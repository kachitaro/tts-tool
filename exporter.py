"""Xuất sách nói: MP3 từng chương (ffmpeg, mono 64–96 kbps, ID3), zip các MP3, và .m4b một file có chương.

Nguồn là audio/<nnnn>.flac do hàng đợi dựng (lossless) nên MP3/AAC chỉ nén một lần. Chỉ xuất chương đã "done".
Việc xuất chạy nền (asyncio + thread), có tiến độ để UI hỏi theo kiểu polling.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import soundfile as sf

import books

KBPS = (64, 80, 96)
M4B_KBPS = 64
JOB_TTL = 3600


class ExportError(ValueError):
    pass


def export_dir(book_id: str) -> Path:
    return books._dir(book_id) / "export"


def safe_name(text: str, fallback: str = "sach") -> str:
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", text).strip(" .")
    return re.sub(r"\s+", " ", text)[:80] or fallback


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise ExportError("Máy chưa cài ffmpeg (sudo apt install ffmpeg).")
    return exe


def _done_chapters(book_id: str, ns: list[int] | None) -> list[dict]:
    chs = [c for c in books.list_chapters(book_id) if c.get("status") == "done" and books.chapter_audio(book_id, c["n"]).is_file()]
    if ns is not None:
        want = set(ns)
        chs = [c for c in chs if c["n"] in want]
    if not chs:
        raise ExportError("Chưa có chương nào đã dựng xong để xuất.")
    return chs


def chapter_mp3(book: dict, meta: dict, kbps: int, total: int) -> Path:
    """MP3 của một chương (cache trong export/mp3/, dựng lại khi FLAC mới hơn)."""
    if kbps not in KBPS:
        raise ExportError(f"kbps phải là một trong {KBPS}.")
    src = books.chapter_audio(book["id"], meta["n"])
    out = export_dir(book["id"]) / "mp3" / f"{meta['n']:04d}_{kbps}.mp3"
    if out.is_file() and out.stat().st_mtime >= src.stat().st_mtime:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.mp3")
    title = f"{meta['n']}. {meta['title']}" if meta.get("title") else f"Chương {meta['n']}"
    cmd = [_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-codec:a", "libmp3lame", "-b:a", f"{kbps}k",
           "-id3v2_version", "3", "-metadata", f"title={title}", "-metadata", f"track={meta['n']}/{total}",
           "-metadata", f"album={book['title']}", "-metadata", f"artist={book.get('author') or ''}", "-metadata", "genre=Audiobook", str(tmp)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise ExportError(f"ffmpeg lỗi ở chương {meta['n']}: {r.stderr.decode(errors='replace')[-300:]}")
    tmp.replace(out)
    return out


@dataclass
class ExportJob:
    id: str
    book: str
    kind: str                 # mp3zip | m4b
    status: str = "running"   # running | done | error
    done: int = 0
    total: int = 0
    chapters: int = 0
    file: str = ""
    size: int = 0
    error: str = ""
    created: float = field(default_factory=time.time)


JOBS: dict[str, ExportJob] = {}


def _purge() -> None:
    now = time.time()
    for jid, j in list(JOBS.items()):
        if j.status != "running" and now - j.created > JOB_TTL:
            del JOBS[jid]


def _build_zip(book: dict, chs: list[dict], kbps: int, job: ExportJob) -> Path:
    out = export_dir(book["id"]) / f"{safe_name(book['title'])} (mp3 {kbps}k).zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    total = len(books.list_chapters(book["id"]))
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:  # MP3 đã nén, không nén thêm
        for c in chs:
            mp3 = chapter_mp3(book, c, kbps, total)
            z.write(mp3, f"{c['n']:04d} - {safe_name(c.get('title') or 'Chương ' + str(c['n']))}.mp3")
            job.done += 1
    tmp.replace(out)
    return out


def _build_m4b(book: dict, chs: list[dict], job: ExportJob) -> Path:
    out = export_dir(book["id"]) / f"{safe_name(book['title'])}.m4b"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp.m4b")
    with tempfile.TemporaryDirectory() as td:
        listing, meta = [], [";FFMETADATA1", f"title={book['title']}", f"artist={book.get('author') or ''}", f"album={book['title']}", "genre=Audiobook"]
        pos = 0
        for c in chs:
            src = books.chapter_audio(book["id"], c["n"])
            dur_ms = round(sf.info(str(src)).duration * 1000)
            listing.append("file '" + str(src).replace("'", "'\\''") + "'")
            title = c.get("title") or f"Chương {c['n']}"
            meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={pos}", f"END={pos + dur_ms}", f"title={c['n']}. {title}"]
            pos += dur_ms
        job.total = max(pos, 1)  # tiến độ tính theo mili-giây audio đã mã hoá
        (Path(td) / "list.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
        (Path(td) / "meta.txt").write_text("\n".join(meta) + "\n", encoding="utf-8")
        cmd = [_ffmpeg(), "-v", "error", "-y", "-nostats", "-progress", "pipe:1", "-f", "concat", "-safe", "0", "-i", str(Path(td) / "list.txt"),
               "-i", str(Path(td) / "meta.txt"), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1", "-c:a", "aac",
               "-b:a", f"{M4B_KBPS}k", "-ac", "1", "-movflags", "+faststart", "-f", "mp4", str(tmp)]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in p.stdout:
            if line.startswith("out_time_us="):
                try:
                    job.done = min(job.total, int(line.split("=")[1]) // 1000)
                except ValueError:
                    pass
        err = p.stderr.read()
        if p.wait() != 0:
            tmp.unlink(missing_ok=True)
            raise ExportError(f"ffmpeg lỗi khi tạo m4b: {err[-300:]}")
    tmp.replace(out)
    return out


def start(book: dict, kind: str, ns: list[int] | None = None, kbps: int = 64) -> ExportJob:
    if kind not in ("mp3zip", "m4b"):
        raise ExportError("kind phải là 'mp3zip' hoặc 'm4b'.")
    if kind == "mp3zip" and kbps not in KBPS:
        raise ExportError(f"kbps phải là một trong {KBPS}.")
    _ffmpeg()
    chs = _done_chapters(book["id"], ns)
    _purge()
    job = ExportJob(uuid.uuid4().hex[:12], book["id"], kind, total=len(chs), chapters=len(chs))

    async def run() -> None:
        try:
            build = (lambda: _build_zip(book, chs, kbps, job)) if kind == "mp3zip" else (lambda: _build_m4b(book, chs, job))
            path = await anyio.to_thread.run_sync(build)
            for c in chs:  # để nút "Xoá nguồn FLAC của chương đã xuất" biết chương nào đã có bản xuất
                books.update_chapter(book["id"], c["n"], exported=sorted(set(c.get("exported") or []) | {kind}))
            job.file, job.size, job.status = path.name, path.stat().st_size, "done"
        except Exception as ex:  # noqa: BLE001
            job.error, job.status = str(ex) or type(ex).__name__, "error"

    JOBS[job.id] = job
    asyncio.create_task(run())
    return job


def list_files(book_id: str) -> list[dict]:
    d = export_dir(book_id)
    if not d.is_dir():
        return []
    return [{"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime}
            for f in sorted(d.iterdir(), key=lambda p: -p.stat().st_mtime) if f.is_file() and f.suffix in (".zip", ".m4b")]


def file_path(book_id: str, name: str) -> Path:
    p = export_dir(book_id) / name
    if "/" in name or "\\" in name or p.parent != export_dir(book_id) or not p.is_file():
        raise ExportError("Không có file này.")
    return p
