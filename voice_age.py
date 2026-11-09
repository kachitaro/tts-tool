"""Nhãn độ tuổi của giọng: "tre" | "trung_nien" | "gia" | "" (chưa rõ).

- Giọng thư viện (ghi âm, pha): lưu ở meta.json của giọng (library.py, trường `age`), người dùng chọn khi thêm / đổi tên.
- Giọng có sẵn (preset): tool chỉ GỢI Ý theo phong cách (`suggest`), người dùng chỉnh được; lựa chọn lưu ở data/voice_ages.json
  (khoá "<engine>:<id>"). Gợi ý chỉ dựa vào chữ mô tả của giọng, KHÔNG phải nghe giọng: lão ông / lão bà phải do người dùng gắn
  hoặc tạo từ file ghi âm / pha giọng.
"""

from __future__ import annotations

import json
import threading

import library

AGES = ("", "tre", "trung_nien", "gia")
LABELS = {"tre": "trẻ", "trung_nien": "trung niên", "gia": "già"}
PATH = library.DATA / "voice_ages.json"
_lock = threading.Lock()


class AgeError(ValueError):
    pass


def check(age: str) -> str:
    if age not in AGES:
        raise AgeError("Độ tuổi phải là 'tre', 'trung_nien', 'gia' hoặc để trống.")
    return age


def group_of(years: int) -> str:
    """Số tuổi → nhóm: trẻ < 25, trung niên 25–55, già > 55."""
    return "tre" if years < 25 else "trung_nien" if years <= 55 else "gia"


def suggest(voice: dict) -> str:
    """Gợi ý theo phong cách trong mô tả / thẻ của giọng có sẵn: "tự nhiên" → trẻ; "kể chuyện" / "đọc truyện" / "tin tức" → trung niên."""
    text = " ".join(
        [str(voice.get("description") or ""), *map(str, voice.get("tags") or [])]
    ).lower()
    if any(k in text for k in ("kể chuyện", "đọc truyện", "tin tức")):
        return "trung_nien"
    if "tự nhiên" in text:
        return "tre"
    return ""


def load() -> dict[str, str]:
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and v in AGES and v}


def set_preset(engine: str, voice: str, age: str) -> None:
    check(age)
    with _lock:
        cur = load()
        if age:
            cur[f"{engine}:{voice}"] = age
        else:
            cur.pop(f"{engine}:{voice}", None)
        PATH.parent.mkdir(parents=True, exist_ok=True)
        library._write_json(PATH, cur)


def annotate_preset(engine: str, voice: dict, saved: dict[str, str]) -> dict:
    """Thêm `age` và `age_source` ("user" | "suggested" | "") cho giọng có sẵn."""
    k = f"{engine}:{voice['id']}"
    if k in saved:
        return {**voice, "age": saved[k], "age_source": "user"}
    s = suggest(voice)
    return {**voice, "age": s, "age_source": "suggested" if s else ""}
