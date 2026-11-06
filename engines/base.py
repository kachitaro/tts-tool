from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Engine(ABC):
    """Một engine TTS. Thêm engine mới: tạo file trong engines/ và thêm 1 dòng vào registry.py."""

    id: str
    label: str            # tên ngắn hiện trên UI, ví dụ "Nhanh"
    description: str      # dòng phụ dưới tên, ví dụ "edge-tts · cần mạng"
    name: str             # tên hiển thị trong thông báo lỗi
    install_hint: str = ""  # lệnh cài khi installed() == False
    error_status: int = 500  # mã HTTP khi synthesize/voices lỗi
    local: bool = False      # chạy nặng trên máy người dùng (UI nhắc văn bản dài sẽ lâu)

    @staticmethod
    @abstractmethod
    def installed() -> bool: ...

    @property
    def loaded(self) -> bool:
        """Model đã nạp vào RAM chưa (engine nhẹ luôn True)."""
        return True

    @abstractmethod
    def capabilities(self) -> dict:
        """{"clone": bool, "pitch": bool, "emotion_tags": list[str], "mix": bool,
        "normalize": bool (engine cần chuẩn hoá văn bản phía ta; engine tự chuẩn hoá thì False)}"""

    @abstractmethod
    async def voices(self) -> list[dict]:
        """[{id, label, gender?, region?, tags?, description?, source?}]
        gender: "nam"|"nữ"; region: "bac"|"trung"|"nam"; source: "preset" (mặc định) | "clone"."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str, speed: int, **opts) -> tuple[bytes, str]:
        """Trả (bytes âm thanh, mime). speed: % (0 = 1x). `voice` dạng "lib:<id>" là giọng trong
        thư viện (engine có clone phải dùng library.ref_path(id)). opts tuỳ engine
        (pitch, ref_audio, warnings: list[str] để engine thêm cảnh báo, …);
        engine bỏ qua opts nó không hỗ trợ."""

    def prepare_reference(self, wav_path: Path) -> None:
        """Làm sạch file mẫu của giọng thư viện tại chỗ (đồng bộ, chạy trong thread).
        Mặc định không làm gì; engine có clone ghi đè nếu hỗ trợ denoise/encode trước."""

    def slider_to_alpha(self, slider: float) -> float:
        """Đổi vị trí thanh trượt UI (0..1, 1 = giọng A thuần) thành hệ số trộn thật. Mặc định giữ nguyên."""
        return slider

    async def mix(self, voice_a: str, voice_b: str, alpha: float, variant: str = "C") -> dict:
        """Chỉ khi capabilities()["mix"]. Trả dict mô tả giọng trộn (alpha=1 là A thuần):
        {speaker_emb, codes, codes_from (id giọng cho codes hoặc None), variant, alpha, mode, cache_name}.
        Dict này đưa thẳng vào synthesize(..., voice_data=dict); server lưu speaker_emb/codes vào
        <cache_name> trong thư mục giọng thư viện. Raise ValueError nếu không tìm thấy giọng."""
        raise NotImplementedError

    def unusable_reason(self, meta: dict) -> str | None:
        """Lý do một giọng thư viện của engine này hiện không dùng được (vd. "tạo ở mode x"), hoặc None."""
        return None

    def cache_tag(self) -> str:
        """Chuỗi cấu hình ảnh hưởng tới âm thanh (vd. mode của model); nằm trong khoá cache từng dòng hội thoại."""
        return ""
