"""
Giọng Việt — tool chuyển văn bản thành giọng nói. Các engine nằm trong engines/ (plugin):
  • edge-tts   : nhanh, nhẹ, cần internet (giọng neural của Microsoft Edge)
  • VieNeu-TTS : chạy offline trên máy, tự nhiên hơn, nhân bản giọng từ 3–5 giây audio
Thư viện giọng (giọng nhân bản, yêu thích) nằm trong library.py → data/.

Chạy:  python -m giongviet   →  mở http://localhost:8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from giongviet import library, paths
from giongviet.api import books as books_api
from giongviet.api import dialogue as dialogue_api
from giongviet.api import history as history_api
from giongviet.api import read as read_api
from giongviet.api import settings as settings_api
from giongviet.api import sfx as sfx_api
from giongviet.api import voices as voices_api
from giongviet.api.books import book_voices
from giongviet.books import jobs as bookq
from giongviet.speech import dialogue

ROOT = paths.WEB.parent  # gốc repo


@asynccontextmanager
async def lifespan(_):
    dialogue.prune_cache()  # giữ data/cache/ ≤ TTS_CACHE_MB ngay khi khởi động
    library.drop_untagged_previews()  # preview.wav cũ chưa có cache_tag
    bookq.Q.start(book_voices)  # nạp data/queue.json; chương đang dở khi server chết sẽ chạy tiếp
    yield
    await bookq.Q.stop()  # dừng ở ranh giới mảnh, trả chương dở về hàng đợi


app = FastAPI(title="Giọng Việt", lifespan=lifespan)


class NoCacheStatic(StaticFiles):
    """CSS / JS của giao diện: luôn hỏi lại server (có ETag) để sửa file là thấy ngay, không dính bản cũ trong trình duyệt."""

    def file_response(self, *args, **kwargs):
        r = super().file_response(*args, **kwargs)
        r.headers["Cache-Control"] = "no-cache"
        return r


app.mount("/css", NoCacheStatic(directory=paths.WEB / "css"), name="css")
app.mount("/js", NoCacheStatic(directory=paths.WEB / "js"), name="js")


@app.get("/")
def index():
    return FileResponse(paths.WEB / "index.html", headers={"Cache-Control": "no-cache"})


for _r in (settings_api, voices_api, read_api, sfx_api, dialogue_api, books_api, history_api):
    app.include_router(_r.router)


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
