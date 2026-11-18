"""Cầu nối sang laptop đăng bài: /api/publish*. Máy này tạo file; laptop (giongviet.publisher) giữ lịch và đăng.

Giao diện không nói chuyện thẳng với laptop: token chỉ nằm ở server máy này, không lộ ra trình duyệt.
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from giongviet import history, settings
from giongviet.api.books import book_or_404
from giongviet.books import exporter
from giongviet.books import store as books

router = APIRouter()
PASS_THROUGH = (
    400,
    404,
    409,
    413,
)  # lỗi của laptop mà người dùng sửa được: giữ nguyên mã và lời nhắn


def _call(method: str, path: str, **kw):
    url, token = settings.publisher()
    if not url:
        raise HTTPException(
            400, "Chưa cài địa chỉ laptop đăng bài (Cài đặt chung → Laptop đăng bài)."
        )
    try:
        r = httpx.request(
            method,
            url + path,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(600, connect=10),
            **kw,
        )
    except httpx.HTTPError as ex:
        raise HTTPException(
            502,
            f"Không kết nối được laptop đăng bài ({type(ex).__name__}). Laptop đang bật và cùng mạng chưa?",
        ) from ex
    if r.status_code >= 400:
        if r.status_code == 401:
            raise HTTPException(
                502, "Laptop từ chối token. Kiểm tra lại token trong Cài đặt chung."
            )
        try:
            msg = r.json()["error"]
        except ValueError, KeyError, TypeError:
            msg = f"Laptop trả lỗi {r.status_code}."
        raise HTTPException(r.status_code if r.status_code in PASS_THROUGH else 502, msg)
    return r.json()


class SourceIn(BaseModel):
    kind: str  # history | chapter | export
    id: str | None = None  # history: id bản trong lịch sử
    book: str | None = None  # chapter, export
    n: int | None = None  # chapter
    name: str | None = None  # export: tên file đã xuất
    kbps: int = 64  # chapter


def _resolve(src: SourceIn) -> tuple[Path, str]:
    """(đường dẫn file, tên file gửi đi). Lỗi → HTTPException."""
    if src.kind == "history":
        for fmt in ("mp3", None):  # ưu tiên MP3: nhẹ hơn nhiều so với WAV
            try:
                path, ext = history.audio_path(src.id or "", fmt)
                return path, f"giong-noi.{ext}"
            except KeyError:
                continue
        raise HTTPException(404, "Không tìm thấy bản trong lịch sử.")
    if src.kind == "chapter":
        book = book_or_404(src.book or "")
        try:
            meta, _ = books.chapter_text(book["id"], src.n or 0)
        except books.NotFound:
            raise HTTPException(404, "Không có chương này.") from None
        if meta.get("status") != "done" or not books.chapter_audio(book["id"], src.n).is_file():
            raise HTTPException(409, "Chương này chưa được tạo audio.")
        try:
            path = exporter.chapter_mp3(book, meta, src.kbps, book["chapters"]["count"])
        except exporter.ExportError as ex:
            raise HTTPException(400, str(ex)) from ex
        return path, f"{src.n:04d} - {exporter.safe_name(meta.get('title') or str(src.n))}.mp3"
    if src.kind == "export":
        book_or_404(src.book or "")
        try:
            path = exporter.file_path(src.book, src.name or "")
        except exporter.ExportError as ex:
            raise HTTPException(404, str(ex)) from ex
        return path, path.name
    raise HTTPException(400, "Nguồn bài không hợp lệ.")


class PublishIn(BaseModel):
    id: str  # giao diện sinh (uuid): gửi lại khi rớt mạng thì laptop không đăng đôi
    source: SourceIn
    channels: list[str]
    caption: str = ""
    when: float  # giây epoch UTC


@router.post("/api/publish/posts")
def publish_create(body: PublishIn):
    path, name = _resolve(body.source)
    with path.open("rb") as f:
        return _call(
            "POST",
            "/api/posts",
            data={
                "id": body.id,
                "channels": body.channels,
                "when": str(body.when),
                "caption": body.caption,
            },
            files={"file": (name, f)},
        )


@router.get("/api/publish/channels")
def publish_channels():
    return _call("GET", "/api/channels")


@router.get("/api/publish/posts")
def publish_list():
    return _call("GET", "/api/posts")


class PublishPatch(BaseModel):
    when: float | None = None
    caption: str | None = None


def _pid(pid: str) -> str:
    return urllib.parse.quote(pid, safe="")


@router.patch("/api/publish/posts/{pid}")
def publish_patch(pid: str, body: PublishPatch):
    return _call("PATCH", f"/api/posts/{_pid(pid)}", json=body.model_dump(exclude_none=True))


@router.post("/api/publish/posts/{pid}/retry")
def publish_retry(pid: str):
    return _call("POST", f"/api/posts/{_pid(pid)}/retry")


@router.delete("/api/publish/posts/{pid}")
def publish_delete(pid: str):
    return _call("DELETE", f"/api/posts/{_pid(pid)}")
