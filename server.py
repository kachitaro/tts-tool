"""
Giọng Việt — tool chuyển văn bản thành giọng nói. Các engine nằm trong engines/ (plugin):
  • edge-tts   : nhanh, nhẹ, cần internet (giọng neural của Microsoft Edge)
  • VieNeu-TTS : chạy offline trên máy, tự nhiên hơn, nhân bản giọng từ 3–5 giây audio
Thư viện giọng (giọng nhân bản, yêu thích) nằm trong library.py → data/.

Chạy:  python server.py   →  mở http://localhost:8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import anyio
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import dialogue
import history
import library
import text_normalize
from engines.registry import ENGINES

ROOT = Path(__file__).parent
MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "20000"))
PREVIEW_TEXT = "Xin chào, đây là giọng đọc thử."


@asynccontextmanager
async def lifespan(_):
    dialogue.prune_cache()  # giữ data/cache/ ≤ TTS_CACHE_MB ngay khi khởi động
    yield


app = FastAPI(title="Giọng Việt", lifespan=lifespan)
log = logging.getLogger("tts")


def get_engine(engine_id: str):
    """Trả engine đã cài, hoặc raise 404/400."""
    engine = ENGINES.get(engine_id)
    if engine is None:
        raise HTTPException(404, "Engine không tồn tại")
    if not engine.installed():
        raise HTTPException(400, f"Chưa cài {engine.name}. Chạy: {engine.install_hint}")
    return engine


def check_lib_voice(e, voice: str) -> None:
    """Giọng "lib:<id>" phải tồn tại, và engine phải là engine nó thuộc về."""
    if not voice.startswith(library.LIB_PREFIX):
        return
    try:
        meta = library.get(voice[len(library.LIB_PREFIX):])
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.")
    if meta["engine"] != e.id:
        raise HTTPException(400, f"Giọng này thuộc engine '{meta['engine']}', không dùng được với '{e.id}'.")
    reason = e.unusable_reason(meta)
    if reason:
        raise HTTPException(400, f"Giọng '{meta['name']}' không dùng được: {reason}.")


def warning_headers(warnings: list[str]) -> dict:
    # Header HTTP chỉ chứa được latin-1 nên tiếng Việt phải percent-encode (UI decodeURIComponent).
    return {"X-TTS-Warning": quote("; ".join(warnings))} if warnings else {}


async def read_upload(f: UploadFile) -> bytes:
    data = await f.read(library.MAX_UPLOAD_BYTES + 1)
    if len(data) > library.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File audio quá lớn (tối đa 30 MB).")
    return data


async def add_to_library(e, data: bytes, consent: bool, **fields) -> dict:
    """Chuẩn hoá audio mẫu → lưu vào thư viện → để engine tiền xử lý/encode. Lỗi thì dọn thư mục."""
    if not e.capabilities()["clone"]:
        raise HTTPException(400, f"Engine '{e.id}' không hỗ trợ nhân bản giọng.")
    try:
        wav, sr = await anyio.to_thread.run_sync(library.normalize_reference, data)
        meta = library.create(engine=e.id, wav=wav, sr=sr, consent=consent, **fields)
    except library.LibraryError as ex:
        raise HTTPException(400, str(ex))
    try:
        await anyio.to_thread.run_sync(e.prepare_reference, library.ref_path(meta["id"]))
    except Exception as ex:
        library.delete(meta["id"])
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}")
    return meta


def unusable(meta: dict) -> str:
    """Lý do giọng thư viện không dùng được với cấu hình hiện tại ("" nếu dùng được)."""
    e = ENGINES.get(meta.get("engine"))
    return (e.unusable_reason(meta) or "") if e else ""


def lib_entry(meta: dict) -> dict:
    reason = unusable(meta)
    return {**meta, "voice": library.LIB_PREFIX + meta["id"], "usable": not reason, "unusable_reason": reason}


def lib_as_voice(meta: dict) -> dict:
    """Giọng thư viện dưới dạng phần tử của /api/voices."""
    reason = unusable(meta)
    return {
        "id": library.LIB_PREFIX + meta["id"], "label": meta["name"], "gender": meta.get("gender", ""),
        "region": meta.get("region", ""), "tags": meta.get("tags", []), "description": meta.get("description", ""),
        "source": meta.get("source", "clone"), "favorite": meta.get("favorite", False), "name": meta["name"],
        "usable": not reason, "unusable_reason": reason,
        **{k: meta[k] for k in ("voice_a_name", "voice_b_name", "slider") if k in meta},
    }


async def engine_voices(e) -> list[dict]:
    """Giọng của engine (preset) + giọng thư viện thuộc engine đó, kèm cờ favorite."""
    favs = library.favorites()
    out = [{"source": "preset", "usable": True, **v, "favorite": f"{e.id}:{v['id']}" in favs} for v in await e.voices()]
    if e.capabilities()["clone"]:
        out += [lib_as_voice(m) for m in library.list_voices(engine=e.id)]
    return out


# ──────────────────────────────── API ────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/engines")
def engines():
    return {
        e.id: {
            "local": e.local,
            "available": e.installed(),
            "loaded": e.loaded,
            "label": e.label,
            "description": e.description,
            "install_hint": e.install_hint,
            "capabilities": e.capabilities(),
        }
        for e in ENGINES.values()
    }


@app.get("/api/voices")
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


@app.get("/api/voices/{engine}")
async def voices(engine: str):
    e = get_engine(engine)
    try:
        return await engine_voices(e)
    except Exception as ex:
        raise HTTPException(500, f"Không nạp được {e.name}: {ex}")


@app.post("/api/favorites")
def favorite(engine: str = Form(...), voice: str = Form(...), favorite: bool = Form(...)):
    try:
        library.set_favorite(engine, voice, favorite)
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.")
    return {"engine": engine, "voice": voice, "favorite": favorite}


async def voice_label(e, voice: str) -> str:
    """Tên hiển thị của giọng để lưu vào lịch sử (giọng bị xoá sau này vẫn còn tên)."""
    try:
        if voice.startswith(library.LIB_PREFIX):
            return library.get(voice[len(library.LIB_PREFIX):])["name"]
        for v in await e.voices():
            if v["id"] == voice:
                return v.get("name") or v["label"]
    except Exception:  # chỉ là nhãn: không làm hỏng việc tạo audio
        pass
    return voice


@app.post("/api/tts")
async def tts(
    text: str = Form(""),
    engine: str = Form("edge"),
    voice: str = Form(""),
    speed: int = Form(0),  # % : 0 = 1x, 100 = 2x, 200 = 3x
    pitch: int = Form(0),  # Hz: chỉ engine có capabilities.pitch
    save_as: str = Form(""),  # có ref_audio + save_as: lưu giọng vào thư viện (cần consent=true)
    consent: bool = Form(False),
    normalize: bool = Form(True),  # chuẩn hoá văn bản (chỉ engine có capabilities.normalize, tức VieNeu)
    ref_audio: UploadFile | None = File(None),
):
    text = text.strip()
    if not text:
        raise HTTPException(400, "Văn bản trống.")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Văn bản quá dài (tối đa {MAX_CHARS} ký tự).")
    speed = max(-50, min(200, speed))
    pitch = max(-50, min(50, pitch))
    e = get_engine(engine)
    check_lib_voice(e, voice)
    synth_text = text_normalize.normalize(text) if normalize and e.capabilities().get("normalize") else text
    pausey = text_normalize.has_pause(text)  # có thẻ [nghỉ Ns]: đi qua pipeline hội thoại (mọi engine)
    if pausey:
        try:
            text_normalize.split_pauses(text)
        except ValueError as ex:
            raise HTTPException(400, str(ex))

    warnings: list[str] = []
    extra_files: dict[str, bytes] = {}
    tmp_path = None
    try:
        if e.capabilities()["clone"] and ref_audio is not None and ref_audio.filename:
            raw = await read_upload(ref_audio)
            if save_as.strip():
                voice = library.LIB_PREFIX + (await add_to_library(e, raw, consent, name=save_as))["id"]
            else:
                import tempfile

                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(ref_audio.filename).suffix or ".wav") as f:
                    f.write(raw)
                    tmp_path = f.name
        if pausey:
            wav = await dialogue.render_text(e, voice, text, speed, normalize, pitch, tmp_path, warnings)
            data, mp3 = await anyio.to_thread.run_sync(dialogue.encode_outputs, wav)
            mime = "audio/wav"
            if mp3:
                extra_files["mp3"] = mp3
            await anyio.to_thread.run_sync(dialogue.prune_cache)
        else:
            data, mime = await e.synthesize(synth_text, voice, speed, pitch=pitch, ref_audio=tmp_path, warnings=warnings)
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    ext = "mp3" if mime == "audio/mpeg" else "wav"
    headers = {"Content-Disposition": f'attachment; filename="giong-noi.{ext}"', **warning_headers(warnings)}
    try:  # lịch sử chỉ là tiện ích: lỗi ghi đĩa không được làm hỏng bản vừa tạo
        headers["X-History-Id"] = history.save("tts", {
            "text": text, "engine": e.id, "voice": voice, "voice_label": await voice_label(e, voice) if voice else "",
            "speed": speed, "pitch": pitch, "normalize": normalize, "cloned_ref": bool(tmp_path),
            "has_mp3": "mp3" in extra_files,
        }, data, ext, extra_files)
    except OSError as ex:
        log.warning("Không lưu được lịch sử: %s", ex)
    return Response(data, media_type=mime, headers=headers)


# ───────────────────────────── trộn giọng ─────────────────────────────

def voice_name(voice: str) -> str:
    return library.get(voice[len(library.LIB_PREFIX):])["name"] if voice.startswith(library.LIB_PREFIX) else voice


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
            raise HTTPException(400, str(ex))
    try:
        return await e.mix(voice_a, voice_b, e.slider_to_alpha(slider), variant)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    except Exception as ex:
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}")


@app.post("/api/mix")
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
            text_normalize.normalize(text) if e.capabilities().get("normalize") else text, "", 0, voice_data=data)
    except Exception as ex:
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}")
    return Response(audio, media_type=mime, headers={"X-Mix-Alpha": f"{data['alpha']:.3f}"})


@app.post("/api/mix/save")
async def mix_save(
    voice_a: str = Form(...),
    voice_b: str = Form(...),
    slider: float = Form(0.5),
    name: str = Form(...),
    tags: str = Form(""),
    gender: str = Form(""),
    region: str = Form(""),
    description: str = Form(""),
    engine: str = Form("vieneu"),
    variant: str = Form("C"),
):
    e = get_engine(engine)
    data = await build_mix(e, voice_a, voice_b, slider, variant)
    codes = data["codes"] if data["codes"] is not None else np.zeros(0, dtype=np.int64)
    try:
        meta = library.create_mix(
            engine=e.id, cache_name=data["cache_name"], arrays={"speaker_emb": data["speaker_emb"], "codes": codes},
            mix_meta={
                "voice_a": voice_a, "voice_b": voice_b, "voice_a_name": voice_name(voice_a),
                "voice_b_name": voice_name(voice_b), "slider": slider, "alpha": round(data["alpha"], 4),
                "variant": data["variant"], "mode": data["mode"], "codes_from": data["codes_from"],
            },
            name=name, tags=tags, gender=gender, region=region, description=description,
        )
    except library.LibraryError as ex:
        raise HTTPException(400, str(ex))
    return lib_entry(meta)



# ───────────────────────────── thư viện giọng ─────────────────────────────

@app.get("/api/library")
def library_list(engine: str = "", tag: str = "", gender: str = ""):
    return [lib_entry(m) for m in library.list_voices(engine or None, tag or None, gender or None)]


@app.post("/api/library")
async def library_add(
    name: str = Form(...),
    engine: str = Form(...),
    tags: str = Form(""),
    gender: str = Form(""),
    region: str = Form(""),
    description: str = Form(""),
    consent: bool = Form(False),
    ref_audio: UploadFile = File(...),
):
    e = get_engine(engine)
    meta = await add_to_library(
        e, await read_upload(ref_audio), consent,
        name=name, tags=tags, gender=gender, region=region, description=description,
    )
    return lib_entry(meta)


@app.patch("/api/library/{voice_id}")
def library_patch(
    voice_id: str,
    name: str | None = Form(None),
    tags: str | None = Form(None),
    gender: str | None = Form(None),
    region: str | None = Form(None),
    description: str | None = Form(None),
    favorite: bool | None = Form(None),
):
    try:
        return lib_entry(library.update(voice_id, name=name, tags=tags, gender=gender, region=region,
                                        description=description, favorite=favorite))
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.")
    except library.LibraryError as ex:
        raise HTTPException(400, str(ex))


@app.delete("/api/library/{voice_id}")
def library_delete(voice_id: str):
    try:
        library.delete(voice_id)
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.")
    return {"deleted": voice_id}


@app.get("/api/library/{voice_id}/preview")
async def library_preview(voice_id: str):
    try:
        meta = library.get(voice_id)
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.")
    d = library.voice_dir(voice_id)
    cached = next(iter(d.glob("preview.*")), None)
    if cached is None:
        e = get_engine(meta["engine"])
        reason = e.unusable_reason(meta)
        if reason:
            raise HTTPException(400, f"Giọng không dùng được: {reason}.")
        try:
            data, mime = await e.synthesize(PREVIEW_TEXT, library.LIB_PREFIX + voice_id, 0)
        except Exception as ex:
            raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}")
        cached = d / ("preview.mp3" if mime == "audio/mpeg" else "preview.wav")
        cached.write_bytes(data)
    return FileResponse(cached, media_type="audio/mpeg" if cached.suffix == ".mp3" else "audio/wav")


# ───────────────────────────── hội thoại ─────────────────────────────

class ScriptIn(BaseModel):
    script: str


class DialogueIn(BaseModel):
    script: str
    cast: dict[str, dict] = {}  # {"Lan": {"engine": "vieneu", "voice": "lib:giong-a"}, ...}
    speed: int = 0
    gap_ms: int = 350
    paragraph_gap_ms: int = 800
    normalize: bool = True


class LineRegenIn(BaseModel):
    seed: int | None = None


def parse_or_400(script: str) -> list:
    try:
        return dialogue.parse_script(script, MAX_CHARS)
    except dialogue.ScriptError as ex:
        raise HTTPException(400, str(ex))


def job_or_404(job_id: str):
    try:
        return dialogue.get_job(job_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy job (đã hết hạn hoặc sai id).")


@app.post("/api/dialogue/parse")
def dialogue_parse(req: ScriptIn):
    lines = parse_or_400(req.script)
    return {"speakers": dialogue.speakers_of(lines), "chars": len(req.script),
            "lines": [{"i": l.i, "speaker": l.speaker, "text": l.text, "pause": l.pause} for l in lines]}


@app.post("/api/dialogue")
async def dialogue_create(req: DialogueIn):
    lines = parse_or_400(req.script)
    if not lines:
        raise HTTPException(400, "Kịch bản trống.")
    cast = {dialogue.norm_name(k): v for k, v in req.cast.items()}
    names = dialogue.speakers_of(lines)
    missing = [n for n in names if not (cast.get(n) or {}).get("engine") or not (cast.get(n) or {}).get("voice")]
    if missing:
        return JSONResponse({"error": "Chưa gán giọng cho: " + ", ".join(missing), "missing": missing}, status_code=400)
    resolved, labels = {}, {}
    for n in names:
        e = get_engine(cast[n]["engine"])
        check_lib_voice(e, cast[n]["voice"])
        resolved[n] = (e, cast[n]["voice"])
        labels[n] = await voice_label(e, cast[n]["voice"])
    meta = {"script": req.script, "cast": {n: {**cast[n], "label": labels[n]} for n in names}, "speed": req.speed,
            "gap_ms": req.gap_ms,
            "paragraph_gap_ms": req.paragraph_gap_ms, "normalize": req.normalize}
    job = dialogue.create_job(lines, resolved, max(-50, min(200, req.speed)),
                              max(0, min(5000, req.gap_ms)), max(0, min(10000, req.paragraph_gap_ms)),
                              normalize=req.normalize, meta=meta)
    return {"job_id": job.id, "total": len(lines)}


@app.get("/api/dialogue/{job_id}")
def dialogue_status(job_id: str):
    dialogue.purge()
    return dialogue.job_info(job_or_404(job_id))


@app.get("/api/dialogue/{job_id}/audio")
def dialogue_audio(job_id: str, fmt: str = "wav"):
    job = job_or_404(job_id)
    if job.status != "done":
        raise HTTPException(409, "Audio chưa sẵn sàng.")
    if fmt not in ("wav", "mp3") or (fmt == "mp3" and not job.has_mp3):
        raise HTTPException(404, "Không có định dạng này (MP3 cần ffmpeg).")
    return FileResponse(job.dir / f"out.{fmt}", media_type="audio/mpeg" if fmt == "mp3" else "audio/wav",
                        filename=f"hoi-thoai.{fmt}")


@app.get("/api/dialogue/{job_id}/line/{i}/audio")
def dialogue_line_audio(job_id: str, i: int):
    job = job_or_404(job_id)
    if not 0 <= i < len(job.lines) or job.states[i].status != "done":
        raise HTTPException(404, "Dòng này chưa có audio.")
    return FileResponse(dialogue.line_path(job, i), media_type="audio/wav")


@app.post("/api/dialogue/{job_id}/line/{i}")
async def dialogue_regen(job_id: str, i: int, req: LineRegenIn | None = None):
    job = job_or_404(job_id)
    if not 0 <= i < len(job.lines):
        raise HTTPException(404, "Không có dòng này.")
    try:
        await dialogue.regen_line(job, i, req.seed if req else None)
    except dialogue.Busy as ex:
        raise HTTPException(409, str(ex))
    return dialogue.job_info(job)


@app.get("/api/projects")
def projects_list():
    return dialogue.list_projects()


@app.post("/api/projects")
def projects_save(data: dict):
    try:
        return dialogue.save_project(data)
    except (dialogue.ProjectError, ValueError, TypeError) as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/projects/{project_id}")
def projects_get(project_id: str):
    try:
        return dialogue.get_project(project_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy dự án.")


@app.delete("/api/projects/{project_id}")
def projects_delete(project_id: str):
    try:
        dialogue.delete_project(project_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy dự án.")
    return {"deleted": project_id}


# ───────────────────────────── lịch sử ─────────────────────────────

@app.get("/api/history")
def history_list(kind: str = ""):
    items = history.list_items(kind or None)
    for m in items:  # giọng thư viện đã bị xoá thì UI ghi "(đã xoá)"
        v = m.get("voice") or ""
        m["voice_deleted"] = v.startswith(library.LIB_PREFIX) and not (library.VOICES / v[len(library.LIB_PREFIX):] / "meta.json").is_file()
    return items


@app.get("/api/history/{item_id}/audio")
def history_audio(item_id: str, fmt: str = ""):
    try:
        path, ext = history.audio_path(item_id, fmt or None)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy bản trong lịch sử.")
    return FileResponse(path, media_type="audio/mpeg" if ext == "mp3" else "audio/wav", filename=f"giong-noi.{ext}")


@app.delete("/api/history/{item_id}")
def history_delete(item_id: str):
    try:
        history.delete(item_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy bản trong lịch sử.")
    return {"deleted": item_id}


@app.delete("/api/history")
def history_clear(kind: str = ""):
    return {"deleted": history.clear(kind or None)}


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError):
    return JSONResponse({"error": "Dữ liệu gửi lên không hợp lệ."}, status_code=422)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    print(f"\n  ▶  Mở trình duyệt: http://localhost:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port)
