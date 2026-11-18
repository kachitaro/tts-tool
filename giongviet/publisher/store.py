"""Kho bài của laptop đăng bài: posts.json + media/<id>/<tên file>.

Chạy trên máy yếu nên chỉ dùng thư viện chuẩn: KHÔNG import library / engines / numpy.
shortcut: giữ cả danh sách bài trong RAM và ghi lại toàn bộ file mỗi lần đổi, đủ cho vài trăm bài; nhiều hơn thì chuyển sang sqlite.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path


class Store:
    def __init__(self, data: Path) -> None:
        self.data = data
        self.path = data / "posts.json"
        self.media = data / "media"
        self.lock = threading.RLock()
        self.media.mkdir(parents=True, exist_ok=True)
        try:
            self.posts: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            self.posts = {}
        for p in (
            self.posts.values()
        ):  # đang "running" khi tiến trình chết → đăng lại các kênh chưa xong
            if p["status"] == "running":
                p["status"] = "pending"
        self._save()

    def _save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.posts, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def post_dir(self, pid: str) -> Path:
        return self.media / pid

    def media_path(self, p: dict) -> Path | None:
        if not p.get("filename"):
            return None
        f = self.post_dir(p["id"]) / p["filename"]
        return f if f.is_file() else None

    def get(self, pid: str) -> dict | None:
        with self.lock:
            p = self.posts.get(pid)
            return dict(p) if p else None

    def list(self) -> list[dict]:
        with self.lock:
            return sorted((dict(p) for p in self.posts.values()), key=lambda p: p["when"])

    def create(self, post: dict) -> dict:
        with self.lock:
            self.posts[post["id"]] = post
            self._save()
            return dict(post)

    def update(self, pid: str, **kw) -> dict | None:
        with self.lock:
            p = self.posts.get(pid)
            if p is None:
                return None
            p.update(kw)
            self._save()
            return dict(p)

    def delete(self, pid: str) -> None:
        with self.lock:
            self.posts.pop(pid, None)
            self._save()
        shutil.rmtree(self.post_dir(pid), ignore_errors=True)

    def drop_media(self, pid: str) -> None:
        shutil.rmtree(self.post_dir(pid), ignore_errors=True)


def new_post(
    pid: str, channels: list[str], caption: str, when: float, filename: str | None
) -> dict:
    return {
        "id": pid,
        "channels": channels,
        "caption": caption,
        "filename": filename,
        "when": when,
        "status": "pending",  # pending | running | done | error | missed
        "attempts": 0,
        "next_try": 0.0,
        "results": {},  # {kênh: {"ok": bool, "error": str}}
        "created": time.time(),
        "finished": None,
    }
