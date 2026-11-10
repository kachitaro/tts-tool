"""Thư viện hiệu ứng âm thanh cho thẻ kiểu [tiếng mưa] (chưa nối vào pipeline, xem dialogue / narrate).

Model của ta (edge, VieNeu) không tự tạo được tiếng mưa, tiếng gõ cửa… nên thẻ hiệu ứng chạy bằng cách ghép file âm thanh.

data/sfx/builtin/<id>-v<VERSION>.wav   âm có sẵn, tự sinh bằng numpy/scipy một lần (đổi công thức thì tăng VERSION)
data/sfx/user/<id>.wav                 âm người dùng thêm (id = u-<slug>-<6 hex>, xoá rồi thêm lại không dính cache cũ)
data/sfx/user.json                     danh sách âm người dùng

Mọi âm được chuẩn hoá: mono float32 48 kHz, cắt lặng hai đầu, ≤ 15 giây, RMS phần có tiếng ≈ 0.08 (nhỏ hơn giọng đọc),
peak ≤ 0.9, fade vào 4 ms / ra 30 ms. `audio(id)` trả âm đã chuẩn hoá kèm 0.1 giây lặng hai đầu.
"""

from __future__ import annotations

import functools
import json
import re
import secrets
import threading
import time
import unicodedata
import zlib
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr
from scipy import signal

import library

SR = 48000  # = dialogue.SR (không import để khỏi vòng: dialogue sẽ gọi sfx)
VERSION = 1
MAX_SECONDS = 15.0
TARGET_RMS = 0.08
PEAK = 0.9
EDGE_PAD_S = 0.1
NAME_MAX = 30

ROOT = library.DATA / "sfx"
BUILTIN_DIR = ROOT / "builtin"
USER_DIR = ROOT / "user"
USER_JSON = ROOT / "user.json"

_USER_ID = re.compile(r"u-[a-z0-9-]+")
_lock = threading.RLock()


class SfxError(ValueError):
    """Lỗi do người dùng (tên trùng, file hỏng…): thông báo dùng được nguyên văn."""


class SfxNotFound(LookupError):
    pass


# ───────────────────────── tổng hợp ─────────────────────────


def _t(d: float) -> np.ndarray:
    return np.arange(int(d * SR), dtype=np.float64) / SR


def _noise(rng: np.random.Generator, d: float) -> np.ndarray:
    return rng.standard_normal(int(d * SR))


def _filt(x: np.ndarray, kind: str, cut: float | tuple[float, float], order: int = 4) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, cut, btype=kind, fs=SR, output="sos"), x)


def _put(buf: np.ndarray, sig: np.ndarray, at: float, amp: float = 1.0) -> None:
    i = int(at * SR)
    if i >= len(buf):
        return
    sig = sig[: len(buf) - i]
    buf[i : i + len(sig)] += amp * sig


def _decay(d: float, tau: float, attack: float = 0.0015) -> np.ndarray:
    t = _t(d)
    return np.exp(-t / tau) * np.minimum(1.0, t / attack) if attack else np.exp(-t / tau)


def _partials(freqs, amps, taus, d: float, attack: float = 0.001) -> np.ndarray:
    t = _t(d)
    out = np.zeros_like(t)
    for f, a, tau in zip(freqs, amps, taus, strict=True):
        out += a * np.sin(2 * np.pi * f * t) * np.exp(-t / tau)
    return out * np.minimum(1.0, t / attack)


def _smooth(rng: np.random.Generator, d: float, hz: float) -> np.ndarray:
    """Đường 0..1 đổi chậm (cho gió, mưa to nhỏ)."""
    m = _filt(_noise(rng, d), "low", hz, 2)
    return 0.5 + 0.5 * m / (np.abs(m).max() + 1e-9)


def _fades(x: np.ndarray, fin: float, fout: float) -> np.ndarray:
    x = x.copy()
    a, b = min(int(fin * SR), len(x) // 2), min(int(fout * SR), len(x) // 2)
    if a:
        x[:a] *= np.linspace(0, 1, a)
    if b:
        x[-b:] *= np.linspace(1, 0, b)
    return x


def _thump(f_hi: float, f_lo: float, tau: float, d: float) -> np.ndarray:
    t = _t(d)
    f = f_lo + (f_hi - f_lo) * np.exp(-t / 0.04)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / tau)


