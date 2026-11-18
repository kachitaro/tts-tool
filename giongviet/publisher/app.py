"""API của laptop đăng bài (máy tạo giọng đẩy bài sang đây). Xác thực bằng Bearer token PUBLISHER_TOKEN.

Chỉ phụ thuộc fastapi + httpx: không import gì từ phần TTS của giongviet.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from giongviet.publisher import channels, worker
from giongviet.publisher.store import Store, new_post

DATA = Path(os.getenv("PUBLISHER_DATA", "publisher-data")).resolve()
TOKEN = os.getenv("PUBLISHER_TOKEN", "")
MAX_BYTES = int(float(os.getenv("PUBLISHER_MAX_MB", "200")) * 1024 * 1024)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")  # id làm tên thư mục: chặn path traversal
CAPTION_MAX = 4000

STORE = Store(DATA)


def require_token(request: Request) -> None:
    got = request.headers.get("authorization", "")
    if TOKEN and not secrets.compare_digest(got.encode(), f"Bearer {TOKEN}".encode()):
        raise HTTPException(401, "Sai hoặc thiếu token.")


@asynccontextmanager
async def lifespan(_):
    stop = asyncio.Event()
    task = asyncio.create_task(worker.loop(STORE, stop))
    yield
    stop.set()
    await task  # chờ bài đang đăng dở xong (không bỏ giữa chừng)


app = FastAPI(title="Giọng Việt — đăng bài", lifespan=lifespan)
router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(_, exc: RequestValidationError):
    return JSONResponse({"error": "Dữ liệu gửi lên không hợp lệ."}, status_code=422)


def _post_or_404(pid: str) -> dict:
    p = STORE.get(pid)
    if p is None:
        raise HTTPException(404, "Không tìm thấy bài.")
    return p


@router.get("/channels")
def channels_list():
    sec = channels.load_secrets(DATA)
    return [{"id": c, "configured": channels.configured(sec, c)} for c in channels.CHANNELS]


@router.get("/posts")
def posts_list():
    return STORE.list()


@router.post("/posts")
def posts_create(
    id: str = Form(...),
    channels_: list[str] = Form(..., alias="channels"),
    when: float = Form(...),
    caption: str = Form(""),
    file: UploadFile | None = File(None),
):
    """Tạo bài. Gửi lại cùng id (retry sau khi rớt mạng) trả bài đã có, không tạo thêm."""
    if not ID_RE.match(id):
        raise HTTPException(400, "id không hợp lệ (8–64 ký tự chữ, số, _ hoặc -).")
    if (old := STORE.get(id)) is not None:
        return old
    if not math.isfinite(when) or when <= 0:
        raise HTTPException(400, "Giờ đăng không hợp lệ.")
    if len(caption) > CAPTION_MAX:
        raise HTTPException(400, f"Nội dung dài quá {CAPTION_MAX} ký tự.")
    chans = list(dict.fromkeys(channels_))
    sec = channels.load_secrets(DATA)
    for c in chans:
        if c not in channels.CHANNELS:
            raise HTTPException(400, f"Không có kênh “{c}”.")
        if not channels.configured(sec, c):
            raise HTTPException(400, f"Kênh “{c}” chưa được cấu hình trên laptop (secrets.json).")
    if not chans:
        raise HTTPException(400, "Chưa chọn kênh.")
    name = Path(file.filename or "").name if file else ""
    if file and not name:
        raise HTTPException(400, "File thiếu tên.")
    if file:
        d = STORE.post_dir(id)
        d.mkdir(parents=True, exist_ok=True)
        try:
            n = 0
            with (d / name).open("wb") as out:
                while chunk := file.file.read(1 << 20):
                    n += len(chunk)
                    if n > MAX_BYTES:
                        raise HTTPException(413, "File quá lớn.")
                    out.write(chunk)
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
    return STORE.create(new_post(id, chans, caption, when, name or None))


class PatchIn(BaseModel):
    when: float | None = None
    caption: str | None = None


@router.patch("/posts/{pid}")
def posts_patch(pid: str, body: PatchIn):
    p = _post_or_404(pid)
    if p["status"] != "pending":
        raise HTTPException(409, "Chỉ sửa được bài đang chờ.")
    kw: dict = {}
    if body.when is not None:
        if not math.isfinite(body.when) or body.when <= 0:
            raise HTTPException(400, "Giờ đăng không hợp lệ.")
        kw["when"] = body.when
    if body.caption is not None:
        if len(body.caption) > CAPTION_MAX:
            raise HTTPException(400, f"Nội dung dài quá {CAPTION_MAX} ký tự.")
        kw["caption"] = body.caption
    return STORE.update(pid, **kw)


@router.post("/posts/{pid}/retry")
def posts_retry(pid: str):
    p = _post_or_404(pid)
    if p["status"] not in ("error", "missed"):
        raise HTTPException(409, "Chỉ thử lại được bài lỗi hoặc bị lỡ.")
    if p["filename"] and STORE.media_path(p) is None:
        raise HTTPException(409, "File đính kèm đã bị dọn, hãy gửi lại bài.")
    return STORE.update(
        pid, status="pending", attempts=0, next_try=0.0, finished=None, when=time.time()
    )


@router.delete("/posts/{pid}")
def posts_delete(pid: str):
    p = _post_or_404(pid)
    if p["status"] == "running":
        raise HTTPException(409, "Bài đang được đăng, chưa xoá được.")
    STORE.delete(pid)
    return {"deleted": pid}


app.include_router(router)
