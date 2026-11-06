"""Thư viện giọng: lưu giọng nhân bản/trộn trong data/voices/<id>/ và yêu thích của giọng preset.

data/voices/<id>/ref.wav      audio mẫu đã chuẩn hoá (mono, cắt lặng, peak-normalize)
data/voices/<id>/meta.json    metadata
data/voices/<id>/preview.*    câu đọc thử (sinh khi gọi /preview)
data/voices/<id>/emb.*.npz    cache embedding do engine tự ghi (nếu có)
data/favorites.json           ["engine:voice_id", …] cho giọng preset
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DATA = Path(os.getenv("TTS_DATA_DIR", Path(__file__).parent / "data"))
VOICES = DATA / "voices"
FAVORITES = DATA / "favorites.json"

LIB_PREFIX = "lib:"
MIN_SECONDS, MAX_SECONDS = 3.0, 30.0
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
GENDERS = ("", "nam", "nữ")
REGIONS = ("", "bac", "trung", "nam")
EDITABLE = ("name", "tags", "gender", "region", "description")

_lock = threading.Lock()


class LibraryError(ValueError):
    """Lỗi do dữ liệu người dùng gửi lên (server trả 400)."""


class NotFound(LookupError):
    pass


# ───────────────────────────── helpers ─────────────────────────────

def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "giong"


def parse_tags(raw) -> list[str]:
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    out: list[str] = []
    for t in items:
        t = str(t).strip()
        if t and t.lower() not in (x.lower() for x in out):
            out.append(t[:30])
    return out[:10]


def _clean_fields(name=None, tags=None, gender=None, region=None, description=None) -> dict:
    """Chỉ giữ và kiểm tra các trường được truyền vào (None = không đổi)."""
    out: dict = {}
    if name is not None:
        name = name.strip()
        if not name or len(name) > 60:
            raise LibraryError("Tên giọng phải từ 1 đến 60 ký tự.")
        out["name"] = name
    if tags is not None:
        out["tags"] = parse_tags(tags)
    if gender is not None:
        if gender not in GENDERS:
            raise LibraryError("Giới tính phải là 'nam', 'nữ' hoặc để trống.")
        out["gender"] = gender
    if region is not None:
        if region not in REGIONS:
            raise LibraryError("Vùng miền phải là 'bac', 'trung', 'nam' hoặc để trống.")
        out["region"] = region
    if description is not None:
        out["description"] = description.strip()[:300]
    return out


# ───────────────────────────── audio ─────────────────────────────

def decode_audio(data: bytes) -> tuple[np.ndarray, int]:
    """bytes bất kỳ → (mono float32, sample rate). Thử soundfile trước, ffmpeg là fallback."""
    import soundfile as sf

    try:
        wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return wav.mean(axis=1), sr
    except Exception:
        pass
    if shutil.which("ffmpeg"):
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "wav", "-ac", "1", "pipe:1"],
            input=data, capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout:
            wav, sr = sf.read(io.BytesIO(proc.stdout), dtype="float32", always_2d=True)
            return wav.mean(axis=1), sr
    raise LibraryError(
        "Không đọc được file audio. Hãy dùng wav/mp3/flac/ogg"
        + ("" if shutil.which("ffmpeg") else " (cài ffmpeg để đọc thêm webm/m4a)") + "."
    )


def normalize_reference(data: bytes) -> tuple[np.ndarray, int]:
    """Giải mã, kiểm tra độ dài, cắt lặng hai đầu, chuẩn hoá biên độ."""
    import librosa

    wav, sr = decode_audio(data)
    secs = len(wav) / sr
    if secs < MIN_SECONDS:
        raise LibraryError(f"Audio quá ngắn ({secs:.1f}s). Cần từ {MIN_SECONDS:.0f} đến {MAX_SECONDS:.0f} giây.")
    if secs > MAX_SECONDS:
        raise LibraryError(f"Audio quá dài ({secs:.1f}s). Cần từ {MIN_SECONDS:.0f} đến {MAX_SECONDS:.0f} giây.")
    wav, _ = librosa.effects.trim(wav, top_db=30)
    peak = float(np.abs(wav).max()) if wav.size else 0.0
    if peak < 1e-4:
        raise LibraryError("Audio gần như im lặng.")
    return (wav * (0.95 / peak)).astype(np.float32), sr


# ───────────────────────────── voices ─────────────────────────────

def _dir(voice_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", voice_id):
        raise NotFound(voice_id)
    return VOICES / voice_id


def ref_path(voice_id: str) -> Path:
    """Đường dẫn ref.wav. Giọng source="mix" không có file này; chỉ đường dẫn được trả, không kiểm tra tồn tại."""
    return _dir(voice_id) / "ref.wav"


def voice_dir(voice_id: str) -> Path:
    return _dir(voice_id)


def get(voice_id: str) -> dict:
    meta = _dir(voice_id) / "meta.json"
    if not meta.is_file():
        raise NotFound(voice_id)
    return json.loads(meta.read_text(encoding="utf-8"))


def list_voices(engine: str | None = None, tag: str | None = None, gender: str | None = None) -> list[dict]:
    out = []
    for meta in sorted(VOICES.glob("*/meta.json")) if VOICES.is_dir() else []:
        try:
            v = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if engine and v.get("engine") != engine:
            continue
        if tag and tag.lower() not in (t.lower() for t in v.get("tags", [])):
            continue
        if gender and v.get("gender") != gender:
            continue
        out.append(v)
    out.sort(key=lambda v: v.get("created_at", ""), reverse=True)
    return out


def _make(engine: str, source: str, fields: dict, write, **extra) -> dict:
    """Cấp thư mục mới (slug từ tên), để `write(dir)` ghi dữ liệu, rồi ghi meta.json."""
    clean = _clean_fields(**{k: fields.get(k, "") for k in EDITABLE})
    if not clean.get("name"):
        raise LibraryError("Tên giọng phải từ 1 đến 60 ký tự.")
    with _lock:
        base = slugify(clean["name"])
        voice_id, n = base, 2
        while (VOICES / voice_id).exists():
            voice_id, n = f"{base}-{n}", n + 1
        d = VOICES / voice_id
        d.mkdir(parents=True)
        try:
            write(d)
            meta = {
                "id": voice_id, **clean, "engine": engine, "source": source, "consent": True, "favorite": False,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra,
            }
            _write_json(d / "meta.json", meta)
        except BaseException:
            shutil.rmtree(d, ignore_errors=True)
            raise
    return meta


def create(*, engine, wav: np.ndarray, sr: int, consent: bool, source: str = "clone", **fields) -> dict:
    """Ghi ref.wav + meta.json. Việc tiền xử lý riêng của engine do server gọi sau đó."""
    import soundfile as sf

    if not consent:
        raise LibraryError("Cần xác nhận bạn là chủ giọng nói hoặc đã được người đó đồng ý.")
    return _make(engine, source, fields, lambda d: sf.write(str(d / "ref.wav"), wav, sr, subtype="PCM_16"),
                 duration=round(len(wav) / sr, 2))


def create_mix(*, engine: str, cache_name: str, arrays: dict, mix_meta: dict, **fields) -> dict:
    """Lưu giọng trộn: <cache_name> (npz các mảng do engine tạo) + meta.json, KHÔNG có ref.wav.
    consent=True vì check_mixable đã xác nhận cả hai giọng nguồn trước khi gọi."""
    return _make(engine, "mix", fields, lambda d: np.savez(d / cache_name, **arrays), **mix_meta)


def check_mixable(voice: str, _depth: int = 0) -> None:
    """Giọng preset trộn được. Giọng thư viện phải có consent; giọng mix thì các giọng nguồn còn tồn tại
    cũng phải đạt (đệ quy). Raise NotFound / LibraryError."""
    if not voice.startswith(LIB_PREFIX):
        return
    meta = get(voice[len(LIB_PREFIX):])
    if not meta.get("consent"):
        raise LibraryError(f"Giọng '{meta.get('name', voice)}' chưa có xác nhận quyền sử dụng nên không trộn được.")
    if meta.get("source") == "mix" and _depth < 10:
        for parent in (meta.get("voice_a"), meta.get("voice_b")):
            try:
                check_mixable(parent, _depth + 1)
            except NotFound:
                pass  # giọng nguồn đã bị xoá: consent đã được kiểm lúc tạo giọng mix


def update(voice_id: str, **fields) -> dict:
    changes = _clean_fields(**{k: fields.get(k) for k in EDITABLE})
    if fields.get("favorite") is not None:
        changes["favorite"] = bool(fields["favorite"])
    with _lock:
        meta = get(voice_id)
        meta.update(changes)
        _write_json(_dir(voice_id) / "meta.json", meta)
    return meta


def delete(voice_id: str) -> None:
    with _lock:
        get(voice_id)
        shutil.rmtree(_dir(voice_id))


# ───────────────────────────── yêu thích giọng preset ─────────────────────────────

def favorites() -> set[str]:
    try:
        return set(json.loads(FAVORITES.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def set_favorite(engine: str, voice: str, on: bool) -> None:
    """Giọng thư viện ghi vào meta.json, giọng preset ghi vào favorites.json (key "engine:voice_id")."""
    if voice.startswith(LIB_PREFIX):
        update(voice[len(LIB_PREFIX):], favorite=on)
        return
    with _lock:
        favs = favorites()
        (favs.add if on else favs.discard)(f"{engine}:{voice}")
        FAVORITES.parent.mkdir(parents=True, exist_ok=True)
        _write_json(FAVORITES, sorted(favs))
