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
