"""Thử trộn giọng VieNeu (Phase 3a-bis): nội suy speaker_emb của hai giọng preset.

  A) emb = alpha*emb_a + (1-alpha)*emb_b          , codes của giọng trọng số lớn hơn
  B) cùng emb như A                                , use_ref_codes=False (chỉ dựa vào embedding)
  C) slerp trên hướng + nội suy norm               , codes như A
       u   = slerp(â, b̂, alpha)     (â = emb_a/|emb_a|)
       emb = u * (alpha*|emb_a| + (1-alpha)*|emb_b|)

alpha=1 là giọng A thuần, alpha=0 là giọng B thuần. Hoà ở alpha=0.5 (biến thể A, C):
codes lấy của giọng có norm embedding lớn hơn.

Mỗi điểm chạy nhiều seed. Số đo chính: "A − B" = cos(emb_sinh_ra, emb_a) − cos(emb_sinh_ra, emb_b),
trong đó emb_sinh_ra là encode_reference của chính audio vừa sinh.

Chạy: .venv/bin/python scripts/mix_experiment.py [--pair "Adam bựa,Trúc Ly"] [--seeds 3]
Kết quả: out/mix/<cặp>/<biến thể>_<alpha>_s<seed>.wav, out/mix/index.html, out/mix/metrics.json
"""

from __future__ import annotations

import argparse
import html
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engines.registry import ENGINES  # noqa: E402
from engines.vieneu import codes_owner, make_embedding  # noqa: E402

TEXT = "Xin chào, hôm nay trời đẹp quá, mình đi dạo nhé."
ALPHAS = [0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0]
VARIANTS = ("A", "B", "C")
VERIFY_S = [0.2, 0.4, 0.6, 0.8]  # điểm slider dùng để kiểm chứng hàm ánh xạ bằng audio thật
OUT = ROOT / "out" / "mix"


def seed_all(s: int) -> None:
    random.seed(s)
    np.random.seed(s)  # vieneu lấy mẫu bằng np.random toàn cục


def pick_pairs(tts) -> list[tuple[str, str, str]]:
    """(nhãn, A, B): khác giới cùng miền Bắc; cùng giới (nữ) khác miền Bắc/Trung."""
    from engines.vieneu import _voice_entry

    voices = [_voice_entry(vid, label, tts._preset_voices[vid]) for label, vid in tts.list_preset_voices()]
    first = lambda g, r: next(v["id"] for v in voices if v["gender"] == g and v["region"] == r)  # noqa: E731
    return [
        ("khac-gioi_nam-nu", first("nam", "bac"), first("nữ", "bac")),
        ("cung-gioi_nu_bac-trung", first("nữ", "bac"), first("nữ", "trung")),
    ]


