from __future__ import annotations

import io

from .base import Engine

# Dùng khi không lấy được danh sách giọng từ Microsoft (ví dụ mất mạng).
FALLBACK = [
    {"id": "vi-VN-HoaiMyNeural", "name": "HoaiMy", "label": "Hoài My (nữ, Việt)", "gender": "nữ", "region": "", "lang": "vi-VN"},
    {"id": "vi-VN-NamMinhNeural", "name": "NamMinh", "label": "Nam Minh (nam, Việt)", "gender": "nam", "region": "", "lang": "vi-VN"},
    {"id": "en-US-AvaMultilingualNeural", "name": "AvaMultilingual", "label": "Ava (nữ, Anh, đa ngôn ngữ)", "gender": "nữ", "region": "", "lang": "en-US"},
    {"id": "en-US-AndrewMultilingualNeural", "name": "AndrewMultilingual", "label": "Andrew (nam, Anh, đa ngôn ngữ)", "gender": "nam", "region": "", "lang": "en-US"},
]
PITCH_DROPPED = "Đã bỏ cao độ do edge-tts không hỗ trợ tổ hợp này"


class EdgeEngine(Engine):
    id = "edge"
    label = "Nhanh"
    description = "edge-tts · cần mạng"
    name = "edge-tts"
    install_hint = "pip install edge-tts"
    error_status = 502

    def __init__(self) -> None:
        self._voices: list[dict] | None = None

    @staticmethod
    def installed() -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    def capabilities(self) -> dict:
        # normalize=False: Microsoft tự chuẩn hoá số/ngày/đơn vị phía server.
        return {"clone": False, "pitch": True, "emotion_tags": [], "mix": False, "normalize": False}

    async def voices(self) -> list[dict]:
        if self._voices is not None:
            return self._voices
        try:
            import edge_tts

            voices = []
            for v in await edge_tts.list_voices():
                loc = v.get("Locale", "")
                name = v["ShortName"]
                # Giữ giọng tiếng Việt + giọng đa ngôn ngữ (đọc được cả tiếng Việt)
                if loc.startswith("vi-") or "Multilingual" in name:
                    gender = "nữ" if v.get("Gender") == "Female" else "nam"
                    short = name.split("-")[-1].replace("Neural", "")
                    lang = "Việt" if loc.startswith("vi-") else loc
                    # region là phương ngữ (bac/trung/nam); edge không cho biết nên để trống.
                    voices.append({"id": name, "name": short, "label": f"{short} ({gender}, {lang})",
                                   "gender": gender, "region": "", "lang": loc})
            voices.sort(key=lambda x: (not x["id"].startswith("vi-"), x["label"]))
            self._voices = voices or FALLBACK
        except Exception:
            return FALLBACK  # không cache, để lần sau thử lại
        return self._voices

    async def _stream(self, text: str, voice: str, speed: int, pitch: int) -> bytes:
        import edge_tts

        comm = edge_tts.Communicate(text, voice, rate=f"{speed:+d}%", pitch=f"{pitch:+d}Hz")
        buf = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        if buf.tell() == 0:
            raise edge_tts.exceptions.NoAudioReceived("edge-tts không trả về audio (kiểm tra kết nối mạng).")
        return buf.getvalue()

    async def synthesize(self, text: str, voice: str, speed: int, **opts) -> tuple[bytes, str]:
        import edge_tts

        pitch = opts.get("pitch", 0)
        voice = voice or DEFAULT_VOICE
        try:
            return await self._stream(text, voice, speed, pitch), "audio/mpeg"
        except edge_tts.exceptions.NoAudioReceived:
            if pitch == 0:
                raise
        # Microsoft từ chối một số tổ hợp speed + pitch (vd +100% & +5Hz): thử lại không cao độ.
        opts.get("warnings", []).append(PITCH_DROPPED)
        return await self._stream(text, voice, speed, 0), "audio/mpeg"
