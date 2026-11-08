"""Cài đặt chung của người dùng (data/settings.json). Hiện có: giọng mặc định, báo khi tạo sách nói xong (notify).

Chỉ giữ những gì người dùng chọn; "chưa chọn" = null và giao diện tự chọn giọng có sẵn được đánh dấu ★ đầu tiên của giọng trên máy.
"""

from __future__ import annotations

import json
import threading

import library

PATH = library.DATA / "settings.json"
_lock = threading.Lock()


class SettingsError(ValueError):
    pass


def load() -> dict:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    dv = raw.get("default_voice")
    ok = isinstance(dv, dict) and isinstance(dv.get("engine"), str) and isinstance(dv.get("voice"), str) and dv["engine"] and dv["voice"]
    return {"default_voice": {"engine": dv["engine"], "voice": dv["voice"]} if ok else None,
            "notify": raw.get("notify") is not False}   # mặc định bật


_KEEP = object()


def save(default_voice=_KEEP, notify: bool | None = None) -> dict:
    """default_voice: {"engine", "voice"} hoặc None (xoá lựa chọn); bỏ qua = giữ nguyên. notify: bật/tắt thông báo khi tạo xong.
    Việc kiểm tra giọng có tồn tại do server làm trước khi gọi."""
    if default_voice not in (_KEEP, None) and not (str(default_voice.get("engine", "")).strip() and str(default_voice.get("voice", "")).strip()):
        raise SettingsError("Giọng mặc định cần có engine và voice.")
    with _lock:
        cur = load()
        if default_voice is not _KEEP:
            cur["default_voice"] = None if default_voice is None else {"engine": str(default_voice["engine"]), "voice": str(default_voice["voice"])}
        if notify is not None:
            cur["notify"] = bool(notify)
        PATH.parent.mkdir(parents=True, exist_ok=True)
        library._write_json(PATH, cur)
    return load()
