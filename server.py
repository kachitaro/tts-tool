"""
Giọng Việt — tool chuyển văn bản thành giọng nói. Các engine nằm trong engines/ (plugin):
  • edge-tts   : nhanh, nhẹ, cần internet (giọng neural của Microsoft Edge)
  • VieNeu-TTS : chạy offline trên máy, tự nhiên hơn, nhân bản giọng từ 3–5 giây audio
Thư viện giọng (giọng nhân bản, yêu thích) nằm trong library.py → data/.

Chạy:  python server.py   →  mở http://localhost:8000
"""

from __future__ import annotations

import json
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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import bookq
import books
import dialogue
import exporter
import lexicon
import narrate
import settings
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
    library.drop_untagged_previews()  # preview.wav cũ chưa có cache_tag
    bookq.Q.start(book_voices)  # nạp data/queue.json; chương đang dở khi server chết sẽ chạy tiếp
    yield
    await bookq.Q.stop()  # dừng ở ranh giới mảnh, trả chương dở về hàng đợi


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

class NoCacheStatic(StaticFiles):
    """CSS / JS của giao diện: luôn hỏi lại server (có ETag) để sửa file là thấy ngay, không dính bản cũ trong trình duyệt."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "no-cache"
        return r


app.mount("/css", NoCacheStatic(directory=ROOT / "static" / "css"), name="css")
app.mount("/js", NoCacheStatic(directory=ROOT / "static" / "js"), name="js")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/settings")
def settings_get():
    return settings.load()


@app.get("/api/settings/info")
def settings_info():
    """Chỉ đọc, cho khối "Nâng cao" của Cài đặt chung: các giá trị đặt bằng biến môi trường khi mở tool."""
    return {
        "vieneu_mode": os.getenv("VIENEU_MODE", "v3turbo"),
        "precision": bookq.current_precision(),
        "segment_chars": books.SEGMENT_CHARS,
        "cache_bytes": dialogue._dir_size(dialogue.CACHE) if dialogue.CACHE.is_dir() else 0,
        "cache_max_bytes": dialogue.CACHE_MAX_BYTES,
    }


class SettingsIn(BaseModel):
    default_voice: dict | None = None   # {"engine", "voice"} hoặc null = bỏ chọn


@app.put("/api/settings")
async def settings_put(body: SettingsIn):
    """Lưu cài đặt chung. default_voice phải là giọng đang có và dùng được; null để bỏ chọn."""
    dv = body.default_voice
    if dv is not None:
        e = get_engine(str(dv.get("engine", "")))
        voice = str(dv.get("voice", ""))
        check_lib_voice(e, voice)
        try:
            known = {v["id"] for v in await engine_voices(e)}
        except Exception as ex:
            raise HTTPException(e.error_status, f"Không kiểm tra được danh sách giọng: {ex}")
        if voice not in known:
            raise HTTPException(400, f"Không có giọng '{voice}'.")
        dv = {"engine": e.id, "voice": voice}
    try:
        return settings.save(dv)
    except settings.SettingsError as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/overview")
def overview():
    """Chỉ đọc, gộp dữ liệu có sẵn cho màn chính và thanh trên cùng bằng 1 request:
    queue = trạng thái hàng đợi tạo sách nói; books = mỗi truyện kèm số chương đã xong; current = truyện đang tạo (nếu có) + ước tính."""
    q = bookq.Q.status()
    queued_by_book: dict[str, int] = {}
    for it in bookq.Q.s["items"]:
        queued_by_book[it["book"]] = queued_by_book.get(it["book"], 0) + 1
    items = []
    for b in books.list_books():
        done = 0
        if b["status"] == "ready":
            done = sum(1 for c in books.list_chapters(b["id"]) if c.get("status") in ("done", "exported"))
        items.append({**b, "done": done, "queued": queued_by_book.get(b["id"], 0),
                      "running": bool(q["running"] and q["running"]["book"] == b["id"])})
    current = None
    active = (q["running"] or {}).get("book") or next(iter(queued_by_book), None)
    if active and (q["running"] or queued_by_book):
        book = next((i for i in items if i["id"] == active), None)
        if book:
            try:
                bs = bookq.Q.book_status(active, books.get(active)["voice"]["engine"])
            except books.NotFound:
                bs = {}
            current = {"book": active, "title": book["title"], "chapters": book["chapters"], "done": book["done"],
                       "chapter": (q["running"] or {}).get("n"), "paused": q["paused"], "state": q["state"],
                       "estimate_seconds": bs.get("estimate_seconds"), "note": q["note"]}
    return {"queue": q, "books": items, "current": current}


@app.get("/api/engines")
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
            raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}")
        for old in d.glob("preview.*"):  # bản của tag khác (precision / mode cũ)
            old.unlink(missing_ok=True)
        cached = d / f"{stem}.{'mp3' if mime == 'audio/mpeg' else 'wav'}"
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


# ───────────────────────────── sách nói ─────────────────────────────

def default_book_voice() -> dict:
    """Giọng kể mặc định của truyện mới: giọng mặc định người dùng đã chọn (nếu còn dùng được), không thì VieNeu (Hải Đăng), không thì edge."""
    chosen = settings.load()["default_voice"]
    if chosen:
        e = ENGINES.get(chosen["engine"])
        try:
            if e and e.installed():
                check_lib_voice(e, chosen["voice"])
                return dict(chosen)
        except HTTPException:
            pass  # giọng đã bị xoá / không còn dùng được: quay về mặc định của tool
    v = ENGINES.get("vieneu")
    if v and v.installed():
        return {"engine": "vieneu", "voice": "Hải Đăng"}
    return {"engine": "edge", "voice": "vi-VN-HoaiMyNeural"}


def book_or_404(book_id: str) -> dict:
    try:
        return books.get(book_id)
    except books.NotFound:
        raise HTTPException(404, "Không tìm thấy truyện.")


def busy_check(book_id: str) -> None:
    """Tách lại chương / xoá truyện xoá audio đã dựng: không làm khi chương của truyện này đang chạy; chương đang chờ thì bỏ khỏi hàng đợi."""
    if bookq.Q.running and bookq.Q.running["book"] == book_id:
        raise HTTPException(409, "Đang tạo audio cho truyện này. Hãy huỷ hàng đợi (hoặc đợi chương đang chạy xong) rồi thử lại.")
    bookq.Q.forget_book(book_id)


class SplitIn(BaseModel):
    regex: str | None = None
    mode: str | None = None
    ops: list[dict] | None = None
    selector: str | None = None
    clean: dict | None = None
    exceptions: list[dict] | None = None


class BookPatch(BaseModel):
    title: str | None = None
    author: str | None = None
    voice: dict | None = None
    speed: int | None = None
    normalize: bool | None = None
    read_title: bool | None = None
    paragraph_pause_s: float | None = None
    title_pause_s: float | None = None
    split: dict | None = None
    clean: dict | None = None
    exceptions: list[dict] | None = None
    lexicon: list[dict] | None = None
    dialogue_voice: dict | None = None
    dismiss_trial: bool | None = None   # "Để sau" trên banner tạo thử: bỏ book["trial"]


async def build_book(book_id: str, book: dict, body: SplitIn) -> tuple[dict, dict]:
    """Tách chương + làm sạch với cài đặt đã lưu, ghi đè bởi body (xem trước hoặc xác nhận). Trả (built, settings)."""
    try:
        settings = books.overrides(book, body.model_dump())
        built = await anyio.to_thread.run_sync(lambda: books.build(books.load_docs(book_id, settings["split"].get("selector")), settings))
    except books.BookError as ex:
        raise HTTPException(400, str(ex))
    return built, settings


@app.get("/api/books")
def books_list():
    return books.list_books()


@app.post("/api/books/import")
async def books_import(files: list[UploadFile] = File(...), title: str = Form(""), author: str = Form("")):
    data = []
    for f in files:
        raw = await f.read(books.MAX_FILE_BYTES + 1)
        if len(raw) > books.MAX_FILE_BYTES:
            raise HTTPException(413, f"'{f.filename}' quá lớn (tối đa {books.MAX_FILE_BYTES // 2**20} MB).")
        data.append((f.filename or "file.txt", raw))
    try:
        return await anyio.to_thread.run_sync(books.import_files, data, title, author, default_book_voice())
    except books.BookError as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/masked-words")
def masked_words_get():
    return books.load_masked()


class MaskedIn(BaseModel):
    masked: str
    correct: str


@app.post("/api/masked-words")
def masked_words_add(body: MaskedIn):
    """Thêm từ vào từ điển từ bị che (từ màn xem trước: "từ đúng là…"). 400 nếu từ đúng không khớp từ bị che."""
    try:
        return books.add_masked_word(body.masked, body.correct)
    except books.BookError as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/books/{book_id}")
def books_get(book_id: str):
    book = book_or_404(book_id)
    return {**book, "chapters_list": books.list_chapters(book_id) if book["status"] == "ready" else [],
            "rules_catalog": [{"name": n, "label": label} for n, label in books.RULES],
            "default_regex": books.DEFAULT_SPLIT_REGEX}


@app.patch("/api/books/{book_id}")
def books_patch(book_id: str, body: BookPatch):
    book = book_or_404(book_id)
    try:
        if body.title is not None:
            if not body.title.strip():
                raise books.BookError("Tên truyện không được để trống.")
            book["title"] = body.title.strip()[:200]
        if body.author is not None:
            book["author"] = body.author.strip()[:200]
        if body.voice is not None:
            e = get_engine(str(body.voice.get("engine", "")))
            check_lib_voice(e, str(body.voice.get("voice", "")))
            book["voice"] = {"engine": e.id, "voice": str(body.voice["voice"])}
        if body.speed is not None:
            book["speed"] = max(-50, min(200, body.speed))
        if body.normalize is not None:
            book["normalize"] = body.normalize
        if body.read_title is not None:
            book["read_title"] = body.read_title
        if body.paragraph_pause_s is not None:
            book["paragraph_pause_s"] = books.validate_pause(body.paragraph_pause_s, "Nghỉ giữa các đoạn văn", 3)
        if body.title_pause_s is not None:
            book["title_pause_s"] = books.validate_pause(body.title_pause_s, "Nghỉ sau tiêu đề", 5)
        if body.split is not None:
            sp = {**book["split"], **{k: v for k, v in body.split.items() if k in ("regex", "mode", "ops", "selector")}}
            books.compile_split(sp["regex"])
            if "selector" in sp:
                sp["selector"] = books.validate_selector(sp["selector"])
            if sp["mode"] not in ("regex", "per_file"):
                raise books.BookError("mode phải là 'regex' hoặc 'per_file'.")
            book["split"] = sp
        if body.clean is not None:
            book["clean"] = books.validate_clean(body.clean)
        if body.exceptions is not None:
            book["exceptions"] = books.validate_exceptions(body.exceptions)
        if body.lexicon is not None:
            book["lexicon"] = lexicon.validate(body.lexicon)
        if body.dismiss_trial:
            book.pop("trial", None)
        if body.dialogue_voice is not None:
            dv = body.dialogue_voice
            e = get_engine(str(dv.get("engine", "")))
            check_lib_voice(e, str(dv.get("voice", "")))
            book["dialogue_voice"] = {"enabled": bool(dv.get("enabled")), "engine": e.id, "voice": str(dv["voice"])}
    except (books.BookError, lexicon.LexiconError) as ex:
        raise HTTPException(400, str(ex))
    books.save(book)
    return book


@app.delete("/api/books/{book_id}")
def books_delete(book_id: str):
    book_or_404(book_id)
    busy_check(book_id)
    books.delete(book_id)
    return {"deleted": book_id}


@app.post("/api/books/{book_id}/preview")
async def books_preview(book_id: str, body: SplitIn | None = None):
    """Xem trước danh sách chương với cài đặt hiện tại (có thể ghi đè bằng body); không ghi gì ra đĩa."""
    built, _ = await build_book(book_id, book_or_404(book_id), body or SplitIn())
    chapters = books.summarize(built)
    return {"chapters": chapters, "stats": built["stats"], "rules": built["rules"], "dropped": built["dropped"],
            "masked_unknown": built["masked_unknown"], "warnings": built["warnings"],
            "total_chars": sum(c["chars"] for c in chapters)}


@app.post("/api/books/{book_id}/chapters")
async def books_confirm(book_id: str, body: SplitIn | None = None):
    """Xác nhận tách chương: ghi chapters/ (thay chương cũ) và lưu cài đặt tách/làm sạch."""
    book = book_or_404(book_id)
    built, settings = await build_book(book_id, book, body or SplitIn())
    busy_check(book_id)
    try:
        return books.confirm(book_id, built, settings)
    except books.BookError as ex:
        raise HTTPException(400, str(ex))


@app.get("/api/books/{book_id}/chapters")
def books_chapters(book_id: str):
    book = book_or_404(book_id)
    chs = books.list_chapters(book_id)
    try:  # audio đã dựng bằng cấu hình cũ (đổi giọng, tốc độ, từ điển…) → stale
        narr, dlg = book_voices(book)
        sig = bookq.signature(book, narr, dlg, lexicon.load_global())
    except HTTPException:
        sig = None
    for c in chs:
        c["stale"] = bool(sig and c.get("status") == "done" and c.get("sig") != sig)
    return chs


@app.get("/api/books/{book_id}/chapters/{n}")
def books_chapter(book_id: str, n: int):
    book = book_or_404(book_id)
    try:
        meta, body = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.")
    return {**meta, "text": body, "reading_text": books.reading_text(book, meta, body)}


def book_voices(book: dict):
    """(giọng kể, giọng lời thoại hoặc None) dạng (engine, voice); kiểm tra engine + giọng thư viện."""
    def one(v: dict):
        e = get_engine(v["engine"])
        check_lib_voice(e, v["voice"])
        return e, v["voice"]
    dv = book.get("dialogue_voice") or {}
    return one(book["voice"]), (one(dv) if dv.get("enabled") else None)


async def speak_book(book: dict, text: str, use_lexicon: bool = True) -> tuple[bytes, float]:
    narr, dlg = book_voices(book)
    try:
        wav = await narrate.render(text, narr, dlg, book["speed"], book["normalize"],
                                   book.get("lexicon") if use_lexicon else None,
                                   lexicon.load_global() if use_lexicon else None)
        data, _ = await anyio.to_thread.run_sync(dialogue.encode_outputs, wav, False)
    except Exception as ex:
        raise HTTPException(narr[0].error_status, f"{narr[0].name} lỗi: {ex}")
    return data, len(wav) / dialogue.SR


@app.get("/api/books/{book_id}/chapters/{n}/sample")
async def books_sample(book_id: str, n: int, use_lexicon: bool = True):
    """Nghe thử đầu chương (~300 ký tự, có đọc tiêu đề) bằng giọng + từ điển + giọng lời thoại của truyện. Chạy ngay
    (không qua hàng đợi) nhưng vào khoá model trước việc nền. Bản dài hơn: POST …/trial."""
    book = book_or_404(book_id)
    try:
        meta, body = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.")
    text = narrate.join_paras(books.excerpt_paras(books.paragraphs(book, meta, body), 300))
    data, seconds = await speak_book(book, text, use_lexicon)
    return Response(data, media_type="audio/wav", headers={"X-Sample-Seconds": f"{seconds:.1f}", "X-Sample-Chars": str(len(text))})


class SpeakIn(BaseModel):
    text: str
    use_lexicon: bool = True


@app.post("/api/books/{book_id}/speak")
async def books_speak(book_id: str, body: SpeakIn):
    """Đọc một đoạn văn bản bất kỳ bằng giọng của truyện (nghe thử câu ví dụ của gợi ý từ điển)."""
    text = body.text.strip()
    if not text or len(text) > 2000:
        raise HTTPException(400, "Văn bản phải từ 1 đến 2000 ký tự.")
    data, seconds = await speak_book(book_or_404(book_id), text, body.use_lexicon)
    return Response(data, media_type="audio/wav", headers={"X-Sample-Seconds": f"{seconds:.1f}"})


@app.post("/api/books/{book_id}/lexicon/apply")
def books_lexicon_apply(book_id: str, body: SpeakIn):
    """Văn bản sau khi qua từ điển của truyện + toàn cục (để kiểm tra; chưa qua chuẩn hoá và tách lời thoại)."""
    book = book_or_404(book_id)
    return {"text": lexicon.apply(body.text, book.get("lexicon"), lexicon.load_global())}


@app.get("/api/books/{book_id}/suggest")
async def books_suggest(book_id: str, min_count: int = 3, limit: int = 200):
    """Gợi ý tên riêng: cụm viết hoa 2–4 tiếng KHÔNG đứng đầu câu, lặp ≥ min_count lần (bỏ cụm đã có trong từ điển)."""
    book = book_or_404(book_id)
    if book["status"] != "ready":
        raise HTTPException(400, "Hãy tách chương trước.")
    known = {e["match"] for e in (book.get("lexicon") or []) + lexicon.load_global()}
    terms = await anyio.to_thread.run_sync(
        lambda: lexicon.suggest_terms(books.iter_chapters(book_id), known, max(1, min_count), max(1, min(limit, 1000))))
    return {"terms": [{"phrase": t.phrase, "count": t.count, "chapter": t.chapter, "example": t.example, "parent": t.parent} for t in terms]}


@app.get("/api/lexicon")
def lexicon_get():
    return lexicon.load_global()


@app.put("/api/lexicon")
def lexicon_put(entries: list[dict]):
    try:
        return lexicon.save_global(entries)
    except lexicon.LexiconError as ex:
        raise HTTPException(400, str(ex))


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


# ───────────── hàng đợi tạo audio (Phase 6c) ─────────────

class TrialIn(BaseModel):
    chars: int = 900
    offset: float = 0.0


@app.post("/api/books/{book_id}/chapters/{n}/trial")
async def books_trial(book_id: str, n: int, body: TrialIn | None = None):
    """"Đọc thử 1 phút": xếp một đoạn ~900 ký tự vào hàng đợi ưu tiên cao nhất (chen vào giữa hai mảnh của chương đang chạy).
    offset 0..1 là vị trí bắt đầu trong chương (0 = đầu chương, có đọc tiêu đề). Hỏi tiến độ: GET /api/trials/{id}."""
    body = body or TrialIn()
    book = book_or_404(book_id)
    if not 50 <= body.chars <= 3000 or not 0 <= body.offset <= 1:
        raise HTTPException(400, "chars phải từ 50 đến 3000 và offset từ 0 đến 1.")
    try:
        meta, text = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.")
    narr, dlg = book_voices(book)
    excerpt = narrate.join_paras(books.excerpt_paras(books.paragraphs(book, meta, text, title=body.offset == 0), body.chars, body.offset))
    try:
        t = bookq.Q.submit_trial(book, n, excerpt, narr, dlg)
    except (bookq.QueueError, ValueError) as ex:
        raise HTTPException(400, str(ex))
    return {"id": t.id, "total": t.total, "chars": len(excerpt)}


def trial_or_404(tid: str) -> bookq.Trial:
    t = bookq.Q.trials.get(tid)
    if t is None:
        raise HTTPException(404, "Không tìm thấy bản đọc thử (đã hết hạn?).")
    return t


@app.get("/api/trials/{tid}")
def trial_status(tid: str):
    t = trial_or_404(tid)
    return {"id": t.id, "status": t.status, "done": t.done, "total": t.total, "seconds": round(t.seconds, 1), "error": t.error}


@app.get("/api/trials/{tid}/audio")
def trial_audio(tid: str):
    t = trial_or_404(tid)
    if t.status != "done":
        raise HTTPException(409, "Bản đọc thử chưa xong.")
    return Response(t.wav, media_type="audio/wav")


def queue_state(book_id: str | None = None) -> dict:
    if book_id is None:
        return bookq.Q.status()
    book = book_or_404(book_id)
    out = bookq.Q.book_status(book_id, book["voice"]["engine"])
    out["exports"] = exporter.list_files(book_id)
    out["trial"] = book.get("trial")   # {limit, done_at} khi truyện đang ở giai đoạn "tạo thử N chương"
    n, size = books.purgeable(book_id)
    out["purgeable"] = {"chapters": n, "bytes": size}
    try:
        out["bench"] = json.loads(bookq.BENCH_PATH.read_text(encoding="utf-8")).get("vieneu")
    except (OSError, ValueError):
        out["bench"] = None
    return out


@app.get("/api/queue")
def queue_get(book: str | None = None):
    return queue_state(book)


class RunIn(BaseModel):
    chapters: list[int] | None = None   # None = mọi chương chưa xong của truyện
    limit: int | None = None            # chỉ lấy N chương đầu trong danh sách trên ("Chạy thử 5 chương đầu")
    regenerate: bool = False            # xoá audio cũ và dựng lại bằng model (bỏ qua cache)
    stale_only: bool = False            # chỉ chương đã dựng bằng cấu hình cũ (kèm regenerate)
    trial: bool = False                 # "tạo thử N chương" (N = limit): ghi book["trial"], xong thì banner "Tạo tiếp"


@app.post("/api/books/{book_id}/queue/run")
def queue_run(book_id: str, body: RunIn | None = None):
    body = body or RunIn()
    book = book_or_404(book_id)
    if book["status"] != "ready":
        raise HTTPException(400, "Hãy tách chương trước.")
    book_voices(book)  # báo lỗi giọng (thiếu engine / giọng đã xoá) ngay thay vì làm mọi chương lỗi
    chs = books.list_chapters(book_id)
    if body.chapters is not None:
        ns = body.chapters
    elif body.stale_only:
        stale = {c["n"] for c in books_chapters(book_id) if c["stale"]}
        ns = [c["n"] for c in chs if c["n"] in stale]
    else:  # mặc định: chương chưa xong; regenerate không kèm danh sách: dựng lại tất cả
        ns = [c["n"] for c in chs if body.regenerate or c.get("status") not in ("done", "exported")]
    if body.limit is not None:
        ns = ns[: max(0, body.limit)]
    if not ns:
        raise HTTPException(400, "Không có chương nào cần tạo.")
    if body.trial and body.limit is None:
        raise HTTPException(400, "Tạo thử cần số chương (limit).")
    try:
        res = bookq.Q.enqueue(book_id, ns, regenerate=body.regenerate)
    except bookq.QueueError as ex:
        raise HTTPException(400, str(ex))
    if body.trial:
        book["trial"] = {"limit": len(ns), "done_at": None}
    elif body.chapters is None and not body.stale_only:  # "Tạo tiếp" / tạo cả truyện: hết giai đoạn thử
        book.pop("trial", None)
    books.save(book)
    return {**res, **queue_state(book_id)}


class FocusIn(BaseModel):
    n: int


@app.post("/api/books/{book_id}/queue/focus")
def queue_focus(book_id: str, body: FocusIn):
    """Chương đang mở trên giao diện: nếu đang chờ trong hàng đợi thì chạy trước."""
    book_or_404(book_id)
    return {"moved": bookq.Q.focus(book_id, body.n)}


@app.post("/api/queue/pause")
def queue_pause():
    bookq.Q.pause()
    return bookq.Q.status()


@app.post("/api/queue/resume")
def queue_resume():
    bookq.Q.resume()
    return bookq.Q.status()


class CancelIn(BaseModel):
    book: str | None = None


@app.post("/api/queue/cancel")
def queue_cancel(body: CancelIn | None = None):
    n = bookq.Q.cancel(body.book if body else None)
    return {"cancelled": n, **bookq.Q.status()}


class QueueSettings(BaseModel):
    inhibit_sleep: bool


@app.post("/api/queue/settings")
def queue_settings(body: QueueSettings):
    bookq.Q.set_inhibit(body.inhibit_sleep)
    return bookq.Q.status()


@app.get("/api/books/{book_id}/disk")
def books_disk(book_id: str):
    """Dung lượng đã dùng của truyện (byte): tổng, audio gốc (FLAC + đoạn dở), file xuất, còn lại."""
    book_or_404(book_id)
    return books.disk_usage(book_id)


@app.post("/api/books/{book_id}/audio/purge-exported")
def books_purge_exported(book_id: str):
    """Xoá FLAC của chương đã xuất. Chương chuyển sang "exported": không nghe lại / xuất lại được nữa cho tới khi Tạo lại."""
    book_or_404(book_id)
    n, freed = books.purge_exported(book_id)
    return {"deleted": n, "freed": freed, **books.disk_usage(book_id)}


@app.get("/api/books/{book_id}/chapters/{n}/audio.mp3")
async def books_chapter_audio(book_id: str, n: int, kbps: int = 64):
    """MP3 của chương đã dựng (nghe lại trong trình duyệt / tải về)."""
    book = book_or_404(book_id)
    try:
        meta, _ = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.")
    if meta.get("status") != "done" or not books.chapter_audio(book_id, n).is_file():
        raise HTTPException(409, "Chương này chưa được tạo audio.")
    try:
        path = await anyio.to_thread.run_sync(exporter.chapter_mp3, book, meta, kbps, book["chapters"]["count"])
    except exporter.ExportError as ex:
        raise HTTPException(400, str(ex))
    return FileResponse(path, media_type="audio/mpeg", filename=f"{n:04d} - {exporter.safe_name(meta.get('title') or str(n))}.mp3")


class ExportIn(BaseModel):
    kind: str = "mp3zip"                # mp3zip | m4b
    chapters: list[int] | None = None   # None = mọi chương đã xong
    kbps: int = 64                      # MP3: 64 / 80 / 96 (m4b luôn AAC 64k)


@app.post("/api/books/{book_id}/export")
async def books_export(book_id: str, body: ExportIn):
    book = book_or_404(book_id)
    try:
        j = exporter.start(book, body.kind, body.chapters, body.kbps)
    except exporter.ExportError as ex:
        raise HTTPException(400, str(ex))
    return {"id": j.id, "total": j.total}


@app.get("/api/exports/{jid}")
def export_status(jid: str):
    j = exporter.JOBS.get(jid)
    if j is None:
        raise HTTPException(404, "Không tìm thấy việc xuất (đã hết hạn?).")
    return {"id": j.id, "book": j.book, "kind": j.kind, "status": j.status, "done": j.done, "total": j.total, "chapters": j.chapters,
            "file": j.file, "size": j.size, "error": j.error}


@app.get("/api/books/{book_id}/export/{name}")
def books_export_file(book_id: str, name: str):
    book_or_404(book_id)
    try:
        path = exporter.file_path(book_id, name)
    except exporter.ExportError as ex:
        raise HTTPException(404, str(ex))
    return FileResponse(path, filename=path.name, media_type="audio/mp4" if path.suffix == ".m4b" else "application/zip")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    print(f"\n  ▶  Mở trình duyệt: http://localhost:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port)
