"""Hàm dùng chung của các router: tìm engine, đọc file tải lên, nhãn giọng, thư viện giọng."""

from __future__ import annotations

import logging
import os
from urllib.parse import quote

import anyio
from fastapi import HTTPException, UploadFile

from giongviet import library
from giongviet.books import voice_age
from giongviet.engines.registry import ENGINES

MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "20000"))
PREVIEW_TEXT = "Xin chào, đây là giọng đọc thử."


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
        meta = library.get(voice[len(library.LIB_PREFIX) :])
    except library.NotFound:
        raise HTTPException(404, "Không tìm thấy giọng trong thư viện.") from None
    if meta["engine"] != e.id:
        raise HTTPException(
            400, f"Giọng này thuộc engine '{meta['engine']}', không dùng được với '{e.id}'."
        )
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
        raise HTTPException(400, str(ex)) from ex
    try:
        await anyio.to_thread.run_sync(e.prepare_reference, library.ref_path(meta["id"]))
    except Exception as ex:
        library.delete(meta["id"])
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}") from ex
    return meta


def unusable(meta: dict) -> str:
    """Lý do giọng thư viện không dùng được với cấu hình hiện tại ("" nếu dùng được)."""
    e = ENGINES.get(meta.get("engine"))
    return (e.unusable_reason(meta) or "") if e else ""


def lib_entry(meta: dict) -> dict:
    reason = unusable(meta)
    return {
        **meta,
        "voice": library.LIB_PREFIX + meta["id"],
        "usable": not reason,
        "unusable_reason": reason,
    }


def lib_as_voice(meta: dict) -> dict:
    """Giọng thư viện dưới dạng phần tử của /api/voices."""
    reason = unusable(meta)
    return {
        "id": library.LIB_PREFIX + meta["id"],
        "label": meta["name"],
        "gender": meta.get("gender", ""),
        "region": meta.get("region", ""),
        "age": meta.get("age", ""),
        "age_source": "user" if meta.get("age") else "",
        "tags": meta.get("tags", []),
        "description": meta.get("description", ""),
        "source": meta.get("source", "clone"),
        "favorite": meta.get("favorite", False),
        "name": meta["name"],
        "usable": not reason,
        "unusable_reason": reason,
        **{k: meta[k] for k in ("voice_a_name", "voice_b_name", "slider") if k in meta},
    }


async def engine_voices(e) -> list[dict]:
    """Giọng của engine (preset) + giọng thư viện thuộc engine đó, kèm cờ favorite."""
    favs = library.favorites()
    ages = voice_age.load()
    out = [
        voice_age.annotate_preset(
            e.id,
            {"source": "preset", "usable": True, **v, "favorite": f"{e.id}:{v['id']}" in favs},
            ages,
        )
        for v in await e.voices()
    ]
    if e.capabilities()["clone"]:
        out += [lib_as_voice(m) for m in library.list_voices(engine=e.id)]
    return out


async def voice_label(e, voice: str) -> str:
    """Tên hiển thị của giọng để lưu vào lịch sử (giọng bị xoá sau này vẫn còn tên)."""
    try:
        if voice.startswith(library.LIB_PREFIX):
            return library.get(voice[len(library.LIB_PREFIX) :])["name"]
        for v in await e.voices():
            if v["id"] == voice:
                return v.get("name") or v["label"]
    except Exception:  # chỉ là nhãn: không làm hỏng việc tạo audio
        pass
    return voice