def _mua(rng: np.random.Generator) -> np.ndarray:
    d = 4.5
    bed = _filt(_noise(rng, d), "band", (800, 7000)) * (0.8 + 0.2 * _smooth(rng, d, 3))
    imp = np.zeros(int(d * SR))
    idx = rng.integers(0, len(imp), int(d * 90))
    imp[idx] = rng.uniform(0.3, 1.0, len(idx))
    drops = _filt(_filt(imp, "high", 1500), "low", 12000)
    drops = np.clip(
        drops / (drops.std() + 1e-9), -3, 3
    )  # xung đơn lẻ mà cao thì peak chặn mất RMS cả tiếng mưa
    return _fades(bed / bed.std() + 0.7 * drops, 0.3, 0.6)


def _sam(rng: np.random.Generator) -> np.ndarray:
    d = 4.8
    t = _t(d)
    rumble = _filt(np.cumsum(_noise(rng, d)), "band", (25, 220), 2)
    env = np.zeros_like(t)
    for at, a, tau in ((0.12, 1.0, 0.6), (0.9, 0.7, 0.5), (1.7, 0.5, 0.5), (2.6, 0.3, 0.7)):
        dt = np.maximum(t - at, 0)
        env += a * (1 - np.exp(-dt / 0.05)) * np.exp(-dt / tau) * (t >= at)
    crack = np.zeros_like(t)
    c = _filt(_noise(rng, 0.5), "band", (300, 3000)) * _decay(0.5, 0.12)
    _put(crack, c, 0.1)
    return crack / np.abs(crack).max() * 0.6 + rumble / np.abs(rumble).max() * env * 1.6


def _gio(rng: np.random.Generator) -> np.ndarray:
    d = 5.0
    body = _filt(_noise(rng, d), "band", (150, 1500)) * (0.35 + 0.65 * _smooth(rng, d, 0.4))
    whistle = _filt(_noise(rng, d), "band", (900, 2400)) * _smooth(rng, d, 0.7) ** 2
    return _fades(body / body.std() + 0.3 * whistle / whistle.std(), 0.8, 0.8)


def _tim_dap(rng: np.random.Generator) -> np.ndarray:
    buf = np.zeros(int(3.0 * SR))
    for k in range(3):
        at = 0.05 + 0.85 * k
        _put(buf, _thump(95, 52, 0.07, 0.3), at)
        _put(buf, _thump(80, 45, 0.06, 0.3), at + 0.22, 0.7)
    return _filt(buf, "low", 220, 2)


def _go_cua(rng: np.random.Generator) -> np.ndarray:
    buf = np.zeros(int(1.5 * SR))
    for at, a in ((0.0, 1.0), (0.42, 0.85), (0.84, 0.95)):
        knock = _partials((180, 410, 760), (1, 0.5, 0.3), (0.05, 0.035, 0.02), 0.25)
        knock += 0.5 * _filt(_noise(rng, 0.25), "band", (300, 2000)) * _decay(0.25, 0.012)
        _put(buf, knock, at, a)
    return buf


def _chuong(rng: np.random.Generator) -> np.ndarray:
    f0 = 520
    sig = _partials(
        [f0 * r for r in (0.5, 1, 1.19, 1.5, 2.0, 2.76, 4.07)] + [f0 + 1.7],
        (0.6, 1, 0.5, 0.4, 0.6, 0.3, 0.15, 0.6),
        (3.0, 2.5, 1.8, 1.5, 1.0, 0.6, 0.3, 2.2),
        4.0,
    )
    return sig + 0.3 * _filt(_noise(rng, 4.0), "high", 2500) * _decay(4.0, 0.004)


def _chieng(rng: np.random.Generator) -> np.ndarray:
    d = 5.0
    f0 = 110
    freqs = [f0 * r for r in (1, 1.47, 2.03, 2.51, 3.12, 4.3)] + [f0 + 2.0, f0 * 2.03 + 3.0]
    sig = _partials(
        freqs,
        (1, 0.7, 0.6, 0.4, 0.3, 0.2, 0.8, 0.4),
        (2.5, 2, 1.5, 1.2, 0.9, 0.6, 2.4, 1.4),
        d,
        0.04,
    )
    return sig + 0.4 * _filt(_noise(rng, d), "low", 1500) * _decay(d, 0.1, 0.02)


