from __future__ import annotations

import io
import logging
import os
import threading
from pathlib import Path

import numpy as np

import anyio

import library

from .base import Engine, PriorityLock

log = logging.getLogger(__name__)

# Thẻ cảm xúc thật của checkpoint v3 Turbo, lấy từ _EMOTION_TAG_TO_K trong
# vieneu_utils/phonemize_text.py (ngoài ra còn bản tiếng Anh: [chuckle] [sigh] [clear throat]).
EMOTION_TAGS = ["[cười]", "[thở dài]", "[hắng giọng]"]

_GENDER = {"male": "nam", "female": "nữ"}
_REGION = {"Bắc": "bac", "Trung": "trung", "Nam": "nam"}
_STYLE = {"tu_nhien": "tự nhiên", "doc_truyen": "đọc truyện", "tin_tuc": "tin tức"}

# ── Trộn giọng (Phase 3a/3b; thí nghiệm ở scripts/mix_experiment.py, số đo ở out/mix/metrics.json) ──
VARIANTS = ("A", "B", "C")
# Thanh trượt UI (1 = giọng A thuần) → alpha thật. Bảng = mapping.C.slider_to_alpha của lần chạy 3a-bis;
# thanh trượt tuyến tính vì "A − B" đo được gần như tuyến tính theo slider sau phép ánh xạ này.
SLIDER_KNOTS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
ALPHA_KNOTS = [0.0, 0.232, 0.384, 0.433, 0.47, 0.511, 0.57, 0.632, 0.698, 0.794, 1.0]


def slider_to_alpha(slider: float) -> float:
    return float(np.interp(slider, SLIDER_KNOTS, ALPHA_KNOTS))


def slerp_mix(ea: np.ndarray, eb: np.ndarray, alpha: float) -> np.ndarray:
    """Biến thể C: slerp trên hướng, nội suy tuyến tính norm. alpha=1 → ea."""
    na, nb = np.linalg.norm(ea), np.linalg.norm(eb)
    ua, ub = ea / na, eb / nb
    omega = float(np.arccos(np.clip(ua @ ub, -1.0, 1.0)))
    if omega < 1e-6:
        u = ua
    else:
        u = (np.sin((1 - alpha) * omega) * ub + np.sin(alpha * omega) * ua) / np.sin(omega)
    return (u * (alpha * na + (1 - alpha) * nb)).astype(np.float32)


def make_embedding(variant: str, ea: np.ndarray, eb: np.ndarray, alpha: float) -> np.ndarray:
    """A và B: nội suy tuyến tính; C: slerp + nội suy norm."""
    if variant == "C":
        return slerp_mix(ea, eb, alpha)
    return (alpha * ea + (1 - alpha) * eb).astype(np.float32)


def codes_owner(alpha: float, na: float, nb: float) -> str:
    """'a' hoặc 'b': giọng có trọng số lớn hơn cho codes; hoà (alpha=0.5) → giọng có norm embedding lớn hơn."""
    if alpha != 0.5:
        return "a" if alpha > 0.5 else "b"
    return "a" if na >= nb else "b"


def check_emotion_tags() -> list[str]:
    """So danh sách ghi cứng với _EMOTION_TAG_TO_K của vieneu; trả về các điểm lệch (rỗng = khớp).
    Thư viện đổi tên biến private này thì bỏ qua (không có gì để so)."""
    try:
        from vieneu_utils.phonemize_text import _EMOTION_TAG_TO_K as real
    except ImportError:
        return []
    problems = [f"{t} không còn trong vieneu" for t in EMOTION_TAGS if t[1:-1] not in real]
    # Mỗi cảm xúc k phải có đúng một thẻ tiếng Việt ghi cứng.
    covered = {real[t[1:-1]] for t in EMOTION_TAGS if t[1:-1] in real}
    problems += [f"vieneu có thêm cảm xúc #{k} chưa có thẻ" for k in sorted(set(real.values()) - covered)]
    return problems


