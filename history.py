"""Lịch sử các bản đã tạo (tab Đọc và Hội thoại): data/history/<id>.json + <id>.<ext>. Giữ MAX_ITEMS bản mới nhất."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone

import library

HISTORY = library.DATA / "history"
MAX_ITEMS = 50
_lock = threading.Lock()
_ID = re.compile(r"\d{16}-[0-9a-f]{4}")


def _meta_path(item_id: str):
    if not _ID.fullmatch(item_id):
        raise KeyError(item_id)
    return HISTORY / f"{item_id}.json"


def _audio_file(item_id: str, ext: str):
    return HISTORY / f"{item_id}.{ext}"


def save(kind: str, meta: dict, audio: bytes, ext: str, extra: dict[str, bytes] | None = None) -> str:
    """kind: "tts" | "dialogue". meta do nơi gọi quyết định (văn bản, giọng, cast, tốc độ…).
    extra: định dạng đi kèm {"mp3": bytes} lưu cạnh file chính."""
    with _lock:
        HISTORY.mkdir(parents=True, exist_ok=True)
        item_id = f"{time.time_ns() // 1000:016d}-{secrets.token_hex(2)}"  # micro giây: sắp theo id = sắp theo thời gian
        _audio_file(item_id, ext).write_bytes(audio)
        for e, data in (extra or {}).items():
            _audio_file(item_id, e).write_bytes(data)
        record = {**meta, "id": item_id, "kind": kind, "ext": ext, "bytes": len(audio),
                  "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        library._write_json(_meta_path(item_id), record)
        for old in sorted(p.stem for p in HISTORY.glob("*.json"))[:-MAX_ITEMS]:
            _remove(old)
    return item_id


def replace_audio(item_id: str, audio: bytes, ext: str) -> None:
    """Cập nhật audio của một bản (hội thoại sau khi sinh lại một dòng)."""
    with _lock:
        meta = get(item_id)
        if meta["ext"] != ext:
            _audio_file(item_id, meta["ext"]).unlink(missing_ok=True)
        _audio_file(item_id, ext).write_bytes(audio)
        library._write_json(_meta_path(item_id), {**meta, "ext": ext, "bytes": len(audio)})


def get(item_id: str) -> dict:
    path = _meta_path(item_id)
    if not path.is_file():
        raise KeyError(item_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_items(kind: str | None = None) -> list[dict]:
    out = []
    for p in sorted(HISTORY.glob("*.json"), reverse=True) if HISTORY.is_dir() else []:
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not kind or m.get("kind") == kind:
            out.append(m)
    return out


def audio_path(item_id: str, fmt: str | None = None):
    """Đường dẫn audio của bản; fmt chọn định dạng đi kèm (vd. "mp3"), mặc định định dạng chính."""
    ext = fmt or get(item_id)["ext"]
    path = _audio_file(item_id, ext)
    if not path.is_file():
        raise KeyError(item_id)
    return path, ext


def _remove(item_id: str) -> None:
    for e in ("wav", "mp3"):
        _audio_file(item_id, e).unlink(missing_ok=True)
    _meta_path(item_id).unlink(missing_ok=True)


def delete(item_id: str) -> None:
    with _lock:
        get(item_id)
        _remove(item_id)


def clear(kind: str | None = None) -> int:
    with _lock:
        ids = [m["id"] for m in list_items(kind)]
        for i in ids:
            _remove(i)
    return len(ids)
