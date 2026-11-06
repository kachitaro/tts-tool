"""Đọc văn bản truyện: từ điển phát âm + tách lời thoại cho giọng thứ hai (Phase 6b).

split_line(line) → [(kind, text)], kind "narr" (giọng kể) hoặc "dlg" (lời thoại). Nhận hai kiểu lời thoại:
  (a) đoạn trong ngoặc kép “…” / «…» / 「…」 / "…"  — chỉ coi là lời thoại nếu kết thúc bằng dấu câu (. ! ? … , ; :) hoặc có ≥ 4 từ,
      để thuật ngữ như  "Đấu Khí"  vẫn do giọng kể đọc. Ngoặc kép không đóng thì cả phần còn lại là lời kể.
  (b) dòng bắt đầu bằng gạch thoại "–", "—" (có hoặc không có khoảng trắng sau) hoặc "- " (gạch nối + khoảng trắng).
      Trong dòng, gạch ngăn cách " – " theo sau là chữ THƯỜNG là phần dẫn ("– Đi đâu? – hắn hỏi.") → giọng kể; lời thoại
      tiếp sau phần dẫn cũng bắt đầu bằng chữ thường ("– Tôi đi – anh nói – rồi sẽ về.") nên trạng thái đảo qua lại;
      gạch theo sau là chữ HOA là một câu thoại mới, trừ khi nó là phần dẫn: ≤ 60 ký tự và có một động từ nói
      (config/speech_verbs.txt) trong 4 tiếng đầu ("– Đi đâu? – Hắn hỏi." → "Hắn hỏi." do giọng kể).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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
# Hiệu chỉnh đo thực tế (scripts/measure_pauses.py, VieNeu): sau khi trừ lặng đệm, khoảng lặng đo được vẫn dài hơn thẻ nghỉ
# trung bình ~0,03 s ở đường đọc sách nói, nên trừ thêm phần này để xuống đoạn / tiêu đề đo ra đúng giây cấu hình.
PAUSE_TRIM_S = 0.03


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


SPEECH_VERBS_PATH = Path(__file__).resolve().parent / "config" / "speech_verbs.txt"
MAX_TAG_CHARS = 60     # phần dẫn viết hoa dài hơn ngần này không coi là phần dẫn
TAG_WINDOW = 4         # động từ nói phải nằm trong ngần này tiếng đầu
_verbs_cache: tuple[float, re.Pattern | None] = (-1.0, None)


def _speech_verbs() -> re.Pattern | None:
    """Biên dịch config/speech_verbs.txt (đọc lại khi file đổi)."""
    global _verbs_cache
    try:
        mtime = SPEECH_VERBS_PATH.stat().st_mtime
    except OSError:
        return None
    if mtime != _verbs_cache[0]:
        words = [l.split("#")[0].strip().lower() for l in SPEECH_VERBS_PATH.read_text(encoding="utf-8").splitlines()]
        words = sorted({w for w in words if w}, key=len, reverse=True)
        rx = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in words) + r")(?!\w)") if words else None
        _verbs_cache = (mtime, rx)
    return _verbs_cache[1]


def _is_tag(part: str) -> bool:
    """Phần dẫn viết hoa ("Hắn hỏi.", "Nàng thì thầm, giọng run run."): ngắn và có động từ nói trong 4 tiếng đầu."""
    rx = _speech_verbs()
    if rx is None or len(part) > MAX_TAG_CHARS:
        return False
    head = " ".join(part.split()[:TAG_WINDOW]).lower()
    return bool(rx.search(head))


def _dash_line(rest: str) -> list[tuple[str, str]]:
    segs, kind = [], "dlg"
    for i, part in enumerate(_INNER.split(rest)):
        part = part.strip()
        if not part:
            continue
        if i:
            first = next((c for c in part if c.isalpha()), "")
            if first.islower():
                kind = "narr" if kind == "dlg" else "dlg"
            else:  # chữ hoa: câu thoại mới, trừ khi là phần dẫn ngắn có động từ nói đứng sau một câu thoại
                kind = "narr" if kind == "dlg" and _is_tag(part) else "dlg"
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


PIECE_CHARS = 256   # mỗi lần gọi model đọc tối đa ngần này ký tự (đã chuẩn hoá; = max_chars mà VieNeu tự chia chunk) nên tương tác chỉ chờ một mảnh
_SENT = re.compile(r"(?<=[.!?…])\s+")


def split_pieces(text: str, limit: int = PIECE_CHARS) -> list[str]:
    """Chia văn bản đã chuẩn hoá thành mảnh ≤ limit ký tự: gộp câu liên tiếp cho tới khi vượt limit; câu dài hơn limit
    cắt ở dấu phẩy/chấm phẩy/hai chấm gần cuối nhất, không có thì ở khoảng trắng."""
    out: list[str] = []
    cur = ""
    for sent in _SENT.split(text.strip()):
        while len(sent) > limit:
            cut = max((sent.rfind(c, 0, limit) for c in ",;:"), default=-1) + 1 or sent.rfind(" ", 0, limit) + 1 or limit
            if cur:
                out.append(cur)
                cur = ""
            out.append(sent[:cut].strip())
            sent = sent[cut:].strip()
        if cur and len(cur) + 1 + len(sent) > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return [p for p in out if p]


@dataclass
class Segment:
    """Đoạn của hàng đợi (≤ limit ký tự). paras: [[văn bản đoạn văn, giây nghỉ sau]]. cont=True: đoạn này tiếp tục một đoạn văn
    dài đã bị cắt ở ranh giới câu (mối nối giữa hai đoạn như vậy không chèn khoảng nghỉ đoạn văn)."""
    paras: list
    cont: bool = False


def split_segments(paras: list[list], limit: int) -> list[Segment]:
    """Chia chương thành đoạn ≤ limit ký tự: chỉ cắt giữa các đoạn văn (gộp nguyên đoạn văn cho tới khi đầy). Một đoạn văn dài
    hơn limit mới bị cắt, ở ranh giới câu, mỗi mảnh là một đoạn riêng."""
    segs: list[Segment] = []
    cur: list = []
    size = 0

    def flush() -> None:
        nonlocal cur, size
        if cur:
            segs.append(Segment(cur))
        cur, size = [], 0

    for text, gap in paras:
        if len(text) > limit:
            flush()
            pieces = split_pieces(text, limit)
            for j, piece in enumerate(pieces):
                segs.append(Segment([[piece, gap if j == len(pieces) - 1 else 0]], cont=j > 0))
            continue
        if cur and size + len(text) + 1 > limit:
            flush()
        cur.append([text, gap])
        size += len(text) + 1
    flush()
    return segs


def _tag(sec: float) -> str:
    return f"[nghỉ {sec:g}s]"


def join_paras(paras: list[list]) -> str:
    """Các đoạn văn → văn bản có thẻ nghỉ giữa chúng (giây nghỉ = 0 thì không chèn thẻ). Không có thẻ sau đoạn cuối."""
    parts: list[str] = []
    for i, (text, gap) in enumerate(paras):
        parts.append(text)
        if gap and i < len(paras) - 1:
            parts.append(_tag(gap))
    return "\n".join(parts)


def segment_text(segs: list[Segment], k: int) -> str:
    """Văn bản đưa cho model của đoạn k. Mối nối với đoạn k+1 là ranh giới đoạn văn thì thẻ nghỉ nằm ở cuối đoạn k;
    mối nối giữa hai mảnh của một đoạn văn dài (đoạn k+1 là cont) thì không có."""
    text = join_paras(segs[k].paras)
    gap = segs[k].paras[-1][1]
    if gap and k + 1 < len(segs) and not segs[k + 1].cont:
        text += "\n" + _tag(gap)
    return text


@dataclass
class Unit:
    """Một bước dựng audio. kind: "text" (gọi model, có cache) | "silence" (khoảng lặng, seconds)."""
    kind: str
    engine: object = None
    voice: str = ""
    text: str = ""
    seconds: float = 0.0
    chars: int = 0
    pause: bool = False   # khoảng lặng sinh từ thẻ [nghỉ …] (xuống đoạn, tiêu đề, dấu ngăn cảnh), không phải khoảng nghỉ khi đổi giọng


def units(text: str, narr: tuple, dlg: tuple | None, normalize: bool, book_lex: list[dict] | None = None,
          global_lex: list[dict] | None = None, piece_chars: int = PIECE_CHARS) -> list[Unit]:
    """Từ điển → (tuỳ chọn) tách lời thoại → từng run → plan (thẻ nghỉ) → mảnh ≤ piece_chars. Raise ValueError (thẻ nghỉ sai)."""
    text = lexicon.apply(text, book_lex, global_lex)
    chunks = runs(split_text(text)) if dlg else [Run("narr", text, False)]
    out: list[Unit] = []
    prev_ends_pause = False
    for ri, r in enumerate(chunks):
        engine, voice = dlg if r.kind == "dlg" else narr
        plan = dialogue.make_plan(engine, r.text, normalize)
        if plan == [("text", "")]:
            continue
        # đổi giọng thì thêm một khoảng nghỉ nhỏ, trừ khi chỗ đó đã có thẻ nghỉ (xuống đoạn): tránh cộng dồn hai khoảng
        if out and not prev_ends_pause and plan[0][0] != "pause":
            out.append(Unit("silence", seconds=GAP_NEW_LINE if r.new_line else GAP_SAME_LINE))
        for idx, (kind, val) in enumerate(plan):
            if kind == "text":
                out.extend(Unit("text", engine, voice, p, chars=len(p)) for p in split_pieces(val, piece_chars))
                continue
            # thẻ nghỉ: trừ phần lặng đệm sát đoạn chữ kề bên (cùng cách tính với dialogue.render_plan), kể cả chữ nằm ở run kề bên
            pads = (idx > 0 and plan[idx - 1][0] == "text") + (idx + 1 < len(plan) and plan[idx + 1][0] == "text")
            # chữ nằm ở run kề bên (đổi giọng) hoặc ở đoạn kề bên: thẻ nghỉ cuối plan luôn được nối với một đoạn chữ khác
            # (thẻ nghỉ ở cuối đoạn cắt = ranh giới đoạn văn, đoạn kế tiếp bắt đầu bằng chữ)
            pads += (idx == 0 and bool(out) and out[-1].kind == "text") + (idx == len(plan) - 1)
            out.append(Unit("silence", seconds=max(0.0, val - pads * dialogue.SEGMENT_PAD_S - PAUSE_TRIM_S), pause=True))
        prev_ends_pause = plan[-1][0] == "pause"
    return out


async def render_unit(u: Unit, speed: int, warnings: list | None = None, force: bool = False) -> np.ndarray:
    """force=True: bỏ qua cache (dùng cho "Tạo lại chương": model lấy mẫu ngẫu nhiên nên cho bản đọc khác)."""
    if u.kind == "silence":
        return np.zeros(int(u.seconds * dialogue.SR), dtype=np.float32)
    return await dialogue.synth_segment(u.engine, u.voice, u.text, speed, force=force, warnings=warnings if warnings is not None else [])


async def render(text: str, narr: tuple, dlg: tuple | None, speed: int, normalize: bool,
                 book_lex: list[dict] | None = None, global_lex: list[dict] | None = None,
                 warnings: list | None = None) -> np.ndarray:
    """units() → sinh từng bước → ghép (float32 48 kHz). narr / dlg = (engine, voice); dlg=None thì cả văn bản do giọng kể đọc."""
    parts = [await render_unit(u, speed, warnings) for u in units(text, narr, dlg, normalize, book_lex, global_lex)]
    return np.concatenate(parts) if parts else np.zeros(int(0.4 * dialogue.SR), dtype=np.float32)
