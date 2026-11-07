"""Đo tốc độ VieNeu trên máy này: fp32 so với int8, cùng 3 đoạn (~2.000 ký tự).

Mỗi precision chạy trong tiến trình riêng (VIENEU_PRECISION=...). Đo qua đúng đường của hàng đợi sách nói
(narrate.units → mảnh ≤ 500 ký tự → dialogue.synth_segment, bỏ qua cache). In: thời gian nạp model, RTF (giây chạy / giây audio),
ký tự/giây, và ước tính thời gian cho truyện hiện tại. Kèm kiểm tra encode_reference (speaker encoder + codec) có phụ thuộc
precision không: so sánh embedding và codes của cùng một file mẫu giữa các precision.

int8 chỉ đo nếu CPU có VNNI (avx512_vnni hoặc avx_vnni); không thì ghi "không hỗ trợ" (đặt --force-int8 để vẫn đo).
Kết quả lưu vào data/bench.json; tab Sách nói dùng số này để ước tính khi chưa có số đo thực tế từ hàng đợi.

Chạy: .venv/bin/python scripts/bench_vieneu.py [--book ID] [--precisions fp32,int8] [--no-save] [--force-int8]
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

VOICE = "Hải Đăng"
PASSAGES = [
    "Sáng sớm, sương còn đọng trên những mái nhà ngói đỏ của làng chài ven biển. Ông Tư đã ra bến từ lúc bốn giờ, lặng lẽ kiểm tra "
    "từng chiếc lưới, từng sợi dây neo. Gió đông thổi nhẹ, mang theo mùi muối mặn và tiếng sóng vỗ đều đặn vào bờ cát. Cậu con trai "
    "út chạy theo sau, vừa đi vừa dụi mắt. \"Ba ơi, hôm nay mình đi xa không?\" Ông Tư cười, không trả lời ngay. Ông nhìn về phía "
    "chân trời, nơi mặt trời vừa nhô lên đỏ rực như một quả cam chín, rồi mới khẽ nói rằng biển hôm nay hiền, đủ để đi đến tận "
    "bãi đá ngầm, nơi cá thu thường kéo về vào mùa này. Hai cha con xuống thuyền, đẩy mạnh một cái, chiếc ghe nhỏ trượt khỏi bờ cát "
    "và hòa vào làn nước xanh thẫm phía xa.",
    "Chuyến tàu từ Hà Nội vào Sài Gòn mất gần ba mươi tiếng, đi qua hơn bảy mươi ga lớn nhỏ. Lan ngồi cạnh cửa sổ, đầu tựa vào thành "
    "ghế, nhìn những cánh đồng lúa xanh lùi dần về phía sau. Trong túi xách của cô có một cuốn sổ cũ, vài tấm ảnh đã ngả màu và "
    "tám trăm nghìn đồng, tất cả những gì cô dành dụm được sau hai năm làm công nhân. Người đàn ông ngồi đối diện bắt chuyện, hỏi cô "
    "đi đâu, làm gì. Cô chỉ đáp ngắn gọn rằng mình đi tìm một người, và không biết người ấy còn nhớ đến mình hay không. Đến ga Vinh trời đổ mưa, những hạt nước lăn dài trên ô cửa kính, "
    "nhòe đi cả bóng dáng của thành phố đang trôi qua.",
    "Thiếu niên áo đen bước vào đại sảnh, ánh mắt lạnh lùng quét qua đám đông đang xì xào bàn tán. Không ai dám lên tiếng. Trên bục "
    "cao, vị trưởng lão râu tóc bạc phơ đặt chén trà xuống, chậm rãi nói rằng cuộc thi năm nay sẽ khác mọi năm, bởi phần thưởng "
    "là một viên đan dược quý hiếm mà cả tông môn đã cất giữ suốt ba trăm năm. Tiếng hít vào đồng loạt vang lên khắp sảnh. Thiếu niên "
    "vẫn đứng yên, tay siết chặt chuôi kiếm, trong lòng thầm nhủ rằng dù phải đánh đổi bất cứ thứ gì, hắn cũng nhất định phải có "
    "được viên đan dược ấy để cứu lấy mẹ mình. Tiếng chuông đồng ngân lên ba hồi dài, cuộc thi chính thức bắt đầu trong ánh mắt dõi theo của hàng nghìn người.",
]


from engines.vieneu import default_precision, has_vnni  # noqa: E402


def cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "?"


def child(precision: str, ref: Path, emb_out: Path) -> None:
    import asyncio

    import numpy as np
    import soundfile as sf

    import dialogue
    import narrate
    from engines.registry import ENGINES

    engine = ENGINES["vieneu"]
    t0 = time.perf_counter()
    tts = engine._get()
    load_s = time.perf_counter() - t0

    async def render(text: str):
        us = narrate.units(text, (engine, VOICE), None, True)
        wavs = [await narrate.render_unit(u, 0, [], True) for u in us]
        return np.concatenate(wavs), len(us)

    async def run():
        await render("Xin chào các bạn.")  # khởi động: lần gọi đầu có chi phí khởi tạo session
        rows, first = [], None
        for text in PASSAGES:
            t = time.perf_counter()
            wav, pieces = await render(text)
            wall = time.perf_counter() - t
            first = wav if first is None else first
            rows.append({"chars": len(text), "pieces": pieces, "wall": wall, "audio": len(wav) / dialogue.SR})
        return rows, first

    rows, first = asyncio.run(run())
    if not ref.is_file():  # file mẫu chung cho các precision: lấy từ lần đọc đầu của tiến trình đầu tiên
        sf.write(str(ref), first, dialogue.SR)
    emb, codes = tts.encode_reference(ref, denoise=False)
    np.savez(emb_out, emb=np.asarray(emb, dtype=np.float32), codes=np.asarray(codes if codes is not None else [], dtype=np.int64))
    print("RESULT " + json.dumps({"precision": precision, "load_s": load_s, "rows": rows, "sample_rate": getattr(tts, "sample_rate", None),
                                  "backend": getattr(tts, "backend", None)}))


def book_estimate(book_id: str | None) -> tuple[str, int] | None:
    import books

    items = books.list_books()
    if not items:
        return None
    b = next((x for x in items if x["id"] == book_id), None) if book_id else max(items, key=lambda x: x.get("created_at", ""))
    if b is None:
        raise SystemExit(f"Không có truyện '{book_id}'.")
    chs = books.list_chapters(b["id"]) if b.get("status") == "ready" else []
    todo = [c for c in chs if c.get("status") != "done"]
    return b["title"], sum(c["chars"] for c in todo), len(todo), len(chs)


def fmt(sec: float) -> str:
    return f"{sec / 3600:.1f} giờ" if sec >= 3600 else f"{sec / 60:.0f} phút" if sec >= 90 else f"{sec:.0f} giây"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child")
    ap.add_argument("--ref")
    ap.add_argument("--emb-out")
    ap.add_argument("--precisions", default="fp32,int8")
    ap.add_argument("--book")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--force-int8", action="store_true")
    a = ap.parse_args()
    if a.child:
        return child(a.child, Path(a.ref), Path(a.emb_out))

    import numpy as np

    tmp = Path(tempfile.mkdtemp(prefix="bench_vieneu_"))
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)   # dọn thư mục tạm khi thoát (kể cả lỗi)
    ref = tmp / "ref.wav"
    total_chars = sum(len(p) for p in PASSAGES)
    print(f"CPU: {cpu_name()} ({os.cpu_count()} luồng) · VNNI: {'có' if has_vnni() else 'không'} → precision mặc định của server: "
          f"{default_precision()} · 3 đoạn, {total_chars} ký tự\n")
    results: dict[str, dict] = {}
    embs: dict[str, dict] = {}
    independent = None
    for p in [x.strip() for x in a.precisions.split(",") if x.strip()]:
        if p == "int8" and not has_vnni() and not a.force_int8:
            print(f"{p:5s} không hỗ trợ: CPU không có VNNI (int8 sẽ bị méo tiếng). Dùng --force-int8 để vẫn đo.")
            results[p] = {"supported": False}
            continue
        env = {**os.environ, "VIENEU_PRECISION": p, "TTS_DATA_DIR": str(tmp / f"data_{p}")}
        print(f"… đo {p} (nạp model + khởi động + 3 đoạn)", flush=True)
        r = subprocess.run([sys.executable, __file__, "--child", p, "--ref", str(ref), "--emb-out", str(tmp / f"emb_{p}.npz")],
                           env=env, capture_output=True, text=True)
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
        if r.returncode or not line:
            print(f"{p:5s} LỖI: {(r.stderr or r.stdout)[-400:]}")
            results[p] = {"supported": True, "error": (r.stderr or r.stdout)[-400:]}
            continue
        d = json.loads(line[7:])
        wall, audio = sum(x["wall"] for x in d["rows"]), sum(x["audio"] for x in d["rows"])
        results[p] = {"supported": True, "chars_per_sec": round(total_chars / wall, 2), "rtf": round(wall / audio, 3), "load_s": round(d["load_s"], 1),
                      "wall_s": round(wall, 1), "audio_s": round(audio, 1), "sample_rate": d["sample_rate"], "backend": d["backend"],
                      "cpu": cpu_name(), "measured_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        with np.load(tmp / f"emb_{p}.npz") as z:
            embs[p] = {"emb": z["emb"], "codes": z["codes"]}

    print(f"\n{'precision':10s} {'nạp (s)':>8s} {'chạy (s)':>9s} {'audio (s)':>10s} {'RTF':>6s} {'ký tự/s':>8s}")
    for p, r in results.items():
        if "chars_per_sec" in r:
            print(f"{p:10s} {r['load_s']:8.1f} {r['wall_s']:9.1f} {r['audio_s']:10.1f} {r['rtf']:6.2f} {r['chars_per_sec']:8.2f}")
    if "fp32" in results and "int8" in results and "chars_per_sec" in results["int8"] and "chars_per_sec" in results["fp32"]:
        print(f"\nint8 nhanh gấp {results['int8']['chars_per_sec'] / results['fp32']['chars_per_sec']:.2f}x so với fp32 "
              f"(audio dài {results['int8']['audio_s']:.1f}s vs {results['fp32']['audio_s']:.1f}s; chất lượng phải nghe bằng tai)")

    if len(embs) >= 2:
        (pa, ea), (pb, eb) = list(embs.items())[:2]
        same_emb = np.array_equal(ea["emb"], eb["emb"])
        same_codes = np.array_equal(ea["codes"], eb["codes"])
        print(f"\nencode_reference của cùng một file mẫu, {pa} vs {pb}: speaker_emb "
              f"{'GIỐNG HỆT' if same_emb else 'khác (max |Δ| = %.3g)' % float(np.abs(ea['emb'] - eb['emb']).max())}, "
              f"codes {'GIỐNG HỆT' if same_codes else 'khác'}")
        independent = bool(same_emb and same_codes)

    if independent is not None:
        print("→ giọng nhân bản và giọng trộn (emb.<mode>.npz) " + ("giữ nguyên khi đổi precision, không cần tạo lại." if independent
              else "PHỤ THUỘC precision: cần tạo lại khi đổi."))
    est = book_estimate(a.book)
    if est and len(est) == 4:
        title, chars, todo, n = est
        print(f"\nTruyện '{title}': {todo}/{n} chương chưa xong, {chars:,} ký tự".replace(",", "."))
        for p, r in results.items():
            if "chars_per_sec" in r:
                print(f"  ước tính với {p}: {fmt(chars / r['chars_per_sec'])}")

    if not a.no_save:
        import library

        path = library.DATA / "bench.json"
        old = json.loads(path.read_text()) if path.is_file() else {}
        old.setdefault("vieneu", {}).update({p: r for p, r in results.items() if isinstance(r, dict) and "chars_per_sec" in r})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n→ đã lưu {path}")


if __name__ == "__main__":
    main()
