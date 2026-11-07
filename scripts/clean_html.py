#!/usr/bin/env python3
"""
Làm sạch file HTML chương truyện (đã lưu từ trình duyệt) thành văn bản .txt cho tab Sách nói.

Dùng:
    python clean_html.py chuong1.html chuong2.html ... -o truyen.txt
    python clean_html.py thu_muc_html/ -o truyen.txt

Xử lý:
  - Lấy nội dung từ khung chương (#chapter-c) đến hết trang, kể cả phần bị đẩy ra ngoài
    khung do HTML lỗi; bỏ script, style, khối quảng cáo (id/class chứa "ads").
  - <br>, <p> thành xuống dòng; xuống dòng trong mã nguồn HTML thành dấu cách.
  - Tiêu đề lấy từ <title>: bỏ tên trang, bỏ "Chương N:" bị lặp, chữ IN HOA thành chữ thường.
  - Khôi phục từ bị che bằng dấu * (h*m m**n → ham muốn) theo từ điển masked_words.txt.
  - Ghép số bị tách: "2. 513" → "2.513".
  - Dòng ngăn cảnh (=====, oOo, ***, ---) → "***" (tool đổi thành [nghỉ 1.5s]).
  - Gộp file theo số chương, xuất 1 file .txt có tiêu đề "Chương N: ..." để tool tự tách.
Chỉ dùng thư viện chuẩn của Python.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))  # chạy độc lập: logic nằm trong html_import.py (cùng module dùng cho tab Sách nói)

from html_import import (  # noqa: E402
    build_unmask_patterns,
    chapter_number,
    clean_body,
    clean_title,
    extract,
    load_masked_words,
)


# ─────────────────────────────────── main ────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Làm sạch HTML chương truyện thành .txt")
    ap.add_argument("inputs", nargs="+", help="file .html/.htm hoặc thư mục")
    ap.add_argument("-o", "--output", default="truyen.txt")
    ap.add_argument("--masked", default=str(HERE / "masked_words.txt"),
                    help="từ điển khôi phục từ bị che dấu *")
    args = ap.parse_args()

    files: list[Path] = []
    for item in args.inputs:
        p = Path(item)
        files += sorted(p.glob("*.htm*")) if p.is_dir() else [p]
    if not files:
        print("Không tìm thấy file HTML nào.", file=sys.stderr)
        return 1

    patterns = build_unmask_patterns(load_masked_words(Path(args.masked)))
    chapters, warnings = [], []
    for i, f in enumerate(files):
        raw = f.read_bytes().decode("utf-8", errors="replace")
        title_raw, body_raw, _ = extract(raw)
        title = clean_title(title_raw) or f.stem
        body, leftover = clean_body(body_raw, patterns)
        if len(body) < 200:
            warnings.append(f"{f.name}: nội dung rất ngắn ({len(body)} ký tự), kiểm tra lại")
        if leftover:
            warnings.append(f"{title}: còn từ bị che chưa khôi phục: {', '.join(leftover)}")
        no = chapter_number(title, f.name)
        chapters.append((float(no) if no is not None else 1e9 + i, title, body))

    chapters.sort(key=lambda c: c[0])
    seen, dupes = set(), []
    for no, title, _ in chapters:
        if no < 1e9 and no in seen:
            dupes.append(title)
        seen.add(no)
    if dupes:
        warnings.append("Trùng số chương: " + ", ".join(dupes))

    out = "\n\n\n".join(f"{t}\n\n{b}" for _, t, b in chapters) + "\n"
    Path(args.output).write_text(out, encoding="utf-8")

    print(f"✔ {len(chapters)} chương → {args.output} ({len(out):,} ký tự)")
    for w in warnings:
        print("⚠", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