def _dien_thoai(rng: np.random.Generator) -> np.ndarray:
    d = 3.0
    t = _t(0.4)
    tone = np.sin(2 * np.pi * 440 * t) + np.sin(2 * np.pi * 480 * t)
    ring = (
        tone
        * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 20 * t)))
        * np.minimum(1, np.minimum(t, 0.4 - t) / 0.01)
    )
    buf = np.zeros(int(d * SR))
    for at in (0.0, 0.6, 2.0, 2.6):
        _put(buf, ring, at)
    return _filt(buf, "low", 3000, 2)


def _trong_don(rng: np.random.Generator) -> np.ndarray:
    buf = np.zeros(int(3.4 * SR))
    at, gap = 0.0, 0.16
    while at < 2.0:
        a = 0.3 + 0.7 * at / 2.0
        hit = _filt(_noise(rng, 0.12), "band", (200, 3000)) * _decay(0.12, 0.015)
        hit += 0.8 * np.sin(2 * np.pi * 150 * _t(0.12)) * _decay(0.12, 0.03)
        _put(buf, hit, at, a * rng.uniform(0.85, 1.0))
        at += gap
        gap = max(0.04, gap * 0.9)
    _put(buf, _thump(110, 70, 0.25, 0.8), 2.1, 1.2)
    _put(buf, _filt(_noise(rng, 1.2), "high", 4000) * _decay(1.2, 0.45), 2.1, 0.7)
    return buf


def _ban_phim(rng: np.random.Generator) -> np.ndarray:
    buf = np.zeros(int(2.6 * SR))
    at = 0.05
    for k in range(16):
        click = _filt(_noise(rng, 0.05), "band", (1500, 6000)) * _decay(0.05, 0.006)
        click += 0.6 * np.sin(2 * np.pi * rng.uniform(1500, 2200) * _t(0.05)) * _decay(0.05, 0.004)
        _put(buf, click, at, rng.uniform(0.6, 1.0) * (1.3 if k == 15 else 1.0))
        at += rng.uniform(0.07, 0.2)
    return buf


def _vo_tay(rng: np.random.Generator) -> np.ndarray:
    d = 4.0
    t = _t(d)
    lam = np.clip(t / 0.4, 0, 1) * np.clip((d - 0.3 - t) / 1.6, 0, 1)
    lam *= 0.8 + 0.2 * _smooth(rng, d, 4)
    out = np.zeros(len(t))
    for _ in range(4):
        imp = np.zeros(len(t))
        hit = rng.random(len(t)) < lam * 90 / SR
        imp[hit] = rng.uniform(0.3, 1.0, hit.sum())
        kernel = _filt(_noise(rng, 0.04), "band", (800, 5000)) * _decay(0.04, 0.012)
        out += signal.fftconvolve(imp, kernel)[: len(t)]
    return out / (out.std() + 1e-9) + 0.35 * _filt(_noise(rng, d), "band", (600, 4000)) * lam


def _buoc_chan(rng: np.random.Generator) -> np.ndarray:
    buf = np.zeros(int(2.6 * SR))
    for k in range(4):
        at = 0.1 + 0.55 * k
        step = _filt(_noise(rng, 0.2), "low", 700) * _decay(0.2, 0.04)
        step += 0.9 * np.sin(2 * np.pi * (80 + 8 * (k % 2)) * _t(0.2)) * _decay(0.2, 0.06)
        _put(
            buf,
            _filt(_noise(rng, 0.1), "band", (1500, 4000)) * _decay(0.1, 0.04, 0.03),
            at - 0.04,
            0.2,
        )
        _put(buf, step, at, 0.9 + 0.1 * (k % 2))
    return buf


def _kiem(rng: np.random.Generator) -> np.ndarray:
    buf = np.zeros(int(2.2 * SR))
    scrape = _filt(_noise(rng, 0.14), "band", (3000, 9000)) * np.linspace(0.1, 1, int(0.14 * SR))
    _put(buf, scrape, 0.0, 0.5)
    ring = _partials(
        (2300, 3410, 4780, 6120, 7440, 1100),
        (1, 0.8, 0.6, 0.4, 0.3, 0.7),
        (0.9, 0.7, 0.5, 0.35, 0.25, 0.6),
        2.0,
    )
    ring += 0.8 * _filt(_noise(rng, 2.0), "high", 2000) * _decay(2.0, 0.03)
    _put(buf, ring, 0.12)
    return buf


