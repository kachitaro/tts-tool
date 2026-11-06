"""Hội thoại nhiều người: tách kịch bản "[Tên]: lời", sinh audio từng dòng (có cache), ghép WAV 48 kHz mono.

Tiến độ qua polling: server giữ Job trong bộ nhớ (dọn sau JOB_TTL), UI hỏi GET /api/dialogue/{id}.
Cache từng dòng:  data/cache/<hash>.wav   (đã decode, resample 48 kHz, cắt lặng, chuẩn hoá âm lượng)
Đầu ra của job:   data/cache/jobs/<job_id>/out.wav (+ out.mp3 nếu có ffmpeg)
Project:          data/projects/<id>.json
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import anyio
import numpy as np

import history
import library
import text_normalize
from engines.registry import ENGINES

SR = 48000
LINE_RE = re.compile(r"^\s*\[([^\]]+)\]\s*:\s*(.*)$")
MAX_LINES = 300
JOB_TTL = 3600           # giây; job xong quá 1 giờ thì bị dọn
EDGE_PARALLEL = 4        # engine không "local" chạy tối đa 4 dòng cùng lúc; engine local chạy tuần tự
CACHE_MAX_BYTES = int(float(os.getenv("TTS_CACHE_MB", "1024")) * 1024 * 1024)
TARGET_RMS = 0.12        # RMS của phần có tiếng; đưa mọi dòng về cùng mức để edge và VieNeu không chênh âm lượng
MAX_PEAK = 0.95
CACHE = library.DATA / "cache"
PROJECTS = library.DATA / "projects"


class ScriptError(ValueError):
    pass


class Busy(RuntimeError):
    pass


# ───────────────────────────── kịch bản ─────────────────────────────

def norm_name(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip())


@dataclass
class Line:
    i: int
    speaker: str
    text: str
    pause: str  # "" (dòng đầu) | "line" | "paragraph" (có dòng trống ngay trước)


def parse_script(script: str, max_chars: int) -> list[Line]:
    if len(script) > max_chars:
        raise ScriptError(f"Kịch bản quá dài (tối đa {max_chars} ký tự).")
    lines: list[Line] = []
    speaker: str | None = None
    blank = False
    for n, raw in enumerate(script.splitlines(), 1):
        if not raw.strip():
            blank = blank or bool(lines)
            continue
        m = LINE_RE.match(raw)
        if m:
            speaker, text = norm_name(m.group(1)), m.group(2).strip()
            if not speaker:
                raise ScriptError(f"Dòng {n}: tên người nói trống.")
        elif speaker is None:
            raise ScriptError(f"Dòng {n} chưa có người nói. Hãy bắt đầu bằng [Tên]: lời thoại.")
        else:
            text = raw.strip()
        if not text:  # "[Tên]:" không có lời: chỉ đổi người nói cho các dòng sau
            continue
        lines.append(Line(len(lines), speaker, text, "" if not lines else "paragraph" if blank else "line"))
        blank = False
        if len(lines) > MAX_LINES:
            raise ScriptError(f"Kịch bản quá dài (tối đa {MAX_LINES} dòng).")
    return lines


def speakers_of(lines: list[Line]) -> list[str]:
    return list(dict.fromkeys(l.speaker for l in lines))


# ───────────────────────────── audio từng dòng ─────────────────────────────

def prepare_text(engine, text: str, normalize: bool = True) -> str:
    """Bỏ thẻ cảm xúc mà engine này không hỗ trợ (engine khác thì đọc to cả chữ trong ngoặc);
    rồi chuẩn hoá văn bản nếu engine cần (VieNeu; edge được Microsoft tự chuẩn hoá)."""
    caps = engine.capabilities()
    for tag in {t for e in ENGINES.values() for t in e.capabilities()["emotion_tags"]} - set(caps["emotion_tags"]):
        text = text.replace(tag, " ")
    if normalize and caps.get("normalize"):
        text = text_normalize.normalize(text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,!?;:…])", r"\1", text)  # "Chào em [cười]." → "Chào em ." gây lỗi no-audio ở edge


def line_key(engine, voice: str, text: str, speed: int) -> str:
    """Đổi một trong engine / giọng / lời / tốc độ / mode / (variant, alpha của giọng mix) là không dùng cache cũ.
    created_at của giọng thư viện để giọng bị xoá rồi tạo lại cùng tên không dính cache cũ."""
    parts: dict = {"engine": engine.id, "voice": voice, "text": text, "speed": speed, "mode": engine.cache_tag()}
    if voice.startswith(library.LIB_PREFIX):
        try:
            meta = library.get(voice[len(library.LIB_PREFIX):])
        except library.NotFound:
            meta = {}
        parts["created_at"] = meta.get("created_at")
        if meta.get("source") == "mix":
            parts["variant"], parts["alpha"] = meta.get("variant"), meta.get("alpha")
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def to_line_audio(data: bytes) -> np.ndarray:
    """Audio bất kỳ (mp3/wav…) → float32 mono 48 kHz, cắt lặng hai đầu, chuẩn hoá âm lượng."""
    import librosa
    import soxr

    wav, sr = library.decode_audio(data)
    if wav.size == 0:
        raise ValueError("Engine trả về audio rỗng.")
    if sr != SR:
        wav = soxr.resample(wav, sr, SR, quality="HQ")
    wav = np.ascontiguousarray(wav, dtype=np.float32)
    peak = float(np.abs(wav).max())
    if peak < 1e-4:
        raise ValueError("Audio gần như im lặng.")
    _, (a, b) = librosa.effects.trim(wav, top_db=40)
    pad = int(0.03 * SR)  # giữ một chút lặng để khoảng nghỉ do gap_ms quyết định, không do engine
    wav = wav[max(a - pad, 0): min(b + pad, len(wav))]
    peak = float(np.abs(wav).max())
    active = wav[np.abs(wav) > 0.02 * peak]
    rms = float(np.sqrt(np.mean(active**2)))
    wav = wav * float(np.clip(TARGET_RMS / rms, 0.25, 4.0))
    peak = float(np.abs(wav).max())
    return wav * (MAX_PEAK / peak) if peak > MAX_PEAK else wav


def _write_wav(path: Path, wav: np.ndarray) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    sf.write(str(tmp), wav, SR, format="WAV", subtype="PCM_16")
    tmp.replace(path)


def export_mp3(wav_path: Path, mp3_path: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-q:a", "2",
                        str(mp3_path)], capture_output=True)
    return r.returncode == 0


# ───────────────────────────── job ─────────────────────────────

@dataclass
class LineState:
    status: str = "pending"  # pending | running | done | error
    seconds: float = 0.0
    seed: int | None = None
    cached: bool = False
    error: str = ""


@dataclass
class Job:
    id: str
    lines: list[Line]
    cast: dict  # tên → (engine, voice)
    speed: int
    gap_ms: int
    paragraph_gap_ms: int
    states: list[LineState] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    status: str = "running"  # running | done | error
    error: str = ""
    done: int = 0
    updated: float = field(default_factory=time.time)
    has_mp3: bool = False
    normalize: bool = True
    meta: dict = field(default_factory=dict)  # nội dung lưu vào lịch sử khi xong
    history_id: str = ""
    task: asyncio.Task | None = None

    @property
    def dir(self) -> Path:
        return CACHE / "jobs" / self.id

    def touch(self) -> None:
        self.updated = time.time()


JOBS: dict[str, Job] = {}
_sems: dict[str, asyncio.Semaphore] = {}


def purge() -> None:
    """Dọn job đã xong quá JOB_TTL (xoá cả thư mục kết quả)."""
    now = time.time()
    for jid, job in list(JOBS.items()):
        if job.status != "running" and now - job.updated > JOB_TTL:
            shutil.rmtree(job.dir, ignore_errors=True)
            del JOBS[jid]


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def prune_cache(limit: int | None = None) -> int:
    """Giữ data/cache/ ≤ TTS_CACHE_MB: xoá file dòng ít dùng nhất trước (mtime; cache hit có touch).
    Không xoá dòng của job còn trong bộ nhớ vì sinh lại một dòng cần ghép lại từ các file đó.
    Trả về số byte đã giải phóng."""
    limit = CACHE_MAX_BYTES if limit is None else limit
    if not CACHE.is_dir():
        return 0
    total = _dir_size(CACHE)
    protected = {f"{k}.wav" for job in JOBS.values() for k in job.keys if k}
    freed = 0
    for f in sorted((p for p in CACHE.glob("*.wav") if p.name not in protected), key=lambda p: p.stat().st_mtime):
        if total - freed <= limit:
            break
        size = f.stat().st_size
        f.unlink(missing_ok=True)
        freed += size
    return freed


def get_job(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def create_job(lines: list[Line], cast: dict, speed: int, gap_ms: int, paragraph_gap_ms: int,
               normalize: bool = True, meta: dict | None = None) -> Job:
    purge()
    job = Job(uuid.uuid4().hex[:12], lines, cast, speed, gap_ms, paragraph_gap_ms, normalize=normalize, meta=meta or {})
    job.states = [LineState() for _ in lines]
    job.keys = [""] * len(lines)
    JOBS[job.id] = job
    job.task = asyncio.create_task(_run(job))
    return job


def line_path(job: Job, i: int) -> Path:
    return CACHE / f"{job.keys[i]}.wav"


async def _do_line(job: Job, i: int, force: bool = False, seed: int | None = None) -> None:
    line, st = job.lines[i], job.states[i]
    try:
        engine, voice = job.cast[line.speaker]
        text = prepare_text(engine, line.text, job.normalize)
        job.keys[i] = line_key(engine, voice, text, job.speed)
        path = line_path(job, i)
        st.seed = seed
        if path.is_file() and not force:
            st.cached = True
            path.touch()  # LRU: lần dùng gần nhất
        else:
            st.status, st.cached = "running", False
            if not text:  # dòng chỉ có thẻ cảm xúc mà engine không hỗ trợ → nghỉ ngắn
                wav = np.zeros(int(0.4 * SR), dtype=np.float32)
            else:
                sem = _sems.setdefault(engine.id, asyncio.Semaphore(1 if engine.local else EDGE_PARALLEL))
                async with sem:
                    data, _ = await engine.synthesize(text, voice, job.speed, seed=seed, warnings=[])
                wav = await anyio.to_thread.run_sync(to_line_audio, data)
            await anyio.to_thread.run_sync(_write_wav, path, wav)
        st.seconds = round(path.stat().st_size / (2 * SR), 2)
        st.status = "done"
    except Exception as ex:
        st.status, st.error = "error", f"{type(ex).__name__}: {ex}" if not str(ex) else str(ex)
    finally:
        job.done += 1
        job.touch()


def _assemble(job: Job) -> None:
    import soundfile as sf

    parts: list[np.ndarray] = []
    for i, line in enumerate(job.lines):
        if i:
            gap = job.paragraph_gap_ms if line.pause == "paragraph" else job.gap_ms
            parts.append(np.zeros(int(SR * gap / 1000), dtype=np.float32))
        wav, _ = sf.read(str(line_path(job, i)), dtype="float32")
        parts.append(wav)
    out = job.dir / "out.wav"
    _write_wav(out, np.concatenate(parts))
    job.has_mp3 = export_mp3(out, job.dir / "out.mp3")


def _save_history(job: Job) -> None:
    """Lưu (hoặc cập nhật sau khi sinh lại dòng) bản hội thoại vào lịch sử; ưu tiên MP3 cho nhẹ."""
    ext = "mp3" if job.has_mp3 else "wav"
    audio = (job.dir / f"out.{ext}").read_bytes()
    if job.history_id:
        try:
            return history.replace_audio(job.history_id, audio, ext)
        except KeyError:  # bản đã bị xoá khỏi lịch sử
            pass
    seconds = round(sum(s.seconds for s in job.states), 1)
    job.history_id = history.save("dialogue", {**job.meta, "seconds": seconds, "lines": len(job.lines)}, audio, ext)


async def _finish(job: Job) -> None:
    errors = [f"Dòng {i + 1} ({job.lines[i].speaker}): {s.error}" for i, s in enumerate(job.states) if s.status == "error"]
    if errors:
        job.status, job.error = "error", "; ".join(errors)
    else:
        try:
            await anyio.to_thread.run_sync(_assemble, job)
            await anyio.to_thread.run_sync(_save_history, job)
            job.status, job.error = "done", ""
        except Exception as ex:
            job.status, job.error = "error", f"Không ghép được audio: {ex}"
    await anyio.to_thread.run_sync(prune_cache)
    job.touch()


async def _run(job: Job) -> None:
    await asyncio.gather(*(_do_line(job, i) for i in range(len(job.lines))))
    await _finish(job)


async def regen_line(job: Job, i: int, seed: int | None) -> None:
    """Sinh lại một dòng (bỏ qua cache, seed mới) rồi ghép lại file tổng. Take mới thay take cũ trong cache."""
    if job.status == "running":
        raise Busy("Job đang chạy.")
    if not 0 <= i < len(job.lines):
        raise IndexError(i)
    job.status, job.done = "running", len(job.lines) - 1
    job.states[i] = LineState()
    await _do_line(job, i, force=True, seed=seed if seed is not None else secrets.randbelow(2**31))
    await _finish(job)


def job_info(job: Job) -> dict:
    return {
        "id": job.id, "status": job.status, "done": job.done, "total": len(job.lines), "error": job.error,
        "audio": {"wav": job.status == "done", "mp3": job.status == "done" and job.has_mp3},
        "lines": [
            {"i": l.i, "speaker": l.speaker, "text": l.text, "pause": l.pause, "status": s.status,
             "seconds": s.seconds, "seed": s.seed, "cached": s.cached, "error": s.error}
            for l, s in zip(job.lines, job.states)
        ],
    }


# ───────────────────────────── project ─────────────────────────────

class ProjectError(ValueError):
    pass


def _project_path(project_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", project_id):
        raise KeyError(project_id)
    return PROJECTS / f"{project_id}.json"


def save_project(data: dict) -> dict:
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 80:
        raise ProjectError("Tên dự án phải từ 1 đến 80 ký tự.")
    project = {
        "name": name, "script": str(data.get("script", "")), "cast": data.get("cast") or {},
        "speed": int(data.get("speed", 0)), "gap_ms": int(data.get("gap_ms", 350)),
        "paragraph_gap_ms": int(data.get("paragraph_gap_ms", 800)), "normalize": bool(data.get("normalize", True)),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    pid = library.slugify(name)
    PROJECTS.mkdir(parents=True, exist_ok=True)
    library._write_json(_project_path(pid), project)
    return {"id": pid, **project}


def get_project(project_id: str) -> dict:
    path = _project_path(project_id)
    if not path.is_file():
        raise KeyError(project_id)
    return {"id": project_id, **json.loads(path.read_text(encoding="utf-8"))}


def list_projects() -> list[dict]:
    out = []
    for p in PROJECTS.glob("*.json") if PROJECTS.is_dir() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": p.stem, "name": d["name"], "updated_at": d.get("updated_at", "")})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda x: x["updated_at"], reverse=True)


def delete_project(project_id: str) -> None:
    path = _project_path(project_id)
    if not path.is_file():
        raise KeyError(project_id)
    path.unlink()