def cos(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.reshape(-1), b.reshape(-1)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def audio_stats(wav: np.ndarray, sr: int) -> dict:
    return {
        "seconds": round(len(wav) / sr, 2),
        "peak": round(float(np.abs(wav).max()), 3) if wav.size else 0.0,
        "clip_frac": round(float((np.abs(wav) >= 0.999).mean()), 5) if wav.size else 0.0,
        "finite": bool(np.isfinite(wav).all()),
    }


def monotone(y: np.ndarray) -> np.ndarray:
    return np.maximum.accumulate(y)


def normalized_curve(means: list[float]) -> np.ndarray:
    """Đường cong "A − B" đã co về 0..1 theo hai đầu mút, ép tăng đơn điệu (để nghịch đảo được)."""
    y = np.asarray(means, dtype=float)
    y = (y - y[0]) / (y[-1] - y[0])
    return monotone(y)


def inverse_map(curve: np.ndarray, s: np.ndarray) -> np.ndarray:
    """alpha cần dùng để "A − B" chuẩn hoá đạt giá trị s. np.interp cần x tăng ngặt → dùng khử trùng lặp nhỏ."""
    x = curve + np.arange(len(curve)) * 1e-9
    return np.interp(s, x, ALPHAS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", action="append", help='"A,B" (tên giọng preset); lặp lại được, mặc định tự chọn 2 cặp')
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    seeds = list(range(args.seeds))

    engine = ENGINES["vieneu"]
    tts = engine._get()
    sr = tts.sample_rate
    pairs = ([(f"{i + 1}_{a}-{b}".replace(" ", "_"), a, b) for i, (a, b) in enumerate(p.split(",") for p in args.pair)]
             if args.pair else pick_pairs(tts))
    presets = tts._preset_voices
    shutil.rmtree(OUT, ignore_errors=True)

    def infer(emb, codes, use_codes, seed):
        seed_all(seed)
        wav = tts.infer(TEXT, voice={"speaker_emb": emb, "codes": codes}, use_ref_codes=use_codes)
        return np.asarray(wav, dtype=np.float32)

    def measure(d: Path, name: str, emb, codes, use_codes, seed, ea, eb) -> dict:
        rec: dict = {"file": name}
        try:
            wav = infer(emb, codes, use_codes, seed)
            sf.write(d / name, wav, sr)
            rec.update(audio_stats(wav, sr))
            g, _ = tts.encode_reference(d / name, denoise=False)
            rec["cos_a"], rec["cos_b"] = cos(g, ea), cos(g, eb)
            rec["a_minus_b"] = rec["cos_a"] - rec["cos_b"]
        except Exception as e:  # ghi lại thay vì dừng cả thí nghiệm
            rec["error"] = f"{type(e).__name__}: {e}"
        return rec

    metrics: dict = {"text": TEXT, "alphas": ALPHAS, "seeds": seeds, "variants": VARIANTS, "pairs": {}}
    for label, a, b in pairs:
        pa, pb = presets[a], presets[b]
        ea, eb = pa["speaker_emb"].astype(np.float32), pb["speaker_emb"].astype(np.float32)
        na, nb = float(np.linalg.norm(ea)), float(np.linalg.norm(eb))
        d = OUT / label
        d.mkdir(parents=True, exist_ok=True)
        pm: dict = {"a": a, "b": b, "cos_ab": round(cos(ea, eb), 4), "norm_a": round(na, 4), "norm_b": round(nb, 4),
                    "angle_deg": round(float(np.degrees(np.arccos(cos(ea, eb)))), 1), "cells": {}}
        for tag, p in (("goc-A", pa), ("goc-B", pb)):
            sf.write(d / f"{tag}.wav", infer(p["speaker_emb"], p["codes"], True, 0), sr)
        for variant in VARIANTS:
            for alpha in ALPHAS:
                emb = make_embedding(variant, ea, eb, alpha)
                owner = codes_owner(alpha, na, nb)
                codes = (pa if owner == "a" else pb)["codes"]
                runs = [measure(d, f"{variant}_{alpha}_s{s}.wav", emb, codes, variant != "B", s, ea, eb) for s in seeds]
                ok = [r for r in runs if "error" not in r]
                vals = [r["a_minus_b"] for r in ok]
                cell = {
                    "mixed_norm": round(float(np.linalg.norm(emb)), 3),
                    "codes_from": None if variant == "B" else (a if owner == "a" else b),
                    "mean": float(np.mean(vals)) if vals else None,
                    "std": float(np.std(vals)) if vals else None,
                    "cos_a": float(np.mean([r["cos_a"] for r in ok])) if ok else None,
                    "cos_b": float(np.mean([r["cos_b"] for r in ok])) if ok else None,
                    "per_seed": [round(v, 4) for v in vals],
                    "errors": [r["error"] for r in runs if "error" in r],
                    "bad_audio": [r["file"] for r in ok if not r["finite"] or r["clip_frac"] >= 0.001],
                    "seconds": [min(r["seconds"] for r in ok), max(r["seconds"] for r in ok)] if ok else None,
                    "file0": f"{variant}_{alpha}_s{seeds[0]}.wav",
                }
                pm["cells"][f"{variant}_{alpha}"] = cell
                print(f"{label:24s} {variant} a={alpha:<4} " + (f"A-B = {cell['mean']:+.3f} ± {cell['std']:.3f}"
                      if vals else cell["errors"][:1]))
        metrics["pairs"][label] = pm

    # ── hàm ánh xạ slider → alpha ──
    def curve(pm, v):
        return [pm["cells"][f"{v}_{al}"]["mean"] for al in ALPHAS]

    mapping: dict = {}
    for v in VARIANTS:
        curves = {l: normalized_curve(curve(pm, v)) for l, pm in metrics["pairs"].items()}
        shared = np.mean(list(curves.values()), axis=0)
        grid = np.linspace(0, 1, 11)
        amap = inverse_map(shared, grid)
        resid = {l: float(np.max(np.abs(np.interp(amap, ALPHAS, c) - grid))) for l, c in curves.items()}
        raw_dev = {l: float(np.max(np.abs(c - np.array(ALPHAS)))) for l, c in curves.items()}
        mapping[v] = {
            "normalized_curve_shared": [round(float(x), 3) for x in shared],
            "slider_to_alpha": {f"{s:.1f}": round(float(al), 3) for s, al in zip(grid, amap)},
            "max_nonlinearity_without_map": {l: round(x, 3) for l, x in raw_dev.items()},
            "max_nonlinearity_with_map": {l: round(x, 3) for l, x in resid.items()},
            "monotonic_raw": {l: bool(np.all(np.diff([pm["cells"][f"{v}_{al}"]["mean"] for al in ALPHAS]) > 0))
                              for l, pm in metrics["pairs"].items()},
            "mean_std": round(float(np.mean([c["std"] for pm in metrics["pairs"].values() for k, c in pm["cells"].items()
                                              if k.startswith(v + "_") and c["std"] is not None])), 4),
        }
    best = min(VARIANTS, key=lambda v: np.mean(list(mapping[v]["max_nonlinearity_without_map"].values())))
    metrics["mapping"], metrics["best_by_linearity"] = mapping, best

    # ── kiểm chứng bằng audio thật: slider s → alpha(s) → A−B chuẩn hoá có ≈ s không? ──
    amap_best = [mapping[best]["slider_to_alpha"][f"{s:.1f}"] for s in np.linspace(0, 1, 11)]
    metrics["verify"] = {"variant": best, "points": {}}
    for label, a, b in pairs:
        pa, pb = presets[a], presets[b]
        ea, eb = pa["speaker_emb"].astype(np.float32), pb["speaker_emb"].astype(np.float32)
        na, nb = float(np.linalg.norm(ea)), float(np.linalg.norm(eb))
        lo = metrics["pairs"][label]["cells"][f"{best}_0.0"]["mean"]
        hi = metrics["pairs"][label]["cells"][f"{best}_1.0"]["mean"]
        d = OUT / label
        out = {}
        for s in VERIFY_S:
            alpha = float(np.interp(s, np.linspace(0, 1, 11), amap_best))
            emb = make_embedding(best, ea, eb, alpha)
            owner = codes_owner(alpha, na, nb)
            runs = [measure(d, f"verify_{best}_s{s}_seed{sd}.wav", emb, (pa if owner == "a" else pb)["codes"],
                            best != "B", sd, ea, eb) for sd in seeds]
            vals = [(r["a_minus_b"] - lo) / (hi - lo) for r in runs if "error" not in r]
            out[f"{s}"] = {"alpha": round(alpha, 3), "achieved_mean": round(float(np.mean(vals)), 3),
                           "achieved_std": round(float(np.std(vals)), 3)}
            print(f"verify {label:24s} s={s} alpha={alpha:.3f} → {np.mean(vals):.3f} ± {np.std(vals):.3f}")
        metrics["verify"]["points"][label] = out

    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    write_index(metrics)
    print(f"\nTốt nhất theo độ tuyến tính: {best}\nXong → {OUT / 'index.html'}")


def write_index(m: dict) -> None:
    rows = [f"<h1>Thử trộn giọng VieNeu (3a-bis)</h1><p>Câu: <b>{html.escape(m['text'])}</b></p>",
            "<p>Hàng = alpha (1 là A thuần, 0 là B thuần). Mỗi ô phát seed 0; số dưới ô là "
            "<b>A − B</b> trung bình ± độ lệch chuẩn trên "
            f"{len(m['seeds'])} seed (âm = giống B, dương = giống A). "
            "A: nội suy tuyến tính + codes; B: nội suy tuyến tính, không codes; "
            "C: slerp hướng + nội suy norm + codes. Hoà ở 0.5: codes của giọng có norm lớn hơn.</p>"]
    for label, p in m["pairs"].items():
        rows.append(f"<h2>{html.escape(label)}: A = {html.escape(p['a'])}, B = {html.escape(p['b'])} "
                    f"<small>(góc giữa 2 emb gốc {p['angle_deg']}°, norm {p['norm_a']} / {p['norm_b']})</small></h2>")
        rows.append(f"<p>Giọng gốc: A <audio controls src='{label}/goc-A.wav'></audio> "
                    f"B <audio controls src='{label}/goc-B.wav'></audio></p>")
        rows.append("<table><tr><th>alpha</th>" + "".join(f"<th>biến thể {v}</th>" for v in m["variants"]) + "</tr>")
        for alpha in m["alphas"]:
            cells = []
            for v in m["variants"]:
                c = p["cells"][f"{v}_{alpha}"]
                if c["mean"] is None:
                    cells.append(f"<td>{html.escape(str(c['errors'][:1]))}</td>")
                    continue
                flag = " <b style='color:#c00'>méo?</b>" if c["bad_audio"] else ""
                cells.append(f"<td><audio controls src='{label}/{c['file0']}'></audio><br>"
                             f"<small>A−B {c['mean']:+.2f} ± {c['std']:.2f} · norm {c['mixed_norm']}{flag}</small></td>")
            rows.append(f"<tr><th>{alpha}</th>{''.join(cells)}</tr>")
        rows.append("</table>")
    (OUT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Trộn giọng VieNeu</title>"
        "<style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px;vertical-align:top}"
        "audio{width:210px}small{color:#555}</style>" + "".join(rows), encoding="utf-8")


if __name__ == "__main__":
    main()
