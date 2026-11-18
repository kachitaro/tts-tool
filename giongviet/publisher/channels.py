"""Kênh đăng bài. Thêm kênh = thêm một hàm (cfg, text, media, key) vào CHANNELS và các khoá bắt buộc vào REQUIRED.

Bí mật nằm trong <PUBLISHER_DATA>/secrets.json (bạn tự tạo, nhớ chmod 600), ví dụ:
  {"telegram": {"token": "123:ABC", "chat_id": "-1001234"},
   "discord":  {"webhook": "https://discord.com/api/webhooks/..."},
   "mastodon": {"instance": "https://mastodon.social", "token": "...", "visibility": "unlisted"}}
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import httpx

SECRETS_FILE = "secrets.json"
UPLOAD_TIMEOUT = 600  # giây; mạng nhà đẩy file hàng chục MB có thể chậm
REQUIRED = {
    "telegram": ("token", "chat_id"),
    "discord": ("webhook",),
    "mastodon": ("instance", "token"),
}


class ChannelError(RuntimeError):
    pass


def load_secrets(data: Path) -> dict:
    try:
        raw = json.loads((data / SECRETS_FILE).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def configured(secrets: dict, ch: str) -> bool:
    cfg = secrets.get(ch)
    return isinstance(cfg, dict) and all(
        isinstance(cfg.get(k), str) and cfg[k] for k in REQUIRED[ch]
    )


def _check(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        raise ChannelError(f"{what}: HTTP {r.status_code} {r.text[:200]}")


def telegram(cfg: dict, text: str, media: Path | None, key: str) -> None:
    base = f"https://api.telegram.org/bot{cfg['token']}"
    if media is None:
        r = httpx.post(
            f"{base}/sendMessage", data={"chat_id": cfg["chat_id"], "text": text[:4096]}, timeout=60
        )
    else:
        method, field = (
            ("sendAudio", "audio")
            if media.suffix.lower() in (".mp3", ".m4a")
            else ("sendDocument", "document")
        )
        with media.open("rb") as f:
            r = httpx.post(
                f"{base}/{method}",
                data={
                    "chat_id": cfg["chat_id"],
                    "caption": text[:1024],
                },  # Telegram cắt chú thích ở 1024
                files={field: (media.name, f)},
                timeout=UPLOAD_TIMEOUT,
            )
    _check(r, "Telegram")


def discord(cfg: dict, text: str, media: Path | None, key: str) -> None:
    payload = {"content": text[:2000]}
    if media is None:
        r = httpx.post(cfg["webhook"], json=payload, timeout=60)
    else:
        with media.open("rb") as f:
            r = httpx.post(
                cfg["webhook"],
                data={"payload_json": json.dumps(payload)},
                files={"files[0]": (media.name, f)},
                timeout=UPLOAD_TIMEOUT,
            )
    _check(r, "Discord")


def mastodon(cfg: dict, text: str, media: Path | None, key: str) -> None:
    base = cfg["instance"].rstrip("/")
    h = {"Authorization": f"Bearer {cfg['token']}"}
    ids: list[str] = []
    if media is not None:
        with media.open("rb") as f:
            r = httpx.post(
                f"{base}/api/v2/media",
                headers=h,
                files={"file": (media.name, f)},
                timeout=UPLOAD_TIMEOUT,
            )
        _check(r, "Mastodon (tải file)")
        mid = r.json()["id"]
        if r.status_code == 202:  # audio/video được xử lý nền: chờ tới khi 200
            for _ in range(30):
                time.sleep(2)
                g = httpx.get(f"{base}/api/v1/media/{mid}", headers=h, timeout=30)
                _check(g, "Mastodon (chờ xử lý file)")
                if g.status_code == 200:
                    break
            else:
                raise ChannelError("Mastodon: file xử lý quá 60 giây")
        ids = [mid]
    r = httpx.post(
        f"{base}/api/v1/statuses",
        headers={**h, "Idempotency-Key": key},
        json={"status": text, "media_ids": ids, "visibility": cfg.get("visibility", "public")},
        timeout=60,
    )
    _check(r, "Mastodon")


CHANNELS: dict[str, Callable[[dict, str, Path | None, str], None]] = {
    "telegram": telegram,
    "discord": discord,
    "mastodon": mastodon,
}
