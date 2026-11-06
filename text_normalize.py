"""Chuẩn hoá văn bản TRƯỚC khi đưa cho VieNeu — chỉ các trường hợp sea-g2p (bộ chuẩn hoá của VieNeu) xử lý chưa đúng.

sea-g2p đã tự đọc đúng: ngày/giờ (12/3/2025, 10h30), %, số thập phân và hàng nghìn, tiền (1.000.000đ, VND, €),
đơn vị (km, kg, MB, °C, m2), khoảng (10-15), số điện thoại, viết tắt (TP.HCM, UBND, TNHH, v.v., GS.TS), URL, email.
Phần còn thiếu do scripts/normalize_probe.py tìm ra nằm ở RULES bên dưới (mỗi quy tắc ghi rõ lý do).
Edge-tts không dùng module này: Microsoft tự chuẩn hoá phía server.
"""

from __future__ import annotations

import re

_NUM = r"\d+(?:[.,]\d+)*"


def _city(m: re.Match) -> str:
    # "TP. Hồ Chí Minh": sea-g2p đọc thành "thành phố." (dư dấu chấm). Chỉ đổi khi chữ sau viết hoa
    # để không đụng tới "TP.HCM" (đã đọc đúng) hay cuối câu.
    return "thành phố " + m.group(1) if m.group(1).isupper() else m.group(0)


RULES: list[tuple[re.Pattern, object]] = [
    # "50k" → "năm mươi ca" (sai); người Việt hiểu là nghìn.
    (re.compile(rf"(?<![\w.,])({_NUM})\s?[kK]\b(?!\w)"), r"\1 nghìn"),
    # "1.5 triệu" → "một chấm năm triệu" (sai); dấu chấm trước 1–2 chữ số rồi tới đơn vị lớn là dấu thập phân.
    (re.compile(r"(?<![\d.,])(\d{1,3})\.(\d{1,2})(?!\d)(?=\s*(?:triệu|tỷ|tỉ|nghìn|ngàn)\b)"), r"\1,\2"),
    (re.compile(r"\bTP\.\s+(\S)"), _city),
    # "km²" → "ki lô mét bình phương", "m³" → "mét lập phương" (sai, phải là "vuông"/"khối"); dạng "km2" đọc đúng.
    (re.compile(r"(?<![A-Za-z])(km|dm|cm|mm|m|ha)²"), r"\g<1>2"),
    (re.compile(r"(?<![A-Za-z])(km|dm|cm|mm|m)³"), r"\g<1>3"),
    # "$100", "100$", "USD" → sea-g2p đánh vần "u s d" (đọc theo kiểu tiếng Anh) thay vì "đô la".
    (re.compile(rf"\$\s*({_NUM})"), r"\1 đô la"),
    (re.compile(rf"({_NUM})\s*\$"), r"\1 đô la"),
    (re.compile(r"\bUSD\b"), "đô la Mỹ"),
]


def normalize(text: str) -> str:
    for pattern, repl in RULES:
        text = pattern.sub(repl, text)
    return text


# ── thẻ nghỉ có độ dài: [nghỉ 0.5s], [nghỉ 2s], [nghỉ 1,5s] (0.1–5 giây) ──
PAUSE_RE = re.compile(r"\[\s*nghỉ\s+(\d+(?:[.,]\d+)?)\s*s\s*\]", re.IGNORECASE)
PAUSE_MIN, PAUSE_MAX = 0.1, 5.0


def has_pause(text: str) -> bool:
    return bool(PAUSE_RE.search(text))


def split_pauses(text: str) -> list[tuple[str, object]]:
    """Tách văn bản tại các thẻ nghỉ: [("text", "..."), ("pause", giây), ...]. Raise ValueError nếu thẻ ngoài 0.1–5 giây."""
    out: list[tuple[str, object]] = []
    pos = 0
    for m in PAUSE_RE.finditer(text):
        sec = float(m.group(1).replace(",", "."))
        if not PAUSE_MIN <= sec <= PAUSE_MAX:
            raise ValueError(f"Thẻ nghỉ phải từ {PAUSE_MIN:g} đến {PAUSE_MAX:g} giây (gặp {m.group(0)}).")
        if m.start() > pos:
            out.append(("text", text[pos:m.start()]))
        out.append(("pause", sec))
        pos = m.end()
    if pos < len(text):
        out.append(("text", text[pos:]))
    return out
