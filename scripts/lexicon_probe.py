"""So sánh các cách giúp VieNeu ngắt nhịp quanh tên Hán Việt (Phase 6b).

Biến thể cho câu "Hắn nhìn Tiêu Viêm rồi cười." (và một câu có tên 4 tiếng):
  plain      : viết nguyên
  hyphen     : Tiêu-Viêm
  joined     : TiêuViêm
  comma      : "Hắn nhìn, Tiêu Viêm, rồi cười."
  pause_before / pause_after / pause_both : chèn [nghỉ 0.2s] (pipeline thẻ nghỉ của dự án)

Số đo (trung bình trên 3 seed): phoneme có đổi không; audio có giống từng byte với plain không (cùng seed);
tổng thời lượng; tổng và dài nhất của các khoảng lặng ≥ 80 ms nằm giữa câu; tỉ lệ f0 cuối đoạn trước chỗ ngắt
(so với f0 trung vị; < 1 là đang xuống giọng, tức nghe như hết câu).
Chạy: .venv/bin/python scripts/lexicon_probe.py   → in bảng + ghi out/lexicon_probe.json
Không có tai người ở đây: bảng chỉ cho biết cái gì đo được, quyết định nghe vẫn là của bạn.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

if "TTS_DATA_DIR" not in os.environ:
    os.environ["TTS_DATA_DIR"] = tempfile.mkdtemp(prefix="lexicon_probe_")
    atexit.register(shutil.rmtree, os.environ["TTS_DATA_DIR"], ignore_errors=True)   # dọn khi thoát
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dialogue  # noqa: E402
from engines.registry import ENGINES  # noqa: E402

VOICE = "Hải Đăng"
SEEDS = [0, 1, 2]
SR = dialogue.SR
SENTENCES = {
    "2 tiếng": ("Hắn nhìn {N} rồi cười.", "Tiêu Viêm"),
    "4 tiếng": ("Hắn đọc quyển {N} rất say mê.", "Đấu Phá Thương Khung"),
}


def variants(tpl: str, name: str) -> dict[str, str]:
    hy, jn = name.replace(" ", "-"), name.replace(" ", "")
    return {
        "plain": tpl.format(N=name),
        "hyphen": tpl.format(N=hy),
        "joined": tpl.format(N=jn),
        "comma": tpl.replace("{N}", name).replace(" " + name, ", " + name).replace(name + " ", name + ", "),
        "pause_before": tpl.format(N=f"[nghỉ 0.2s] {name}"),
        "pause_after": tpl.format(N=f"{name} [nghỉ 0.2s]"),
        "pause_both": tpl.format(N=f"[nghỉ 0.2s] {name} [nghỉ 0.2s]"),
    }


def silences(w: np.ndarray, min_s: float = 0.08, edge: float = 0.1, db: float = -40.0) -> list[tuple[float, float]]:
    win = int(0.01 * SR)
    n = len(w) // win
    quiet = np.abs(w[: n * win]).reshape(n, win).mean(1) < 10 ** (db / 20)
    out, start = [], None
    for i, q in enumerate(list(quiet) + [False]):
        if q and start is None:
            start = i
        elif not q and start is not None:
            s, e = start * 0.01, i * 0.01
            if e - s >= min_s and s > edge and e < n * 0.01 - edge:
                out.append((round(s, 2), round(e - s, 2)))
            start = None
    return out


def f0_end_ratio(w: np.ndarray, cut_s: float) -> float | None:
    """f0 trung vị của 250 ms cuối đoạn trước chỗ ngắt (cut_s) / f0 trung vị cả đoạn đó."""
    import librosa

    seg = w[: int(cut_s * SR)]
    if len(seg) < SR * 0.6:
        return None
    f0 = librosa.yin(seg, fmin=70, fmax=400, sr=SR, frame_length=4096, hop_length=480)
    rms = librosa.feature.rms(y=seg, frame_length=4096, hop_length=480)[0][: len(f0)]
    ok = rms > 0.3 * np.median(rms)
    t = np.arange(len(f0)) * 0.01
    tail = ok & (t > cut_s - 0.25) & (t < cut_s - 0.03)
    if tail.sum() < 5 or ok.sum() < 20:
        return None
    return float(np.median(f0[tail]) / np.median(f0[ok]))


async def render(engine, text: str, seed: int) -> np.ndarray:
    plan = dialogue.make_plan(engine, text, True)
    return await dialogue.render_plan(engine, VOICE, plan, 0, seed=seed, force=True)


async def main() -> None:
    engine = ENGINES["vieneu"]
    result: dict = {}
    for label, (tpl, name) in SENTENCES.items():
        rows = {}
        ref = {}
        for vname, text in variants(tpl, name).items():
            ph = dialogue.make_plan(engine, text, True)
            durs, sil_tot, sil_max, ratios, same = [], [], [], [], []
            for seed in SEEDS:
                w = await render(engine, text, seed)
                if vname == "plain":
                    ref[seed] = w
                durs.append(len(w) / SR)
                sl = silences(w)
                sil_tot.append(sum(l for _, l in sl))
                sil_max.append(max((l for _, l in sl), default=0.0))
                same.append(bool(len(w) == len(ref[seed]) and np.array_equal(w, ref[seed])))
                if sl:  # chỗ ngắt dài nhất (chỉ có nghĩa với biến thể có dấu phẩy / thẻ nghỉ)
                    s, l = max(sl, key=lambda x: x[1])
                    r = f0_end_ratio(w, s)
                    if r:
                        ratios.append(r)
            rows[vname] = {"text": text, "plan": [p[0] if p[0] == "pause" else "text" for p in ph], "dur": round(float(np.mean(durs)), 2),
                           "silence_sum": round(float(np.mean(sil_tot)), 2), "silence_max": round(float(np.mean(sil_max)), 2),
                           "f0_end_ratio": round(float(np.mean(ratios)), 3) if ratios else None, "identical_to_plain": all(same)}
        result[label] = rows
        print(f"\n== {label}: {tpl.format(N=name)}")
        print(f"{'biến thể':14s} {'dài(s)':>7s} {'Σ lặng':>7s} {'lặng max':>9s} {'f0 cuối/trung vị':>17s}  giống plain từng byte?")
        for v, r in rows.items():
            print(f"{v:14s} {r['dur']:7.2f} {r['silence_sum']:7.2f} {r['silence_max']:9.2f} {str(r['f0_end_ratio']):>17s}  {r['identical_to_plain']}")
    out = ROOT / "out" / "lexicon_probe.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {out}")


asyncio.run(main())
