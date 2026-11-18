"""Cài đặt chung của người dùng (data/settings.json). Hiện có: giọng mặc định, báo khi tạo sách nói xong (notify).

Chỉ giữ những gì người dùng chọn; "chưa chọn" = null và giao diện tự chọn giọng có sẵn được đánh dấu ★ đầu tiên của giọng trên máy.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from giongviet import library

PATH = library.DATA / "settings.json"
_lock = threading.Lock()


class SettingsError(ValueError):
    pass


def load() -> dict:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except OSError, ValueError:
        raw = {}
    dv = raw.get("default_voice")
    ok = (
        isinstance(dv, dict)
        and isinstance(dv.get("engine"), str)
        and isinstance(dv.get("voice"), str)
        and dv["engine"]
        and dv["voice"]
    )
    url = raw.get("publisher_url")
    return {
        "default_voice": {"engine": dv["engine"], "voice": dv["voice"]} if ok else None,
        "notify": raw.get("notify") is not False,  # mặc định bật
        "publisher_url": url if isinstance(url, str) else "",
        "publisher_token_set": bool(raw.get("publisher_token")),  # token không bao giờ trả ra ngoài
    }


def publisher() -> tuple[str, str]:
    """(địa chỉ, token) của laptop đăng bài; chỉ cho code phía server dùng."""
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except OSError, ValueError:
        raw = {}
    url, token = raw.get("publisher_url"), raw.get("publisher_token")
    return (url if isinstance(url, str) else "", token if isinstance(token, str) else "")


_KEEP = object()


def save(
    default_voice: Any = _KEEP,
    notify: bool | None = None,
    publisher_url: str | None = None,
    publisher_token: str | None = None,
) -> dict:
    """default_voice: {"engine", "voice"} hoặc None (xoá lựa chọn); bỏ qua = giữ nguyên. notify: bật/tắt thông báo khi tạo xong.
    publisher_url / publisher_token: laptop đăng bài ("" = xoá, None = giữ nguyên).
    Việc kiểm tra giọng có tồn tại do server làm trước khi gọi."""
    if default_voice not in (_KEEP, None) and not (
        str(default_voice.get("engine", "")).strip() and str(default_voice.get("voice", "")).strip()
    ):
        raise SettingsError("Giọng mặc định cần có engine và voice.")
    with _lock:
        cur = load()
        cur.pop("publisher_token_set")  # chỉ để hiển thị; token thật lấy lại từ file bên dưới
        cur["publisher_token"] = publisher()[1]
        if default_voice is not _KEEP:
            cur["default_voice"] = (
                None
                if default_voice is None
                else {"engine": str(default_voice["engine"]), "voice": str(default_voice["voice"])}
            )
        if notify is not None:
            cur["notify"] = bool(notify)
        if publisher_url is not None:
            url = publisher_url.strip().rstrip("/")
            if url and not url.startswith(("http://", "https://")):
                raise SettingsError("Địa chỉ laptop phải bắt đầu bằng http:// hoặc https://.")
            cur["publisher_url"] = url
        if publisher_token is not None:
            cur["publisher_token"] = publisher_token.strip()
        PATH.parent.mkdir(parents=True, exist_ok=True)
        library._write_json(PATH, cur)
    return load()