def _no_may(rng: np.random.Generator) -> np.ndarray:
    d = 4.0
    buf = np.zeros(int(d * SR))
    t = _t(1.1)
    gate = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 11 * t))
    crank = signal.sawtooth(2 * np.pi * 55 * t) * gate * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
    _put(buf, _filt(crank, "low", 600, 2), 0.0, 0.8)
    _put(buf, _filt(_noise(rng, 0.4), "low", 400) * _decay(0.4, 0.1), 1.1, 1.5)
    n = int(2.9 * SR)
    t2 = np.arange(n) / SR
    f = 28 + 14 * np.exp(-t2 / 0.35) + 0.8 * _filt(_noise(rng, 2.9), "low", 6, 2) * 6
    phase = 2 * np.pi * np.cumsum(f) / SR
    eng = sum(np.sin(k * phase + k) / k for k in range(1, 13))
    eng = _filt(eng, "low", 900, 2) + 0.2 * _filt(_noise(rng, 2.9), "low", 400)
    _put(buf, _fades(eng, 0.05, 0.3) * np.minimum(1, 0.4 + t2 / 0.5), 1.15, 0.9)
    return buf


# id → (hàm sinh, thẻ, mô tả, bí danh tiếng Anh của ElevenLabs)
_SPECS: dict[str, tuple[Callable[[np.random.Generator], np.ndarray], str, str, tuple[str, ...]]] = {
    "mua": (_mua, "tiếng mưa", "Mưa rơi đều", ("rain falling", "rain")),
    "sam": (_sam, "tiếng sấm", "Sấm rền", ("thunder",)),
    "gio": (_gio, "tiếng gió", "Gió thổi", ("wind",)),
    "tim-dap": (_tim_dap, "tim đập", "Tim đập thình thịch", ("heartbeat",)),
    "go-cua": (_go_cua, "gõ cửa", "Cốc cốc cốc", ("knocking on door",)),
    "chuong": (_chuong, "chuông ngân", "Một tiếng chuông", ("bell ringing",)),
    "chieng": (_chieng, "tiếng chiêng", "Chiêng / cồng", ("gong",)),
    "dien-thoai": (_dien_thoai, "điện thoại reo", "Hai hồi chuông", ("phone ringing",)),
    "trong-don": (_trong_don, "trống dồn", "Trống dồn rồi chũm chọe", ("drum roll",)),
    "ban-phim": (_ban_phim, "gõ phím", "Gõ bàn phím", ("keyboard typing",)),
    "vo-tay": (_vo_tay, "vỗ tay", "Tràng vỗ tay", ("applause",)),
    "buoc-chan": (_buoc_chan, "bước chân", "Bốn bước chân", ("footsteps",)),
    "kiem": (_kiem, "tiếng kiếm", "Kiếm chạm nhau: keng", ("sword clash",)),
    "no-may": (_no_may, "nổ máy", "Đề máy rồi nổ máy", ("engine starting",)),
}
BUILTIN_IDS = tuple(_SPECS)


# ───────────────────────── chuẩn hoá ─────────────────────────


def conform(wav: np.ndarray, sr: int) -> np.ndarray:
    """Âm bất kỳ → mono float32 48 kHz, cắt lặng, ≤ 15 giây, RMS ≈ 0.08, peak ≤ 0.9, có fade. Raise SfxError nếu im lặng."""
    import librosa

    x = np.nan_to_num(np.asarray(wav, dtype=np.float32))
    if sr != SR:
        x = soxr.resample(x, sr, SR)
    if len(x) == 0 or float(np.abs(x).max()) < 1e-4:
        raise SfxError("File này im lặng hoặc quá ngắn. Hãy chọn file có tiếng.")
    x, _ = librosa.effects.trim(x, top_db=45)
    if len(x) > MAX_SECONDS * SR:
        x = _fades(x[: int(MAX_SECONDS * SR)], 0, 0.2)
    frames = librosa.feature.rms(y=x, frame_length=2048, hop_length=512)[0]
    on = frames > frames.max() * 0.1  # chỉ tính phần có tiếng, khỏi bị đoạn lặng kéo RMS xuống
    rms = float(np.sqrt(np.mean(frames[on] ** 2)))
    x = x * (TARGET_RMS / max(rms, 1e-6))
    peak = float(np.abs(x).max())
    if peak > PEAK:
        x = x * (PEAK / peak)
    return _fades(x, 0.004, 0.03).astype(np.float32)


