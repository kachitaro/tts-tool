"""Giọng: engine, danh sách giọng, nhãn tuổi, yêu thích, thư viện giọng nhân bản, trộn giọng."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from giongviet import library
from giongviet.api.common import (
    MAX_CHARS,
    PREVIEW_TEXT,
    add_to_library,
    check_lib_voice,
    engine_voices,
    get_engine,
    lib_entry,
    log,
    read_upload,
    warning_headers,
)
from giongviet.books import voice_age
from giongviet.engines.registry import ENGINES
from giongviet.speech import text_normalize

router = APIRouter()


@router.get("/api/engines")
def engines():
    return {
        e.id: {
            "local": e.local,
            "available": e.installed(),
            "loaded": e.loaded,
            "name": e.name,
            "label": e.label,
            "description": e.description,
            "install_hint": e.install_hint,
            "capabilities": e.capabilities(),
            "precision": e.precision(),
        }
        for e in ENGINES.values()
    }


@router.get("/api/voices")
async def all_voices(engine: str = ""):
    """Gộp giọng của mọi engine đã cài. Engine lỗi bị bỏ qua và báo qua X-TTS-Warning."""
    out, warnings = [], []
    for e in ENGINES.values():
        if (engine and e.id != engine) or not e.installed():
            continue
        try:
            out += [{"engine": e.id, **v} for v in await engine_voices(e)]
        except Exception as ex:
            log.warning("Không lấy được giọng của %s: %s", e.id, ex)
            warnings.append(f"Không nạp được {e.name}: {ex}")
    return JSONResponse(out, headers=warning_headers(warnings))


@router.get("/api/voices/{engine}")
async def voices(engine: str):
    e = get_engine(engine)
    try:
        return await engine_voices(e)
    except Exception as ex:
        raise HTTPException(500, f"Không nạp được {e.name}: {ex}") from ex


class VoiceAgeIn(BaseModel):
    engine: str
    voice: str  # id giọng có sẵn, hoặc "lib:<id>" cho giọng thư viện
    age: str = ""  # "tre" | "trung_nien" | "gia"; "" = bỏ lựa chọn (giọng có sẵn quay về gợi ý)


@router.put("/api/voices/age")
async def voice_age_put(body: VoiceAgeIn):
    """Đặt nhãn tuổi cho một giọng. Giọng thư viện lưu vào meta.json của giọng, giọng có sẵn lưu ở data/voice_ages.json."""
    try:
        voice_age.check(body.age)
        if body.voice.startswith(library.LIB_PREFIX):
            library.update(body.voice[len(library.LIB_PREFIX) :], age=body.age)
        else:
            e = get_engine(body.engine)
            if body.voice not in {v["id"] for v in await e.voices()}:
                raise HTTPException(404, f"Không có giọng '{body.voice}'.")
            voice_age.set_preset(e.id, body.voice, body.age)
    except (voice_age.AgeError, library.LibraryError) as ex:
        raise HTTPException(400, str(ex)) from ex
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.") from None
    return {"engine": body.engine, "voice": body.voice, "age": body.age}


@router.post("/api/favorites")
def favorite(engine: str = Form(...), voice: str = Form(...), favorite: bool = Form(...)):
    try:
        library.set_favorite(engine, voice, favorite)
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.") from None
    return {"engine": engine, "voice": voice, "favorite": favorite}


def voice_name(voice: str) -> str:
    return (
        library.get(voice[len(library.LIB_PREFIX) :])["name"]
        if voice.startswith(library.LIB_PREFIX)
        else voice
    )


async def build_mix(e, voice_a: str, voice_b: str, slider: float, variant: str) -> dict:
    """Kiểm tra điều kiện rồi gọi engine.mix. Giọng nguồn: preset hoặc lib: đã có consent (kể cả giọng mix)."""
    if not e.capabilities()["mix"]:
        raise HTTPException(400, f"Engine '{e.id}' không hỗ trợ trộn giọng.")
    if not voice_a or not voice_b or voice_a == voice_b:
        raise HTTPException(400, "Hãy chọn hai giọng khác nhau.")
    if not 0 <= slider <= 1:
        raise HTTPException(400, "slider phải nằm trong khoảng 0..1.")
    for v in (voice_a, voice_b):
        check_lib_voice(e, v)
        try:
            library.check_mixable(v)
        except library.LibraryError as ex:
            raise HTTPException(400, str(ex)) from ex
    try:
        return await e.mix(voice_a, voice_b, e.slider_to_alpha(slider), variant)
    except ValueError as ex:
        raise HTTPException(400, str(ex)) from ex
    except Exception as ex:
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}") from ex


@router.post("/api/mix")
async def mix_preview(
    voice_a: str = Form(...),
    voice_b: str = Form(...),
    slider: float = Form(0.5),  # 0..1, 1 = giọng A thuần
    text: str = Form(""),
    engine: str = Form("vieneu"),
    variant: str = Form("C"),
):
    text = text.strip() or PREVIEW_TEXT
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Văn bản quá dài (tối đa {MAX_CHARS} ký tự).")
    e = get_engine(engine)
    data = await build_mix(e, voice_a, voice_b, slider, variant)
    try:
        audio, mime = await e.synthesize(
            text_normalize.normalize(text) if e.capabilities().get("normalize") else text,
            "",
            0,
            voice_data=data,
        )
    except Exception as ex:
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}") from ex
    return Response(audio, media_type=mime, headers={"X-Mix-Alpha": f"{data['alpha']:.3f}"})


@router.post("/api/mix/save")
async def mix_save(
    voice_a: str = Form(...),
    voice_b: str = Form(...),
    slider: float = Form(0.5),
    name: str = Form(...),
    tags: str = Form(""),
    gender: str = Form(""),
    region: str = Form(""),
    description: str = Form(""),
    age: str = Form(""),
    engine: str = Form("vieneu"),
    variant: str = Form("C"),
):
    e = get_engine(engine)
    data = await build_mix(e, voice_a, voice_b, slider, variant)
    codes = data["codes"] if data["codes"] is not None else np.zeros(0, dtype=np.int64)
    try:
        meta = library.create_mix(
            engine=e.id,
            cache_name=data["cache_name"],
            arrays={"speaker_emb": data["speaker_emb"], "codes": codes},
            mix_meta={
                "voice_a": voice_a,
                "voice_b": voice_b,
                "voice_a_name": voice_name(voice_a),
                "voice_b_name": voice_name(voice_b),
                "slider": slider,
                "alpha": round(data["alpha"], 4),
                "variant": data["variant"],
                "mode": data["mode"],
                "codes_from": data["codes_from"],
            },
            name=name,
            tags=tags,
            gender=gender,
            region=region,
            description=description,
            age=age,
        )
    except library.LibraryError as ex:
        raise HTTPException(400, str(ex)) from ex
    return lib_entry(meta)


@router.get("/api/library")
def library_list(engine: str = "", tag: str = "", gender: str = ""):
    return [lib_entry(m) for m in library.list_voices(engine or None, tag or None, gender or None)]


@router.post("/api/library")
async def library_add(
    name: str = Form(...),
    engine: str = Form(...),
    tags: str = Form(""),
    gender: str = Form(""),
    region: str = Form(""),
    description: str = Form(""),
    age: str = Form(""),
    consent: bool = Form(False),
    ref_audio: UploadFile = File(...),
):
    e = get_engine(engine)
    meta = await add_to_library(
        e,
        await read_upload(ref_audio),
        consent,
        name=name,
        tags=tags,
        gender=gender,
        region=region,
        description=description,
        age=age,
    )
    return lib_entry(meta)


@router.patch("/api/library/{voice_id}")
def library_patch(
    voice_id: str,
    name: str | None = Form(None),
    tags: str | None = Form(None),
    gender: str | None = Form(None),
    region: str | None = Form(None),
    description: str | None = Form(None),
    age: str | None = Form(None),
    favorite: bool | None = Form(None),
):
    try:
        return lib_entry(
            library.update(
                voice_id,
                name=name,
                tags=tags,
                gender=gender,
                region=region,
                description=description,
                age=age,
                favorite=favorite,
            )
        )
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.") from None
    except library.LibraryError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.delete("/api/library/{voice_id}")
def library_delete(voice_id: str):
    try:
        library.delete(voice_id)
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.") from None
    return {"deleted": voice_id}


@router.get("/api/library/{voice_id}/preview")
async def library_preview(voice_id: str):
    try:
        meta = library.get(voice_id)
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.") from None
    d = library.voice_dir(voice_id)
    e = get_engine(meta["engine"])
    # preview.<cache_tag>.<ext>: đổi precision / mode thì tên khác → tự sinh lại. Engine không có tag (edge) dùng preview.<ext>.
    stem = f"preview.{e.cache_tag()}" if e.cache_tag() else "preview"
    cached = next((p for ext in ("wav", "mp3") if (p := d / f"{stem}.{ext}").is_file()), None)
    if cached is None:
        reason = e.unusable_reason(meta)
        if reason:
            raise HTTPException(400, f"Giọng không dùng được: {reason}.")
        try:
            data, mime = await e.synthesize(PREVIEW_TEXT, library.LIB_PREFIX + voice_id, 0)
        except Exception as ex:
            raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}") from ex
        for old in d.glob("preview.*"):  # bản của tag khác (precision / mode cũ)
            old.unlink(missing_ok=True)
        cached = d / f"{stem}.{'mp3' if mime == 'audio/mpeg' else 'wav'}"
        cached.write_bytes(data)
    return FileResponse(cached, media_type="audio/mpeg" if cached.suffix == ".mp3" else "audio/wav")
