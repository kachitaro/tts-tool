"""Đọc văn bản truyện: từ điển phát âm + tách lời thoại cho giọng thứ hai (Phase 6b).

split_line(line) → [(kind, text)], kind "narr" (giọng kể) hoặc "dlg" (lời thoại). Nhận hai kiểu lời thoại:
  (a) đoạn trong ngoặc kép “…” / «…» / 「…」 / "…"  — chỉ coi là lời thoại nếu kết thúc bằng dấu câu (. ! ? … , ; :) hoặc có ≥ 4 từ,
      để thuật ngữ như  "Đấu Khí"  vẫn do giọng kể đọc. Ngoặc kép không đóng thì cả phần còn lại là lời kể.
  (b) dòng bắt đầu bằng gạch thoại "–", "—" (có hoặc không có khoảng trắng sau) hoặc "- " (gạch nối + khoảng trắng).
      Trong dòng, gạch ngăn cách " – " theo sau là chữ THƯỜNG là phần dẫn ("– Đi đâu? – hắn hỏi.") → giọng kể; lời thoại
      tiếp sau phần dẫn cũng bắt đầu bằng chữ thường ("– Tôi đi – anh nói – rồi sẽ về.") nên trạng thái đảo qua lại;
      gạch theo sau là chữ HOA là một câu thoại mới. Phần dẫn viết hoa ("– Đi đâu? – Hắn hỏi.") KHÔNG nhận ra được.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

import dialogue
import lexicon

_LEAD = re.compile(r"^\s*(?:[–—―‒]\s*|-\s+)")
_INNER = re.compile(r"\s+[–—―‒-]\s+")
_PAUSE_LINE = re.compile(r"^\[nghỉ [^\]]*\]$", re.IGNORECASE)
_OPEN, _CLOSE = "“«「『", "”»」』"
_ENDS = ".!?…,;:"
GAP_SAME_LINE = 0.15   # giây nghỉ thêm khi đổi giọng trong cùng một dòng
GAP_NEW_LINE = 0.30    # ... khi đổi giọng sang dòng khác


def _speakable(t: str) -> bool:
    return bool(re.search(r"\w", t))


def _is_dialogue(inner: str) -> bool:
    t = inner.strip()
    return _speakable(t) and (t[-1] in _ENDS or len(t.split()) >= 4)


def _merge(segs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for kind, text in segs:
        text = text.strip()
        if not _speakable(text):  # chỉ còn dấu câu / ngoặc: bỏ
            continue
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + " " + text)
        else:
            out.append((kind, text))
    return out


def _dash_line(rest: str) -> list[tuple[str, str]]:
    segs, kind = [], "dlg"
    for i, part in enumerate(_INNER.split(rest)):
        part = part.strip()
        if not part:
            continue
        if i:
            first = next((c for c in part if c.isalpha()), "")
            kind = ("narr" if kind == "dlg" else "dlg") if first.islower() else "dlg"
        segs.append((kind, part))
    return _merge(segs)


def _quote_line(s: str) -> list[tuple[str, str]]:
    segs, buf, i, n = [], [], 0, len(s)
    while i < n:
        c = s[i]
        if c in _OPEN or c == '"':
            close = next((k for k in range(i + 1, n) if s[k] in _CLOSE or s[k] == '"'), -1)
            if close < 0:  # ngoặc không đóng: phần còn lại là lời kể (bỏ dấu mở)
                buf.append(s[i + 1:])
                break
            inner = s[i + 1:close]
            if _is_dialogue(inner):
                segs.append(("narr", "".join(buf)))
                buf = []
                segs.append(("dlg", inner))
            else:
                buf.append(s[i:close + 1])  # thuật ngữ trong ngoặc: giữ nguyên cho giọng kể
            i = close + 1
            continue
        buf.append(c)
        i += 1
    segs.append(("narr", "".join(buf)))
    return _merge(segs)


def split_line(line: str) -> list[tuple[str, str]]:
    s = line.strip()
    if not s:
        return []
    if _PAUSE_LINE.match(s):
        return [("narr", s)]
    m = _LEAD.match(s)
    return _dash_line(s[m.end():]) if m else _quote_line(s)


def split_text(text: str) -> list[list[tuple[str, str]]]:
    """Mỗi dòng của văn bản → danh sách đoạn; dòng trống → danh sách rỗng (ngắt đoạn)."""
    return [split_line(l) for l in text.split("\n")]


@dataclass
class Run:
    kind: str
    text: str
    new_line: bool  # run này bắt đầu ở dòng khác với run trước


def runs(lines: list[list[tuple[str, str]]]) -> list[Run]:
    """Gộp các đoạn liên tiếp cùng giọng thành run (giữ ngắt dòng / ngắt đoạn bên trong run)."""
    out: list[Run] = []
    last_line, blank = -1, False
    for li, segs in enumerate(lines):
        if not segs:
            blank = True
            continue
        for kind, text in segs:
            if out and out[-1].kind == kind:
                sep = " " if li == last_line else ("\n\n" if blank else "\n")
                out[-1].text += sep + text
            else:
                out.append(Run(kind, text, bool(out) and li != last_line))
            last_line, blank = li, False
    return out


async def render(text: str, narr: tuple, dlg: tuple | None, speed: int, normalize: bool,
                 book_lex: list[dict] | None = None, global_lex: list[dict] | None = None,
                 warnings: list | None = None) -> np.ndarray:
    """Từ điển → (tuỳ chọn) tách lời thoại → sinh từng run bằng giọng tương ứng → ghép (WAV 48 kHz float32).
    narr / dlg = (engine, voice); dlg=None thì cả văn bản do giọng kể đọc."""
    warnings = warnings if warnings is not None else []
    text = lexicon.apply(text, book_lex, global_lex)
    pieces = runs(split_text(text)) if dlg else [Run("narr", text, False)]
    parts: list[np.ndarray] = []
    for k, r in enumerate(pieces):
        engine, voice = dlg if r.kind == "dlg" else narr
        plan = dialogue.make_plan(engine, r.text, normalize)
        if plan == [("text", "")]:
            continue
        if parts:
            parts.append(np.zeros(int((GAP_NEW_LINE if r.new_line else GAP_SAME_LINE) * dialogue.SR), dtype=np.float32))
        parts.append(await dialogue.render_plan(engine, voice, plan, speed, pitch=0, warnings=warnings))
    return np.concatenate(parts) if parts else np.zeros(int(0.4 * dialogue.SR), dtype=np.float32)
