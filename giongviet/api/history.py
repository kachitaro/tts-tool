"""Lịch sử các lần đọc: /api/history*."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from giongviet import history, library

router = APIRouter()


@router.get("/api/history")
def history_list(kind: str = ""):
    items = history.list_items(kind or None)
    for m in items:  # giọng thư viện đã bị xoá thì UI ghi "(đã xoá)"
        v = m.get("voice") or ""
        m["voice_deleted"] = (
            v.startswith(library.LIB_PREFIX)
            and not (library.VOICES / v[len(library.LIB_PREFIX) :] / "meta.json").is_file()
        )
    return items


@router.get("/api/history/{item_id}/audio")
def history_audio(item_id: str, fmt: str = ""):
    try:
        path, ext = history.audio_path(item_id, fmt or None)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy bản trong lịch sử.") from None
    return FileResponse(
        path, media_type="audio/mpeg" if ext == "mp3" else "audio/wav", filename=f"giong-noi.{ext}"
    )


@router.delete("/api/history/{item_id}")
def history_delete(item_id: str):
    try:
        history.delete(item_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy bản trong lịch sử.") from None
    return {"deleted": item_id}


@router.delete("/api/history")
def history_clear(kind: str = ""):
    return {"deleted": history.clear(kind or None)}
