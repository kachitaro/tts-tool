"""Đo khoảng lặng ở chỗ xuống đoạn văn / sau tiêu đề trong audio chương do hàng đợi sách nói dựng (VieNeu, chạy thật).

Dựng một chương thử (đoạn nhỏ để có mối nối giữa các đoạn cắt, cả ở ranh giới đoạn văn lẫn một đoạn văn dài bị cắt ở ranh giới
câu) bằng đúng đường của worker (bookq), rồi đo mọi khoảng lặng ≥ 0,35 s giữa chương và so với mức nghỉ cấu hình:
  - sau tiêu đề: title_pause_s (1,2 s)
  - giữa hai đoạn văn: paragraph_pause_s (0,6 s), kể cả mối nối giữa hai đoạn cắt
  - dấu ngăn cảnh [nghỉ 1,5s]: 1,5 s (thay, không cộng với nghỉ đoạn văn)
  - giữa hai mảnh của một đoạn văn dài bị cắt: KHÔNG có khoảng nghỉ đoạn văn
Hai biến thể: một giọng, và hai giọng (lời thoại bằng giọng thứ hai) để kiểm tra chỗ đổi giọng trùng chỗ xuống đoạn.

Chạy: .venv/bin/python tools/measure_pauses.py [--tol 0.1]   (thoát mã 1 nếu có chỗ lệch quá dung sai)
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import os
import shutil
import sys
import tempfile

os.environ["TTS_DATA_DIR"] = tempfile.mkdtemp(prefix="measure_pauses_")
atexit.register(shutil.rmtree, os.environ["TTS_DATA_DIR"], ignore_errors=True)  # dọn khi thoát
os.environ.setdefault("BOOK_SEGMENT_CHARS", "220")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from giongviet.books import jobs as bookq  # noqa: E402
from giongviet.books import narrate  # noqa: E402
from giongviet.books import store as books  # noqa: E402
from giongviet.engines.registry import ENGINES  # noqa: E402
from giongviet.speech import dialogue  # noqa: E402

# Một câu dài nhiều vế ngăn bằng dấu phẩy (không có dấu chấm giữa chừng): bị cắt ở ranh giới vế khi vượt giới hạn đoạn, mà không
# sinh khoảng lặng "hết câu" của model (khoảng lặng ≥ 0,35 s đo được ở đây chỉ có thể là chỗ xuống đoạn văn).
LONG = (
    "Gió thổi qua những mái nhà ngói đỏ, mang theo mùi khói bếp từ những gian bếp nhỏ, cùng tiếng gà gáy vọng lại từ xa, "
    "tiếng chó sủa lẫn trong sương sớm, tiếng trẻ con í ới gọi nhau ngoài ngõ, và cả tiếng mái chèo khua nhẹ ngoài bến."
)
PLAIN = f"""Chương 1: Thử nghỉ đoạn
Buổi sáng ở làng chài yên ắng, chỉ có tiếng sóng vỗ đều đặn vào bờ cát.
Ông Tư kiểm tra từng chiếc lưới, từng sợi dây neo trước khi ra khơi.
{LONG}
Cậu con trai út chạy theo sau, vừa đi vừa dụi mắt ngái ngủ.
***
Chiều xuống, cả hai cha con trở về với khoang thuyền đầy cá bạc.
Bà Tư đã đứng chờ sẵn ở đầu bến, tay cầm chiếc nón lá cũ.
Mâm cơm tối được dọn ra ngay trước hiên nhà, thơm mùi cá kho riềng.
Cả nhà quây quần bên nhau, nghe ông kể chuyện biển cả những ngày giông bão.
Đêm đó, trăng lên rất sáng, soi rõ từng con sóng bạc đầu ngoài khơi xa."""
DIALOGUE = """Chương 1: Thử nghỉ đoạn
Buổi sáng ở làng chài yên ắng, chỉ có tiếng sóng vỗ đều đặn vào bờ cát.
– Hôm nay mình đi xa không ba? – Cậu bé hỏi.
Ông Tư cười, nhìn về phía chân trời nơi mặt trời vừa nhô lên đỏ rực như quả cam.
"Biển hôm nay hiền, đi được tới bãi đá ngầm." Ông nói khẽ.
***
Chiều xuống, cả hai cha con trở về với khoang thuyền đầy cá bạc.
– Ba giỏi quá! – Cậu bé reo lên.
Bà Tư mỉm cười, đặt mâm cơm xuống giữa hiên nhà.
"Ăn đi con, cá còn nóng đấy." Bà nói.
Ông Tư gật đầu, rót cho mình một chén rượu nhỏ.
– Năm nay biển chiều lòng người lắm. – Ông nói.
Cậu bé ngồi nghe, mắt sáng lên như hai vì sao."""


def quiet_span(w: np.ndarray, center: int, db: float = -40.0) -> float:
    """Độ dài (giây) của khoảng lặng liên tục (cửa sổ 10 ms dưới -40 dB) chứa mẫu `center`."""
    win = int(0.01 * dialogue.SR)
    thr = 10 ** (db / 20)

    def quiet(i: int) -> bool:
        return bool(i >= 0 and i * win < len(w) and np.abs(w[i * win : (i + 1) * win]).mean() < thr)

    c = center // win
    if not quiet(c):
        return 0.0
    lo = hi = c
    while quiet(lo - 1):
        lo -= 1
    while quiet(hi + 1):
        hi += 1
    return (hi - lo + 1) * 0.01


async def run_variant(name: str, text: str, dialogue_voice: bool, tol: float) -> bool:
    engine = ENGINES["vieneu"]
    narr, dlg = (engine, "Hải Đăng"), ((engine, "Trúc Ly") if dialogue_voice else None)
    book = books.import_files(
        [("t.txt", text.encode())], f"Đo nghỉ {name}", "", {"engine": "vieneu", "voice": "Hải Đăng"}
    )
    bid = book["id"]
    settings = books.overrides(books.get(bid), {})
    books.confirm(bid, books.build(books.load_docs(bid), settings), settings)
    bookq.Q.start(lambda b: (narr, dlg))
    bookq.Q.enqueue(bid, [1])  # dựng bằng đúng worker: lấp cache từng mảnh + ra FLAC của chương
    while bookq.Q.status()["state"] != "idle":
        await asyncio.sleep(0.5)
    await bookq.Q.stop()
    b = books.get(bid)
    meta, body = books.chapter_text(bid, 1)
    assert meta["status"] == "done", meta
    paras = books.paragraphs(b, meta, body)
    segs = narrate.split_segments(paras, books.SEGMENT_CHARS)

    # dựng lại từ cache theo từng mảnh để biết vị trí mẫu của mọi chỗ nghỉ / mối nối (cùng cách ghép với worker)
    parts, pause_at, cont_joins, pos = [], [], [], 0
    for k in range(len(segs)):
        us = narrate.units(
            narrate.segment_text(segs, k), narr, dlg, b["normalize"], b.get("lexicon"), []
        )
        for i, u in enumerate(us):
            a = await narrate.render_unit(u, b["speed"])
            if u.pause:
                pause_at.append(
                    (
                        pos + len(a) // 2,
                        "mối nối đoạn cắt" if i == len(us) - 1 else "trong đoạn cắt",
                    )
                )
            parts.append(a)
            pos += len(a)
        if k + 1 < len(segs) and segs[k + 1].cont:
            cont_joins.append(pos)
    wav = np.concatenate(parts)
    flac, sr = sf.read(str(books.chapter_audio(bid, 1)), dtype="float32")
    assert abs(len(flac) - len(wav)) < 0.01 * sr, (
        len(flac) / sr,
        len(wav) / sr,
    )  # cùng audio với file worker đã ghi

    expected = [g for _, g in (p for p in paras[:-1])]
    ok = len(pause_at) == len(expected)
    print(
        f"\n== {name}: {len(segs)} đoạn cắt (cont: {[int(s.cont) for s in segs]}), {len(expected)} chỗ xuống đoạn / tiêu đề, audio {len(wav) / sr:.1f}s"
    )
    print(f"{'#':>2s} {'loại':18s} {'mong đợi':>9s} {'đo được':>8s} {'lệch':>7s}  kết quả")
    for i, (c, label) in enumerate(pause_at):
        want = expected[i] if i < len(expected) else float("nan")
        label = "tiêu đề" if i == 0 and b.get("read_title", True) else label
        got = quiet_span(wav, c)
        good = abs(got - want) <= tol
        ok &= bool(good)
        print(
            f"{i + 1:2d} {label:18s} {want:9.2f} {got:8.2f} {got - want:+7.2f}  {'OK' if good else 'LỆCH'}"
        )
    for c in cont_joins:  # giữa hai mảnh của một đoạn văn dài: không được có khoảng nghỉ đoạn văn
        got = quiet_span(wav, c)
        good = got < 0.4
        ok &= good
        print(
            f"   {'nối trong đoạn văn':18s} {'<0.40':>9s} {got:8.2f} {'':7s}  {'OK' if good else 'LỆCH'}"
        )
    return ok


async def main(tol: float) -> int:
    ok = await run_variant("một giọng", PLAIN, False, tol)
    ok &= await run_variant("hai giọng", DIALOGUE, True, tol)
    print(f"\nTất cả trong dung sai ±{tol:.2f}s." if ok else "\nCÓ CHỖ LỆCH quá dung sai.")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=0.1)
    sys.exit(asyncio.run(main(ap.parse_args().tol)))
