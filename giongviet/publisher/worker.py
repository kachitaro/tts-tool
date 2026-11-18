"""Worker nền của laptop: mỗi TICK giây đăng các bài đến hạn, thử lại khi lỗi, đánh dấu bài lỡ, dọn file cũ."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from giongviet.publisher import channels
from giongviet.publisher.store import Store

log = logging.getLogger(__name__)
TICK = float(os.getenv("PUBLISHER_TICK", "30"))
MAX_ATTEMPTS = 3
BACKOFF = (60, 300, 1500)  # giây chờ trước lần thử lại thứ 1, 2, 3
MISSED_AFTER = (
    float(os.getenv("PUBLISHER_MISSED_HOURS", "6")) * 3600
)  # quá hạn từng này → "missed", không đăng
KEEP = (
    float(os.getenv("PUBLISHER_KEEP_DAYS", "2")) * 86400
)  # giữ file sau khi xong, cho phép "thử lại"


def _redact(msg: str, cfg: dict) -> str:
    for v in cfg.values():
        if isinstance(v, str) and v:
            msg = msg.replace(v, "***")  # lỗi mạng có thể chứa URL có token bot
    return msg[:300]


def run_post(store: Store, p: dict, now: float) -> None:
    store.update(p["id"], status="running")
    secrets = channels.load_secrets(store.data)
    media = store.media_path(p)
    results = dict(p["results"])
    for ch in p["channels"]:
        if results.get(ch, {}).get("ok"):
            continue  # kênh này đã đăng ở lần trước: không đăng đôi
        cfg = secrets.get(ch) or {}
        try:
            if p["filename"] and media is None:
                raise channels.ChannelError("File đính kèm đã bị dọn, hãy gửi lại bài.")
            channels.CHANNELS[ch](cfg, p["caption"], media, p["id"])
            results[ch] = {"ok": True}
        except Exception as ex:  # noqa: BLE001  kênh nào lỗi cũng phải ghi lại, không làm chết worker
            log.warning("bài %s kênh %s lỗi: %s", p["id"], ch, type(ex).__name__)
            results[ch] = {"ok": False, "error": _redact(str(ex) or type(ex).__name__, cfg)}
    if all(results[c]["ok"] for c in p["channels"]):
        store.update(p["id"], status="done", results=results, finished=now)
        return
    attempts = p["attempts"] + 1
    if attempts >= MAX_ATTEMPTS:
        store.update(p["id"], status="error", results=results, attempts=attempts, finished=now)
    else:
        store.update(
            p["id"],
            status="pending",
            results=results,
            attempts=attempts,
            next_try=now + BACKOFF[attempts - 1],
        )


def tick(store: Store, now: float) -> None:
    for p in store.list():
        if p["status"] == "pending":
            if now - p["when"] > MISSED_AFTER:
                store.update(p["id"], status="missed", finished=now)
            elif p["when"] <= now and p["next_try"] <= now:
                run_post(store, p, now)
        elif p["finished"] and now - p["finished"] > KEEP:
            store.drop_media(p["id"])


async def loop(store: Store, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(tick, store, time.time())
        except Exception:  # noqa: BLE001
            log.exception("tick lỗi")
        try:
            await asyncio.wait_for(stop.wait(), TICK)
        except TimeoutError:
            pass