def _write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    sf.write(tmp, x, SR, format="WAV", subtype="PCM_16")
    tmp.replace(path)


def generate(sfx_id: str) -> np.ndarray:
    """Sinh một âm có sẵn (đã chuẩn hoá). Seed cố định theo id nên lần nào cũng giống nhau."""
    fn = _SPECS[sfx_id][0]
    return conform(fn(np.random.default_rng(zlib.crc32(sfx_id.encode()))), SR)


def _builtin_path(sfx_id: str) -> Path:
    path = BUILTIN_DIR / f"{sfx_id}-v{VERSION}.wav"
    with _lock:
        if not path.is_file():
            _write_wav(path, generate(sfx_id))
            for old in BUILTIN_DIR.glob(f"{sfx_id}-v*.wav"):
                if old != path:
                    old.unlink(missing_ok=True)
    return path


# ───────────────────────── âm của người dùng ─────────────────────────


def _norm(s: str) -> str:
    """Dạng so khớp thẻ: NFC, khoảng trắng co giãn, không phân biệt hoa thường."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip().casefold()


def _read_user() -> list[dict]:
    try:
        return json.loads(USER_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError, ValueError:
        return []


def _write_user(items: list[dict]) -> None:
    library._write_json(USER_JSON, items)


def _names() -> dict[str, str]:
    """thẻ (đã chuẩn hoá) → id, gồm tên chính và bí danh."""
    out: dict[str, str] = {}
    for sid, (_, tag, _, aliases) in _SPECS.items():
        for n in (tag, *aliases):
            out[_norm(n)] = sid
    for u in _read_user():
        out[_norm(u["name"])] = u["id"]
    return out


def _check_name(name: str, reserved: Iterable[str]) -> str:
    name = re.sub(r"\s+", " ", unicodedata.normalize("NFC", name)).strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise SfxError(f"Tên thẻ phải từ 1 đến {NAME_MAX} ký tự.")
    if re.search(r"[\[\]:\x00-\x1f]", name):
        raise SfxError(
            "Tên thẻ không được có dấu [ ] hoặc dấu hai chấm. Chỉ cần viết chữ, ví dụ: tiếng còi."
        )
    if _norm(name).startswith("nghỉ"):
        raise SfxError(
            "Tên thẻ không được bắt đầu bằng “nghỉ” vì trùng thẻ nghỉ. Hãy đặt tên khác."
        )
    key = _norm(name)
    if key in _names() or key in {_norm(r.strip("[] ")) for r in reserved}:
        raise SfxError(f"Đã có thẻ [{name}]. Hãy đặt tên khác.")
    return name


def add(name: str, data: bytes, reserved: Iterable[str] = ()) -> dict:
    """Thêm âm của người dùng. `reserved`: các thẻ không được trùng (thẻ cảm xúc của mọi engine)."""
    with _lock:
        name = _check_name(name, reserved)
        try:
            wav, sr = library.decode_audio(data)
        except library.LibraryError as ex:
            raise SfxError(str(ex)) from ex
        x = conform(wav, sr)
        sid = f"u-{library.slugify(name)[:20].strip('-') or 'am'}-{secrets.token_hex(3)}"
        _write_wav(USER_DIR / f"{sid}.wav", x)
        entry = {
            "id": sid,
            "name": name,
            "seconds": round(len(x) / SR, 2),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        _write_user([*_read_user(), entry])
        _invalidate()
        return _public(entry)


def delete(sfx_id: str) -> None:
    with _lock:
        items = _read_user()
        if not any(u["id"] == sfx_id for u in items):
            raise SfxNotFound("Không tìm thấy âm này (âm có sẵn thì không xoá được).")
        _write_user([u for u in items if u["id"] != sfx_id])
        (USER_DIR / f"{sfx_id}.wav").unlink(missing_ok=True)
        _invalidate()


# ───────────────────────── tra cứu ─────────────────────────


def _public(u: dict) -> dict:
    return {
        "id": u["id"], "tag": u["name"], "label": f"[{u['name']}]", "description": "Âm bạn thêm",
        "aliases": [], "source": "user", "seconds": u.get("seconds"),
    }  # fmt: skip


def catalog() -> list[dict]:
    """Âm có sẵn rồi âm của người dùng. `tag` là tên không ngoặc, `label` là thẻ viết đầy đủ."""
    out = []
    for sid, (_, tag, desc, aliases) in _SPECS.items():
        info = sf.info(_builtin_path(sid))
        out.append({
            "id": sid, "tag": tag, "label": f"[{tag}]", "description": desc, "aliases": list(aliases),
            "source": "builtin", "seconds": round(info.duration, 2),
        })  # fmt: skip
    return out + [_public(u) for u in _read_user()]


_rx: re.Pattern | None = None


def _invalidate() -> None:
    global _rx
    _rx = None


def _regex() -> re.Pattern:
    global _rx
    if _rx is None:
        with _lock:
            names = sorted(_names(), key=len, reverse=True)  # thẻ dài khớp trước
            body = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names)
            _rx = re.compile(rf"\[\s*(?:{body})\s*\]", re.IGNORECASE)
    return _rx


def _lookup(tag_text: str) -> str | None:
    return _names().get(_norm(tag_text.strip("[] \t\n")))


def find(tag: str) -> str | None:
    """'[Tiếng  sấm]' hoặc 'rain' → id, không thấy thì None."""
    return _lookup(tag)


def has_sfx(text: str) -> bool:
    if "[" not in text:
        return False
    return bool(_regex().search(unicodedata.normalize("NFC", text)))


def split(text: str) -> list[tuple[str, str]]:
    """[("text", ...), ("sfx", id), ...]. Thẻ lạ (vd [witch voice]) vẫn là chữ. Không có thẻ hiệu ứng thì giữ nguyên `text`."""
    if "[" not in text:
        return [("text", text)] if text else []
    norm = unicodedata.normalize("NFC", text)
    rx = _regex()
    if not rx.search(norm):
        return [("text", text)]
    out: list[tuple[str, str]] = []
    pos = 0
    for m in rx.finditer(norm):
        if m.start() > pos:
            out.append(("text", norm[pos : m.start()]))
        out.append(("sfx", _lookup(m.group(0)) or ""))
        pos = m.end()
    if pos < len(norm):
        out.append(("text", norm[pos:]))
    return out


def path_of(sfx_id: str) -> Path:
    """Đường dẫn file wav của một âm (id lạ → SfxNotFound; chặn path traversal)."""
    if sfx_id in _SPECS:
        return _builtin_path(sfx_id)
    if _USER_ID.fullmatch(sfx_id):
        p = USER_DIR / f"{sfx_id}.wav"
        if p.is_file():
            return p
    raise SfxNotFound("Không tìm thấy âm này.")


def key(sfx_id: str) -> str:
    """Phần khoá cache: đổi công thức (VERSION) hay thay âm thì khoá đổi."""
    path_of(sfx_id)
    return f"{sfx_id}-v{VERSION}" if sfx_id in _SPECS else sfx_id


@functools.lru_cache(maxsize=32)
def _load(sfx_id: str) -> np.ndarray:
    x, _ = sf.read(path_of(sfx_id), dtype="float32")
    pad = np.zeros(int(EDGE_PAD_S * SR), dtype=np.float32)
    out = np.concatenate([pad, x, pad])
    out.flags.writeable = False
    return out


def audio(sfx_id: str) -> np.ndarray:
    """Âm đã chuẩn hoá kèm 0.1 giây lặng hai đầu (chỉ đọc, không sửa tại chỗ)."""
    return _load(sfx_id)


def _selftest() -> None:  # python sfx.py: sinh đủ âm, in thời gian
    t0 = time.perf_counter()
    for sid in BUILTIN_IDS:
        t = time.perf_counter()
        x = generate(sid)
        assert np.isfinite(x).all() and 0.5 < len(x) / SR <= MAX_SECONDS, sid
        print(
            f"{sid:12s} {len(x) / SR:5.2f}s peak={np.abs(x).max():.2f} sinh {time.perf_counter() - t:.2f}s"
        )
    print(f"tổng {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    _selftest()
