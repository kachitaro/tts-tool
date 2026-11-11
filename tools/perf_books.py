"""Đo hiệu năng nhập / xem trước / xác nhận với truyện giả ~20 MB, ~1.500 chương.

Chạy: .venv/bin/python tools/perf_books.py [--mb 20] [--chapters 1500]
Truyện giả có đủ thứ mà bộ làm sạch phải xử lý: dòng URL, dòng "nguồn:", dấu ngăn cảnh, dòng bị ngắt giữa câu,
ngoặc kép cong, dấu ba chấm, và dòng quảng cáo lặp ở mọi chương.
"""

from __future__ import annotations

import argparse
import atexit
import os
import random
import shutil
import tempfile
import time

if "TTS_DATA_DIR" not in os.environ:
    os.environ["TTS_DATA_DIR"] = tempfile.mkdtemp(prefix="perf_books_")
    atexit.register(shutil.rmtree, os.environ["TTS_DATA_DIR"], ignore_errors=True)  # dọn khi thoát
from giongviet.books import store as books  # noqa: E402

WORDS = (
    "hắn đứng lặng người nhìn về phía xa trong lòng dâng lên một cảm giác khó tả Tiêu Viêm cười nhạt đấu khí cuồn cuộn "
    "thiếu niên áo đen bước vào đại sảnh ánh mắt sắc lạnh nói rằng ngươi không thể nào thắng được ta"
).split()


def make_story(mb: float, chapters: int) -> bytes:
    rnd = random.Random(1)
    per = int(mb * 1024 * 1024 / chapters)
    out = ["Tên truyện: Đấu Phá Giả", "Nguồn: truyenfull.vn", ""]
    for n in range(1, chapters + 1):
        out.append(f"Chương {n}: Tiêu đề số {n}")
        size = 0
        while size < per:
            r = rnd.random()
            if r < 0.01:
                line = "Đọc truyện tại https://truyenfull.vn/dau-pha"
            elif r < 0.02:
                line = "***"
            elif r < 0.05:
                line = "Quảng cáo lặp lại ở mọi trang của web truyện này nhé các bạn."
            else:
                words = [rnd.choice(WORDS) for _ in range(rnd.randint(12, 30))]
                words[0] = words[0].capitalize()
                line = " ".join(words) + rnd.choice([".", "...", "!", "?", ".”", ","])
                if rnd.random() < 0.1:
                    line = "“" + line
                if line.endswith(","):  # dòng bị ngắt giữa câu: dòng sau bắt đầu bằng chữ thường
                    out.append(line)
                    size += len(line.encode()) + 1
                    line = " ".join(rnd.choice(WORDS) for _ in range(8)) + "."
            out.append(line)
            size += len(line.encode()) + 1
        out.append("")
    return "\n".join(out).encode("utf-8")


def timed(label: str, fn):
    t = time.perf_counter()
    r = fn()
    print(f"{label:48s} {time.perf_counter() - t:7.2f} s")
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mb", type=float, default=20)
    ap.add_argument("--chapters", type=int, default=1500)
    a = ap.parse_args()
    data = timed(
        f"tạo file giả {a.mb:g} MB / {a.chapters} chương", lambda: make_story(a.mb, a.chapters)
    )
    print(f"  kích thước thật: {len(data) / 2**20:.1f} MB")
    book = timed(
        "nhập (ghi source + dò encoding + gợi ý chế độ)",
        lambda: books.import_files([("story.txt", data)], "Perf", "", {}),
    )
    bid = book["id"]
    docs = timed("  đọc + giải mã nguồn (load_docs)", lambda: books.load_docs(bid))
    settings = books.overrides(books.get(bid), {})
    built = timed("XEM TRƯỚC: tách chương + làm sạch (build)", lambda: books.build(docs, settings))
    summ = timed("  tóm tắt danh sách chương (summarize)", lambda: books.summarize(built))
    print(f"  {len(summ)} chương, stats={built['stats']}")
    docs = books.load_docs(bid)
    timed(
        "XEM TRƯỚC toàn bộ (load_docs + build + summarize)",
        lambda: books.summarize(books.build(docs, settings)),
    )
    timed(
        "XÁC NHẬN (build + ghi chapters/)",
        lambda: books.confirm(bid, books.build(books.load_docs(bid), settings), settings),
    )
    ch = timed("đọc một chương", lambda: books.chapter_text(bid, 700))
    print(f"  chương 700: {len(ch[1])} ký tự")


if __name__ == "__main__":
    main()