def has_vnni() -> bool:
    """CPU có tập lệnh VNNI (avx_vnni hoặc avx512_vnni)? int8 chỉ nhanh và không méo tiếng khi có."""
    try:
        flags = Path("/proc/cpuinfo").read_text().split("flags", 1)[1].split("\n", 1)[0].split()
    except (OSError, IndexError):
        return False
    return "avx_vnni" in flags or "avx512_vnni" in flags


def default_precision() -> str:
    """Tự chọn: int8 nếu CPU có VNNI, không thì fp32. VIENEU_PRECISION (fp32 | int8) ghi đè."""
    env = os.getenv("VIENEU_PRECISION", "").strip().lower()
    if env in ("fp32", "int8"):
        return env
    if env:
        log.warning("VIENEU_PRECISION=%r không hợp lệ (chỉ fp32 hoặc int8): tự chọn theo CPU.", env)
    return "int8" if has_vnni() else "fp32"


def _materialize_hf_symlinks() -> None:
    """onnxruntime từ chối file .data trỏ qua symlink ra ngoài thư mục model (cache HF
    dùng symlink snapshots → blobs). Thay symlink bằng bản sao thật."""
    import shutil

    from huggingface_hub.constants import HF_HUB_CACHE

    for repo in Path(HF_HUB_CACHE).glob("models--*"):
        for link in (repo / "snapshots").rglob("*"):
            if link.is_symlink():
                real = link.resolve()
                link.unlink()
                shutil.copyfile(real, link)


def _voice_entry(vid: str, label: str, preset: dict) -> dict:
    """Metadata có cấu trúc lấy từ _preset_voices của vieneu; nhãn "Nam · Bắc · …" chỉ là fallback."""
    desc = preset.get("description") or ""
    parts = [p.strip() for p in desc.split("·")]
    gender = _GENDER.get(preset.get("gender") or "") or {"Nam": "nam", "Nữ": "nữ"}.get(parts[0], "")
    region = _REGION.get(parts[1], "") if len(parts) > 1 else ""
    style = _STYLE.get(preset.get("style") or "") or (parts[2].removeprefix("Phong cách ") if len(parts) > 2 else "")
    # Giọng không có description và không phải "featured" là giọng do UI cũ lưu bằng add_voice(save=True).
    legacy = not desc and preset.get("featured") is None and bool(preset)
    return {
        "id": vid, "name": vid, "label": label, "gender": gender, "region": region,
        "tags": [style] if style else [], "description": desc,
        "source": "clone" if legacy else "preset",
    }


