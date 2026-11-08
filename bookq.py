"""Hàng đợi tạo audio sách nói (Phase 6c): bền trên đĩa, một worker nền, dừng/tiếp ở ranh giới đoạn.

Đơn vị:
  chương  → chia thành đoạn ≤ BOOK_SEGMENT_CHARS (2000) ký tự; mỗi đoạn dựng xong được ghi ngay thành
            data/books/<id>/audio/<nnnn>.parts/<kkk>_<hash>.flac (hash = văn bản đoạn + cấu hình giọng/từ điển) nên
            khởi động lại hoặc đổi cài đặt thì chỉ dựng lại phần thiếu / lỗi thời.
  đoạn    → chia tiếp thành mảnh ≤ 500 ký tự (narrate.units) mỗi lần gọi model; giữa hai mảnh worker nhường cho
            "Đọc thử" (ưu tiên cao nhất) và request tương tác chen vào khoá model (engines.base.PriorityLock).
Chương xong: ghép các đoạn → audio/<nnnn>.flac, xoá .parts, chapters/<nnnn>.json: status "done".

Trạng thái bền: data/queue.json  {paused, items:[{book,n,force}], inhibit_sleep, rate:[[chars,giây]…], finish}.
Khởi động lại: chương đang "running" quay về "queued", worker chạy tiếp nếu không ở trạng thái tạm dừng.
Tạm dừng / huỷ chỉ có hiệu lực ở ranh giới đoạn (đoạn đang chạy được dựng xong, không cắt giữa chừng); tắt server
(SIGINT/SIGTERM) chờ nốt mảnh đang chạy rồi dừng, đoạn dở được dựng lại khi khởi động.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field

import anyio
import numpy as np
import soundfile as sf

import books
import dialogue
import lexicon
import library
import narrate
import settings
from engines.base import BACKGROUND
from engines.vieneu import default_precision

log = logging.getLogger(__name__)
STATE_PATH = library.DATA / "queue.json"
BENCH_PATH = library.DATA / "bench.json"
RATE_WINDOW = 20  # số đoạn gần nhất dùng để đo tốc độ thực tế
MAX_CONSECUTIVE_ERRORS = 3
TRIAL_TTL = 900  # giây giữ kết quả "Đọc thử"
INHIBIT_WHY = "Giọng Việt đang tạo sách nói"


class QueueError(ValueError):
    pass


@dataclass
class Trial:
    id: str
    book: str
    n: int
    units: list
    speed: int
    status: str = "queued"  # queued | running | done | error
    done: int = 0
    total: int = 0
    seconds: float = 0.0
    error: str = ""
    wav: bytes = b""
    created: float = field(default_factory=time.time)


def _flac(path, wav: np.ndarray) -> None:
    tmp = path.with_name(path.name + ".tmp")
    sf.write(str(tmp), wav, dialogue.SR, format="FLAC", subtype="PCM_16")
    tmp.replace(path)


def _err_text(ex: Exception) -> str:
    return str(getattr(ex, "detail", None) or ex) or type(ex).__name__


def current_precision() -> str:
    return default_precision()


def bench_rate(engine_id: str) -> tuple[float, str] | None:
    """Tốc độ (ký tự/giây) đo bởi scripts/bench_vieneu.py cho precision đang dùng."""
    if engine_id != "vieneu":
        return None
    try:
        data = json.loads(BENCH_PATH.read_text(encoding="utf-8"))
        r = data["vieneu"][current_precision()]
        return float(r["chars_per_sec"]), f"bench {current_precision()}"
    except OSError, ValueError, KeyError, TypeError:
        return None


def signature(book: dict, narr: tuple, dlg: tuple | None, glex: list[dict]) -> str:
    """Cấu hình ảnh hưởng tới audio (giọng, tốc độ, chuẩn hoá, từ điển, đọc tiêu đề, các mức nghỉ, mode/precision của model — hai thứ
    sau nằm trong line_key qua cache_tag): đổi thì audio cũ lỗi thời."""
    speed = book["speed"]
    pp, tp = books.pauses(book)
    parts = {
        "n": dialogue.line_key(narr[0], narr[1], "", speed),
        "d": dialogue.line_key(dlg[0], dlg[1], "", speed) if dlg else None,
        "norm": bool(book["normalize"]),
        "lex": book.get("lexicon") or [],
        "glex": glex,
        "title": bool(book.get("read_title", True)),
        "pp": pp,
        "tp": tp,
    }
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


class BookQueue:
    def __init__(self) -> None:
        self.s: dict = {
            "paused": False,
            "items": [],
            "inhibit_sleep": True,
            "rate": [],
            "finish": {
                "seq": 0,
                "at": 0,
                "done": 0,
                "errors": 0,
                "book": "",
                "title": "",
                "trial": False,
            },
        }
        self.running: dict | None = None
        self.trials: dict[str, Trial] = {}
        self.resolve = None  # callable(book) -> (narr, dlg); server cung cấp
        self.note = ""  # thông báo cho UI (vd. tạm dừng vì lỗi liên tiếp)
        self.inhibit_state = "off"  # off | on | unavailable | error
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._shutdown = False
        self._cancel_current = False
        self._inhibit: subprocess.Popen | None = None
        self._session = {"done": 0, "errors": 0, "book": "", "title": ""}
        self._consecutive_errors = 0
        self._io = threading.Lock()

    # ───────────── bền trên đĩa ─────────────
    def load(self) -> None:
        try:
            saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self.s.update({k: saved[k] for k in self.s if k in saved})
        except OSError, ValueError:
            pass
        items, seen = [], set()
        for it in self.s["items"]:
            key = (it["book"], int(it["n"]))
            if key in seen:
                continue
            try:
                meta, _ = books.chapter_text(*key)
            except books.NotFound, books.BookError, OSError, ValueError:
                continue
            seen.add(key)
            items.append({"book": key[0], "n": key[1], "force": bool(it.get("force"))})
            if meta.get("status") != "queued":
                books.update_chapter(
                    key[0], key[1], status="queued"
                )  # đang "running" khi server chết → làm lại từ đoạn dở
        self.s["items"] = items
        self.save()

    def save(self) -> None:
        with self._io:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            books._write_json(STATE_PATH, self.s)

    # ───────────── điều khiển ─────────────
    def start(self, resolve) -> None:
        self.resolve = resolve
        self.load()
        self._shutdown = False
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._loop())

    async def stop(self, timeout: float = 120) -> None:
        """Tắt server: chờ nốt mảnh đang chạy (không bắt đầu đoạn mới), trả chương dở về hàng đợi."""
        self._shutdown = True
        if self._wake:
            self._wake.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout)
            except TimeoutError:
                log.warning(
                    "Hàng đợi sách nói chưa dừng sau %ss; chương đang dở sẽ làm lại khi khởi động.",
                    timeout,
                )
        self._stop_inhibit()

    def _poke(self) -> None:
        if self._wake:
            self._wake.set()

    def enqueue(
        self, book_id: str, ns: list[int], regenerate: bool = False, start: bool = True
    ) -> dict:
        """Xếp chương vào cuối hàng đợi. Bỏ qua chương đã xong (trừ regenerate: xoá audio cũ, dựng lại bằng model, không dùng cache),
        chương đang chạy và chương đã nằm trong hàng đợi (regenerate thì đánh dấu dựng lại)."""
        books.get(book_id)
        running_key = (self.running["book"], self.running["n"]) if self.running else None
        by_key = {(i["book"], i["n"]): i for i in self.s["items"]}
        added, skipped = [], []
        for n in dict.fromkeys(ns):
            try:
                meta, _ = books.chapter_text(book_id, n)
            except books.NotFound:
                raise QueueError(f"Không có chương {n}.") from None
            key = (book_id, n)
            if key == running_key:
                skipped.append(n)
            elif key in by_key:
                if regenerate:
                    self._reset_chapter(book_id, n)
                    by_key[key]["force"] = True
                    books.update_chapter(book_id, n, status="queued")
                skipped.append(n)
            elif meta.get("status") in ("done", "exported") and not regenerate:
                skipped.append(n)
            else:
                if regenerate:
                    self._reset_chapter(book_id, n)
                books.update_chapter(
                    book_id, n, status="queued", error=None
                )  # chương lỗi/dở: giữ các đoạn đã dựng để chạy tiếp
                self.s["items"].append({"book": book_id, "n": n, "force": bool(regenerate)})
                added.append(n)
        if start:
            self.s["paused"] = False
            self.note = ""
        self.save()
        self._poke()
        return {"added": added, "skipped": skipped}

    def _reset_chapter(self, book_id: str, n: int) -> None:
        books.chapter_audio(book_id, n).unlink(missing_ok=True)
        shutil.rmtree(books.parts_dir(book_id, n), ignore_errors=True)
        books.update_chapter(
            book_id,
            n,
            status="pending",
            segments=None,
            audio_seconds=None,
            gen_seconds=None,
            sig=None,
            error=None,
            finished_at=None,
            exported=None,
        )

    def pause(self) -> None:
        self.s["paused"] = True
        self.save()

    def resume(self) -> None:
        self.s["paused"] = False
        self.note = ""
        self.save()
        self._poke()

    def cancel(self, book_id: str | None = None) -> int:
        """Bỏ các chương chưa chạy (của một truyện hoặc tất cả); chương đang chạy dừng ở ranh giới đoạn, về 'chưa tạo'."""
        keep, dropped = [], 0
        for it in self.s["items"]:
            if book_id and it["book"] != book_id:
                keep.append(it)
                continue
            if self.running and (it["book"], it["n"]) == (self.running["book"], self.running["n"]):
                self._cancel_current = True
                keep.append(it)  # worker gỡ khi dừng
                continue
            try:
                books.update_chapter(it["book"], it["n"], status="pending")
            except OSError, ValueError:
                pass
            dropped += 1
        self.s["items"] = keep
        self.save()
        return dropped

    def focus(self, book_id: str, n: int) -> bool:
        """Chương đang mở: nếu đang chờ trong hàng đợi thì lên đầu (chạy ngay sau đoạn hiện tại)."""
        items = self.s["items"]
        idx = next((k for k, it in enumerate(items) if (it["book"], it["n"]) == (book_id, n)), None)
        if idx is None:
            return False
        first_is_running = bool(
            self.running
            and items
            and (items[0]["book"], items[0]["n"]) == (self.running["book"], self.running["n"])
        )
        target = 1 if first_is_running else 0
        if idx > target:
            items.insert(target, items.pop(idx))
            self.save()
        return True

    def forget_book(self, book_id: str) -> None:
        self.s["items"] = [
            i
            for i in self.s["items"]
            if i["book"] != book_id or (self.running and self.running["book"] == book_id)
        ]
        if self.running and self.running["book"] == book_id:
            self._cancel_current = True
        for t in list(self.trials.values()):
            if t.book == book_id:
                del self.trials[t.id]
        self.save()

    def set_inhibit(self, enabled: bool) -> None:
        self.s["inhibit_sleep"] = bool(enabled)
        self.save()
        if not enabled:
            self._stop_inhibit()
        elif self.running:
            self._start_inhibit()

    # ───────────── Đọc thử (ưu tiên cao nhất) ─────────────
    def submit_trial(self, book: dict, n: int, text: str, narr: tuple, dlg: tuple | None) -> Trial:
        self._purge_trials()
        us = narrate.units(
            text, narr, dlg, book["normalize"], book.get("lexicon"), lexicon.load_global()
        )
        if not us:
            raise QueueError("Đoạn văn không có gì để đọc.")
        t = Trial(uuid.uuid4().hex[:12], book["id"], n, us, book["speed"], total=len(us))
        self.trials[t.id] = t
        self._poke()
        return t

    def _purge_trials(self) -> None:
        now = time.time()
        for tid, t in list(self.trials.items()):
            if t.status in ("done", "error") and now - t.created > TRIAL_TTL:
                del self.trials[tid]

    async def _serve_trials(self) -> None:
        while any(t.status == "queued" for t in self.trials.values()):
            t = next(t for t in self.trials.values() if t.status == "queued")
            t.status = "running"
            try:
                parts = []
                warnings: list = []
                for u in t.units:
                    parts.append(await narrate.render_unit(u, t.speed, warnings))
                    t.done += 1
                wav = np.concatenate(parts)
                t.wav, _ = await anyio.to_thread.run_sync(dialogue.encode_outputs, wav, False)
                t.seconds, t.status = len(wav) / dialogue.SR, "done"
            except Exception as ex:  # noqa: BLE001 — lỗi engine báo lại cho người dùng
                log.warning("Đọc thử %s lỗi: %s", t.id, ex)
                t.error, t.status = _err_text(ex), "error"

    # ───────────── worker ─────────────
    def _next_item(self) -> dict | None:
        return self.s["items"][0] if self.s["items"] else None

    async def _loop(self) -> None:
        BACKGROUND.set(True)
        while not self._shutdown:
            try:
                await self._serve_trials()
                item = self._next_item()
                if item is None or self.s["paused"]:
                    self._on_idle(drained=item is None)
                    await self._wake.wait()
                    self._wake.clear()
                    continue
                self._start_inhibit()
                await self._process(item)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — worker không được chết vì một lỗi bất ngờ
                log.exception("Hàng đợi sách nói gặp lỗi bất ngờ")
                await asyncio.sleep(2)
        self.running = None

    def _on_idle(self, drained: bool) -> None:
        self._stop_inhibit()
        if drained and (self._session["done"] or self._session["errors"]):
            f = self.s["finish"]
            f.update(
                seq=f["seq"] + 1,
                at=time.time(),
                done=self._session["done"],
                errors=self._session["errors"],
                book=self._session["book"],
                title=self._session["title"],
                trial=self._mark_trial_done(self._session["book"]),
            )
            self.save()
            self._notify(f)
            self._session = {"done": 0, "errors": 0, "book": "", "title": ""}

    @staticmethod
    def _mark_trial_done(book_id: str) -> bool:
        """ "Tạo thử N chương" xong khi đủ N chương đã có audio: ghi done_at vào book.json (banner "Tạo tiếp" đọc từ đó)."""
        try:
            b = books.get(book_id)
            t = b.get("trial")
            if not t or t.get("done_at"):
                return False
            if (
                sum(c.get("status") in ("done", "exported") for c in books.list_chapters(book_id))
                < t["limit"]
            ):
                return False
            t["done_at"] = time.time()
            books.save(b)
            return True
        except books.NotFound, OSError, KeyError:
            return False

    def _notify(self, f: dict) -> None:
        import shutil as _sh

        if not _sh.which("notify-send") or not settings.load()["notify"]:
            return
        trial = f.get("trial")
        body = (
            f"{f['title'] or 'Sách nói'}: xong {f['done']} chương"
            + (f", {f['errors']} lỗi" if f["errors"] else "")
            + (". Nghe thử rồi bấm Tạo tiếp." if trial else "")
        )
        try:
            subprocess.Popen(
                [
                    "notify-send",
                    "-a",
                    "Giọng Việt",
                    "Giọng Việt — đã xong chương thử"
                    if trial
                    else "Giọng Việt — tạo sách nói xong",
                    body,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as ex:
            log.info("notify-send lỗi: %s", ex)

    def _interrupted(self) -> str:
        """'' nếu tiếp tục; còn lại là lý do dừng ở ranh giới đoạn: shutdown | pause | cancel."""
        if self._shutdown:
            return "shutdown"
        if self._cancel_current:
            return "cancel"
        if self.s["paused"]:
            return "pause"
        return ""

    def _pop(self, item: dict) -> None:
        self.s["items"] = [
            i for i in self.s["items"] if not (i["book"] == item["book"] and i["n"] == item["n"])
        ]
        self.save()

    async def _process(self, item: dict) -> None:
        book_id, n = item["book"], item["n"]
        self._cancel_current = False
        try:
            book = books.get(book_id)
            meta, body = books.chapter_text(book_id, n)
        except books.NotFound, books.BookError, OSError, ValueError:
            self._pop(item)
            return
        self.running = {
            "book": book_id,
            "n": n,
            "title": meta.get("title", ""),
            "seg_done": 0,
            "seg_total": 0,
            "book_title": book["title"],
        }
        try:
            outcome = await self._generate(book, meta, body, item)
        except Exception as ex:  # noqa: BLE001
            log.warning(
                "Chương %s/%s lỗi: %s",
                book_id,
                n,
                ex,
                exc_info=not isinstance(ex, (RuntimeError, ValueError, OSError)),
            )
            books.update_chapter(book_id, n, status="error", error=_err_text(ex)[:500])
            self._pop(item)
            self._session["errors"] += 1
            self._consecutive_errors += 1
            if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS and not self.s["paused"]:
                self.s["paused"] = True
                self.note = f"Đã tạm dừng vì {MAX_CONSECUTIVE_ERRORS} chương lỗi liên tiếp. Lỗi cuối: {_err_text(ex)[:200]}"
                self.save()
            outcome = "error"
        finally:
            running, self.running = self.running, None
        if outcome == "done":
            self._consecutive_errors = 0
            self._session.update(book=book_id, title=running["book_title"])
            self._session["done"] += 1
        elif outcome == "cancel":
            books.update_chapter(book_id, n, status="pending")
            self._pop(item)
        elif outcome in ("pause", "shutdown"):
            books.update_chapter(book_id, n, status="queued")
        self._cancel_current = False

    async def _generate(self, book: dict, meta: dict, body: str, item: dict) -> str:
        book_id, n = book["id"], meta["n"]
        narr, dlg = self.resolve(book)
        glex = lexicon.load_global()
        sig = signature(book, narr, dlg, glex)
        segs = narrate.split_segments(books.paragraphs(book, meta, body), books.SEGMENT_CHARS)
        if not segs:
            raise ValueError("Chương không có chữ để đọc.")
        texts = [narrate.segment_text(segs, k) for k in range(len(segs))]
        pdir = books.parts_dir(book_id, n)
        pdir.mkdir(parents=True, exist_ok=True)
        names = [
            f"{k:03d}_{hashlib.sha256((t + sig).encode()).hexdigest()[:10]}.flac"
            for k, t in enumerate(texts)
        ]
        for f in pdir.iterdir():  # đoạn của cấu hình cũ / file tạm dở dang
            if f.name not in names:
                f.unlink(missing_ok=True)
        books.update_chapter(
            book_id,
            n,
            status="running",
            segments={"done": 0, "total": len(segs)},
            error=None,
            sig=sig,
        )
        self.running.update(seg_total=len(segs))
        gen_seconds = 0.0
        for k, (seg, name) in enumerate(
            zip(texts, names, strict=True)
        ):  # names sinh 1-1 từ texts nên luôn bằng nhau
            path = pdir / name
            if not path.is_file():
                if why := self._interrupted():
                    return why
                t0 = time.perf_counter()
                wav = await self._render_segment(
                    seg, book, narr, dlg, glex, bool(item.get("force"))
                )
                if wav is None:
                    return "shutdown"
                await anyio.to_thread.run_sync(_flac, path, wav)
                took = time.perf_counter() - t0
                gen_seconds += took
                self._record_rate(len(seg), took)
            self.running.update(seg_done=k + 1)
            books.update_chapter(book_id, n, segments={"done": k + 1, "total": len(segs)})
        audio = await anyio.to_thread.run_sync(
            self._assemble, book_id, n, [pdir / nm for nm in names]
        )
        books.update_chapter(
            book_id,
            n,
            status="done",
            audio_seconds=round(audio, 1),
            gen_seconds=round(gen_seconds, 1),
            finished_at=time.time(),
            error=None,
        )
        self._pop(item)
        return "done"

    async def _render_segment(
        self, seg: str, book: dict, narr: tuple, dlg: tuple | None, glex: list[dict], force: bool
    ) -> np.ndarray | None:
        """None nếu server đang tắt (bỏ nốt đoạn dở, sẽ dựng lại khi khởi động)."""
        us = narrate.units(seg, narr, dlg, book["normalize"], book.get("lexicon"), glex)
        parts, warnings = [], []
        for u in us:
            parts.append(await narrate.render_unit(u, book["speed"], warnings, force))
            await self._serve_trials()  # "Đọc thử" chen vào giữa hai mảnh
            if self._shutdown:
                return None
        return (
            np.concatenate(parts) if parts else np.zeros(int(0.4 * dialogue.SR), dtype=np.float32)
        )

    @staticmethod
    def _assemble(book_id: str, n: int, files: list) -> float:
        wav = np.concatenate([sf.read(str(f), dtype="float32")[0] for f in files])
        books.audio_dir(book_id).mkdir(parents=True, exist_ok=True)
        _flac(books.chapter_audio(book_id, n), wav)
        shutil.rmtree(books.parts_dir(book_id, n), ignore_errors=True)
        return len(wav) / dialogue.SR

    def _record_rate(self, chars: int, seconds: float) -> None:
        rate = self.s["rate"]
        rate.append([chars, round(seconds, 2)])
        del rate[:-RATE_WINDOW]
        self.save()

    # ───────────── chống ngủ máy ─────────────
    def _start_inhibit(self) -> None:
        if not self.s["inhibit_sleep"] or (self._inhibit and self._inhibit.poll() is None):
            return
        if not shutil.which("systemd-inhibit"):
            self.inhibit_state = "unavailable"
            log.info("Không có systemd-inhibit: bỏ qua chống ngủ máy.")
            return
        # tiến trình con tự thoát khi server chết (kể cả bị kill -9) nên khoá không bị kẹt
        cmd = [
            "systemd-inhibit",
            "--what=sleep:idle",
            "--who=Giọng Việt",
            f"--why={INHIBIT_WHY}",
            "--mode=block",
            "sh",
            "-c",
            f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 5; done",
        ]
        try:
            self._inhibit = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True
            )
            self.inhibit_state = "on"
        except OSError as ex:
            log.warning("systemd-inhibit không chạy được (%s): bỏ qua chống ngủ máy.", ex)
            self._inhibit, self.inhibit_state = None, "error"

    def _check_inhibit(self) -> None:
        """systemd-inhibit thoát ngay (vd. không có quyền với logind) thì ghi log một lần và báo 'error'."""
        if self._inhibit and self._inhibit.poll() is not None:
            err = (self._inhibit.stderr.read() or b"").decode(errors="replace").strip()
            log.warning(
                "systemd-inhibit thoát sớm (mã %s): %s — bỏ qua chống ngủ máy.",
                self._inhibit.returncode,
                err,
            )
            self._inhibit, self.inhibit_state = None, "error"

    def _stop_inhibit(self) -> None:
        if self._inhibit and self._inhibit.poll() is None:
            try:
                os.killpg(self._inhibit.pid, signal.SIGTERM)
                self._inhibit.wait(timeout=3)
            except OSError, subprocess.TimeoutExpired:
                pass
        self._inhibit = None
        if self.inhibit_state == "on":
            self.inhibit_state = "off"

    # ───────────── trạng thái ─────────────
    def rate(self, engine_id: str = "vieneu") -> tuple[float, str] | None:
        """(ký tự/giây, nguồn): đo thực tế từ các đoạn gần nhất, không có thì lấy số bench."""
        r = self.s["rate"]
        chars, secs = sum(c for c, _ in r), sum(s for _, s in r)
        if secs > 0 and len(r) >= 1:
            return chars / secs, "đo thực tế"
        return bench_rate(engine_id)

    def status(self) -> dict:
        running = dict(self.running) if self.running else None
        self._check_inhibit()
        state = (
            ("pausing" if self.s["paused"] else "running")
            if running
            else "paused"
            if self.s["paused"]
            else "running"
            if self.s["items"]
            else "idle"
        )
        return {
            "state": state,
            "paused": self.s["paused"],
            "running": running,
            "queued": len(self.s["items"]),
            "inhibit_sleep": self.s["inhibit_sleep"],
            "inhibit": self.inhibit_state,
            "note": self.note,
            "finish": self.s["finish"],
            "precision": current_precision(),
        }

    def book_status(self, book_id: str, engine_id: str = "vieneu") -> dict:
        chs = books.list_chapters(book_id)
        counts: dict[str, int] = {}
        remaining_chars = remaining_n = 0
        for c in chs:
            st = c.get("status", "pending")
            counts[st] = counts.get(st, 0) + 1
            if st not in ("done", "exported"):
                frac = 1.0
                seg = c.get("segments")
                if st == "running" and seg and seg.get("total"):
                    frac = 1 - seg["done"] / seg["total"]
                remaining_chars += c["chars"] * frac
                remaining_n += 1
        r = self.rate(engine_id)
        est = remaining_chars / r[0] if r and r[0] > 0 else None
        out = self.status()
        out.update(
            counts=counts,
            chapters=len(chs),
            remaining=remaining_n,
            remaining_chars=round(remaining_chars),
            estimate_seconds=None if est is None else round(est),
            rate_cps=None if r is None else round(r[0], 2),
            rate_source=None if r is None else r[1],
            queued_book=sum(1 for i in self.s["items"] if i["book"] == book_id),
        )
        return out


Q = BookQueue()
