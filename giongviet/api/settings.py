"""Cài đặt chung và trang tổng quan: /api/settings*, /api/overview."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from giongviet import settings
from giongviet.api.common import check_lib_voice, engine_voices, get_engine
from giongviet.books import jobs as bookq
from giongviet.books import store as books
from giongviet.speech import dialogue

router = APIRouter()


@router.get("/api/settings")
def settings_get():
    return settings.load()


@router.get("/api/settings/info")
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
    default_voice: dict | None = (
        None  # {"engine", "voice"} hoặc null = bỏ chọn (không gửi = giữ nguyên)
    )
    notify: bool | None = (
        None  # báo khi tạo sách nói xong (thông báo desktop của server; giao diện web cũng theo)
    )


@router.put("/api/settings")
async def settings_put(body: SettingsIn):
    """Lưu cài đặt chung. default_voice phải là giọng đang có và dùng được; null để bỏ chọn."""
    dv = body.default_voice
    if "default_voice" not in body.model_fields_set:
        dv = settings._KEEP
    elif dv is not None:
        e = get_engine(str(dv.get("engine", "")))
        voice = str(dv.get("voice", ""))
        check_lib_voice(e, voice)
        try:
            known = {v["id"] for v in await engine_voices(e)}
        except Exception as ex:
            raise HTTPException(
                e.error_status, f"Không kiểm tra được danh sách giọng: {ex}"
            ) from ex
        if voice not in known:
            raise HTTPException(400, f"Không có giọng '{voice}'.")
        dv = {"engine": e.id, "voice": voice}
    try:
        return settings.save(dv, body.notify)
    except settings.SettingsError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.get("/api/overview")
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
            done = sum(
                1 for c in books.list_chapters(b["id"]) if c.get("status") in ("done", "exported")
            )
        items.append(
            {
                **b,
                "done": done,
                "queued": queued_by_book.get(b["id"], 0),
                "running": bool(q["running"] and q["running"]["book"] == b["id"]),
            }
        )
    current = None
    active = (q["running"] or {}).get("book") or next(iter(queued_by_book), None)
    if active and (q["running"] or queued_by_book):
        book = next((i for i in items if i["id"] == active), None)
        if book:
            try:
                bs = bookq.Q.book_status(active, books.get(active)["voice"]["engine"])
            except books.NotFound:
                bs = {}
            current = {
                "book": active,
                "title": book["title"],
                "chapters": book["chapters"],
                "done": book["done"],
                "chapter": (q["running"] or {}).get("n"),
                "paused": q["paused"],
                "state": q["state"],
                "estimate_seconds": bs.get("estimate_seconds"),
                "note": q["note"],
            }
    return {"queue": q, "books": items, "current": current}