class VieNeuEngine(Engine):
    """Nạp model lười (lần gọi đầu mới tải), khoá để chỉ 1 request chạy model cùng lúc."""

    id = "vieneu"
    label = "Chất lượng cao"
    description = "VieNeu · offline"
    local = True
    name = "VieNeu-TTS"
    install_hint = "pip install vieneu"

    def __init__(self) -> None:
        self._tts = None
        self._load_lock = threading.Lock()
        self._run_lock = PriorityLock()  # tương tác vào trước việc nền (hàng đợi sách nói)
        self._lib_cache: dict[str, dict] = {}
        for p in check_emotion_tags():
            log.warning("Danh sách thẻ cảm xúc ghi cứng lệch với vieneu: %s", p)

    @staticmethod
    def installed() -> bool:
        try:
            import vieneu  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def loaded(self) -> bool:
        return self._tts is not None

    @property
    def _mode(self) -> str:
        return os.getenv("VIENEU_MODE", "v3turbo")

    def capabilities(self) -> dict:
        # Thẻ cảm xúc chỉ có ở mode mặc định v3turbo.
        return {"clone": True, "pitch": False,
                "emotion_tags": EMOTION_TAGS if self._mode == "v3turbo" else [], "mix": True, "normalize": True}

    def _get(self):
        if self._tts is None:
            with self._load_lock:
                if self._tts is None:
                    from vieneu import Vieneu

                    kwargs = {}
                    if self._mode == "v3turbo":  # precision chỉ có ở backend ONNX/CPU của v3turbo
                        kwargs["precision"] = default_precision()
                    if os.getenv("VIENEU_MODE"):  # ví dụ: v3nano
                        kwargs["mode"] = os.environ["VIENEU_MODE"]
                    try:
                        self._tts = Vieneu(**kwargs)
                    except Exception as e:
                        if "External data path" not in str(e):
                            raise
                        _materialize_hf_symlinks()
                        self._tts = Vieneu(**kwargs)
        return self._tts

    def _voices(self) -> list[dict]:
        tts = self._get()
        presets = getattr(tts, "_preset_voices", {})
        return [_voice_entry(vid, label, presets.get(vid) or {}) for label, vid in tts.list_preset_voices()]

    async def voices(self) -> list[dict]:
        # Lần đầu sẽ tải model (vài trăm MB) — có thể mất vài phút
        return await anyio.to_thread.run_sync(self._voices)

    # ── giọng trong thư viện ──
    # add_voice(save=True) của vieneu ghi đè file voices_v3_turbo.json nằm trong site-packages
    # (lẫn với giọng dựng sẵn, mất khi nâng cấp gói) nên không dùng. Ta encode ref.wav một lần,
    # cache speaker_emb + codes thành emb.<mode>.npz cạnh ref.wav rồi truyền cho infer(voice=dict).
    def _lib_voice(self, tts, voice_id: str) -> dict:
        meta = library.get(voice_id)
        if meta.get("source") == "mix":  # giọng trộn: chỉ có emb.<mode>.npz, không có ref.wav để encode lại
            cache = library.voice_dir(voice_id) / f"emb.{self._mode}.npz"
            if not cache.is_file():
                raise ValueError(f"Giọng trộn này tạo ở mode '{meta.get('mode')}', hiện đang chạy '{self._mode}'.")
            with np.load(cache) as z:
                return {"speaker_emb": z["speaker_emb"], "codes": z["codes"] if z["codes"].size else None}
        ref = library.ref_path(voice_id)
        if not ref.is_file():
            raise library.NotFound(voice_id)
        cache = ref.with_name(f"emb.{self._mode}.npz")
        stamp = ref.stat().st_mtime_ns
        hit = self._lib_cache.get(voice_id)
        if hit and hit["stamp"] == stamp:
            return hit["voice"]
        voice = None
        if cache.is_file() and cache.stat().st_mtime_ns >= stamp:
            with np.load(cache) as z:
                voice = {"speaker_emb": z["speaker_emb"], "codes": z["codes"] if z["codes"].size else None}
        if voice is None:
            emb, codes = tts.encode_reference(ref, denoise=False)  # ref.wav đã denoise lúc thêm
            voice = {"speaker_emb": np.asarray(emb, dtype=np.float32),
                     "codes": None if codes is None else np.asarray(codes, dtype=np.int64)}
            np.savez(cache, speaker_emb=voice["speaker_emb"],
                     codes=voice["codes"] if voice["codes"] is not None else np.zeros(0, dtype=np.int64))
        self._lib_cache[voice_id] = {"stamp": stamp, "voice": voice}
        return voice

    def prepare_reference(self, wav_path: Path) -> None:
        tts = self._get()
        with self._run_lock:
            try:
                tts.denoise(str(wav_path), out_path=str(wav_path))
            except RuntimeError as e:  # backend không có denoiser: giữ nguyên file đã cắt lặng
                log.warning("Bỏ qua denoise: %s", e)
            self._lib_voice(tts, wav_path.parent.name)  # encode sẵn để lần đọc đầu không phải chờ

    def slider_to_alpha(self, slider: float) -> float:
        return slider_to_alpha(slider)

    def unusable_reason(self, meta: dict) -> str | None:
        # Giọng mix lưu embedding theo mode lúc tạo; mode khác thì không dùng được.
        if meta.get("source") == "mix" and meta.get("mode") != self._mode:
            return f"tạo ở mode {meta.get('mode')}"
        return None

    def precision(self) -> str | None:
        return default_precision() if self._mode == "v3turbo" else None

    def cache_tag(self) -> str:
        # fp32 giữ tag cũ "v3turbo" để cache hiện có còn dùng được; int8 cho audio khác nên tag riêng.
        precision = self.precision()
        return self._mode if precision in (None, "fp32") else f"{self._mode}-{precision}"

    def _voice_data(self, tts, vid: str) -> dict:
        """Giọng preset hoặc lib: → {"speaker_emb", "codes"}."""
        try:
            if vid.startswith(library.LIB_PREFIX):
                return self._lib_voice(tts, vid[len(library.LIB_PREFIX):])
            p = tts.get_preset_voice(vid)
        except (library.NotFound, ValueError) as e:
            raise ValueError(f"Không tìm thấy giọng '{vid}'.") from e
        return {"speaker_emb": p["speaker_emb"], "codes": p.get("codes")}

    def _mix(self, voice_a: str, voice_b: str, alpha: float, variant: str) -> dict:
        if variant not in VARIANTS:
            raise ValueError(f"variant phải là một trong {VARIANTS}.")
        tts = self._get()
        with self._run_lock:  # encode giọng clone chưa có cache dùng model
            da, db = self._voice_data(tts, voice_a), self._voice_data(tts, voice_b)
        ea, eb = (np.asarray(d["speaker_emb"], dtype=np.float32) for d in (da, db))
        owner = codes_owner(alpha, float(np.linalg.norm(ea)), float(np.linalg.norm(eb)))
        codes = None if variant == "B" else (da if owner == "a" else db)["codes"]
        return {
            "speaker_emb": make_embedding(variant, ea, eb, alpha), "codes": codes,
            "codes_from": None if variant == "B" or codes is None else (voice_a if owner == "a" else voice_b),
            "variant": variant, "alpha": alpha, "mode": self._mode, "cache_name": f"emb.{self._mode}.npz",
        }

    async def mix(self, voice_a: str, voice_b: str, alpha: float, variant: str = "C") -> dict:
        return await anyio.to_thread.run_sync(self._mix, voice_a, voice_b, alpha, variant)

    def _synthesize(self, text: str, voice: str | None, speed: int, ref_audio: str | None,
                    voice_data: dict | None = None, seed: int | None = None) -> bytes:
        import soundfile as sf

        tts = self._get()
        with self._run_lock:
            if seed is not None:  # vieneu lấy mẫu bằng RNG toàn cục; khoá run_lock giữ cho seed không bị chen ngang
                import random

                random.seed(seed)
                np.random.seed(seed)
            if voice_data is None and not ref_audio and voice and voice.startswith(library.LIB_PREFIX):
                voice_data = self._lib_voice(tts, voice[len(library.LIB_PREFIX):])
            if ref_audio:
                audio = tts.infer(text, ref_audio=ref_audio, denoise=True)
            elif voice_data is not None:
                audio = tts.infer(text, voice=voice_data, use_ref_codes=voice_data.get("codes") is not None)
            else:
                audio = tts.infer(text, voice=voice or None)

        audio = np.asarray(audio, dtype=np.float32)
        if speed != 0 and audio.size:
            import librosa

            audio = librosa.effects.time_stretch(audio, rate=1 + speed / 100)

        buf = io.BytesIO()
        sf.write(buf, audio, tts.sample_rate, format="WAV")
        return buf.getvalue()

    async def synthesize(self, text: str, voice: str, speed: int, **opts) -> tuple[bytes, str]:
        data = await anyio.to_thread.run_sync(
            self._synthesize, text, voice, speed, opts.get("ref_audio"), opts.get("voice_data"), opts.get("seed"))
        return data, "audio/wav"
