"""Từ điển phát âm 2 cấp (toàn cục data/lexicon.json + theo từng truyện) và gợi ý tên riêng.

Mỗi mục: {match, replace, pause_before, pause_after, whole_word, case_sensitive}
  replace        "đọc thành": thay chữ (rỗng = giữ nguyên chữ gốc)
  pause_before/after  "tạm dừng quanh": chèn [nghỉ Ns] trước / sau cụm (0 = không chèn; 0.1–5 giây)
Áp dụng TRƯỚC bước chuẩn hoá văn bản (xem books.reading_text / narrate.render).

Một lượt duy nhất trên văn bản gốc (không áp dụng nối tiếp), nên kết quả của mục này không bị mục khác khớp lại.
Khi hai mục chồng nhau: cụm khớp dài hơn thắng; bằng nhau thì mục của truyện thắng mục toàn cục, rồi mục đứng trước.
Chuỗi gạch nối ("Đấu-Khí") KHÔNG giúp VieNeu: sea-g2p đổi gạch nối thành khoảng trắng nên audio giống hệt (xem
scripts/lexicon_probe.py), vì vậy từ điển dùng "đọc thành" và "tạm dừng quanh" thay vì gạch nối.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import library

GLOBAL_PATH = library.DATA / "lexicon.json"
STOPWORDS_PATH = Path(__file__).resolve().parent / "config" / "name_stopwords.txt"
MAX_ENTRIES = 2000
MAX_MATCH_CHARS = 100
PAUSE_MIN, PAUSE_MAX = 0.1, 5.0
_lock = threading.Lock()


class LexiconError(ValueError):
    pass


def _pause(v, label: str) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        raise LexiconError(f"{label} phải là số giây.")
    if x == 0:
        return 0.0
    if not PAUSE_MIN <= x <= PAUSE_MAX:
        raise LexiconError(f"{label} phải là 0 (không nghỉ) hoặc từ {PAUSE_MIN:g} đến {PAUSE_MAX:g} giây.")
    return round(x, 1)


def validate(entries) -> list[dict]:
    if not isinstance(entries, list):
        raise LexiconError("Từ điển phải là danh sách.")
    if len(entries) > MAX_ENTRIES:
        raise LexiconError(f"Tối đa {MAX_ENTRIES} mục.")
    out = []
    for e in entries:
        match = unicodedata.normalize("NFC", str(e.get("match", "")).strip())
        if not match or len(match) > MAX_MATCH_CHARS:
            raise LexiconError(f"Mục 'match' phải từ 1 đến {MAX_MATCH_CHARS} ký tự.")
        entry = {
            "match": match,
            "replace": unicodedata.normalize("NFC", str(e.get("replace", "")).strip())[:200],
            "pause_before": _pause(e.get("pause_before"), f"Nghỉ trước '{match}'"),
            "pause_after": _pause(e.get("pause_after"), f"Nghỉ sau '{match}'"),
            "whole_word": bool(e.get("whole_word", True)),
            "case_sensitive": bool(e.get("case_sensitive", False)),
        }
        if not (entry["replace"] or entry["pause_before"] or entry["pause_after"]):
            raise LexiconError(f"Mục '{match}' cần có \"đọc thành\" hoặc khoảng nghỉ trước/sau.")
        out.append(entry)
    return out


def load_global() -> list[dict]:
    try:
        return validate(json.loads(GLOBAL_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def save_global(entries) -> list[dict]:
    clean = validate(entries)
    with _lock:
        GLOBAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        library._write_json(GLOBAL_PATH, clean)
    return clean


def _compile(e: dict) -> re.Pattern:
    pat = re.escape(e["match"])
    if e["whole_word"]:
        pat = rf"(?<!\w){pat}(?!\w)"
    return re.compile(pat, 0 if e["case_sensitive"] else re.IGNORECASE)


def _pause_tag(sec: float) -> str:
    return f"[nghỉ {sec:g}s]"


def apply(text: str, book_entries: list[dict] | None = None, global_entries: list[dict] | None = None) -> str:
    """Áp dụng từ điển lên `text` (một lượt). book_entries được ưu tiên hơn global_entries khi khớp bằng nhau."""
    entries = [(0, i, e) for i, e in enumerate(book_entries or [])] + [(1, i, e) for i, e in enumerate(global_entries or [])]
    if not entries or not text:
        return text
    found: list[tuple[int, int, int, int, dict]] = []  # (start, -length, tier, idx, entry) + end
    spans = []
    for tier, idx, e in entries:
        for m in _compile(e).finditer(text):
            spans.append((m.start(), -(m.end() - m.start()), tier, idx, m.end(), e))
    spans.sort(key=lambda s: s[:4])
    out, pos = [], 0
    for start, _, _, _, end, e in spans:
        if start < pos:  # chồng lên cụm đã nhận
            continue
        out.append(text[pos:start])
        core = e["replace"] or text[start:end]
        if e["pause_before"]:
            out.append(_pause_tag(e["pause_before"]) + " ")
        out.append(core)
        if e["pause_after"]:
            out.append(" " + _pause_tag(e["pause_after"]))
        pos = end
    out.append(text[pos:])
    return "".join(out)


# ───────────────────────────── gợi ý tên riêng ─────────────────────────────

def load_stopwords() -> set[str]:
    """config/name_stopwords.txt: mỗi dòng một từ, '#' là chú thích; không phân biệt hoa thường. Sửa file là có hiệu lực ngay."""
    try:
        lines = STOPWORDS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {unicodedata.normalize("NFC", l.split("#")[0].strip()).lower() for l in lines if l.split("#")[0].strip()}


_WORD = re.compile(r"[^\W\d_]+")
_SENT_END = ".!?…"
# Ký tự ngay trước từ đầu cụm cho biết từ đó đứng đầu câu / đầu lời thoại: . ! ? : … " “ « ‘ ' ( – — - 「 (hoặc đầu dòng)
_BOUNDARY = set(".!?:…\"“”«»‘’'(–—―-「」『』[")
MIN_PHRASE, MAX_PHRASE = 2, 4
SINGLE_MIN = 5   # tiếng đơn (vd. "Viêm") chỉ được gợi ý khi đứng riêng, không ở đầu câu, ≥ ngần này lần


def _is_cap(w: str) -> bool:
    return len(w) >= 2 and w[0].isupper() and w[1:].islower()


@dataclass
class Term:
    phrase: str
    count: int = 0
    chapter: int = 0
    example: str = ""
    parent: str = ""   # khác rỗng: gợi ý 1 tiếng, thành phần của cụm `parent`


def _sentence(line: str, start: int, end: int, limit: int = 220) -> str:
    a = max((line.rfind(c, 0, start) for c in _SENT_END), default=-1) + 1
    b = min((i for i in (line.find(c, end) for c in _SENT_END) if i >= 0), default=len(line) - 1) + 1
    s = line[a:b].strip().lstrip('"“”«»‘’\'–—-… ')  # bỏ dấu ngoặc / gạch thoại còn sót ở đầu câu
    if len(s) > limit:  # câu dài: cắt quanh cụm
        lo = max(0, start - a - limit // 2)
        s = ("…" if lo else "") + line[a + lo:a + lo + limit].strip() + "…"
    return s


def scan_line(line: str, stop: set[str]):
    """Sinh (phrase, start, end) cho các cụm viết hoa KHÔNG đứng đầu câu trong một dòng: 2–4 tiếng (gợi ý chính)
    và 1 tiếng đứng riêng (chỉ dùng làm gợi ý phụ khi là thành phần của một cụm chính)."""
    toks = [(m.group(), m.start(), m.end()) for m in _WORD.finditer(line)]
    i, n = 0, len(toks)
    while i < n:
        if not _is_cap(toks[i][0]):
            i += 1
            continue
        j = i
        while j + 1 < n and _is_cap(toks[j + 1][0]) and not line[toks[j][2]:toks[j + 1][1]].strip():
            j += 1
        run = toks[i:j + 1]
        before = line[:run[0][1]].rstrip()
        at_start = not before or before[-1] in _BOUNDARY
        # bỏ từ dừng (Anh, Hắn, Nhưng…) ở hai đầu; bỏ từ dừng đầu câu thì phần còn lại không còn đứng đầu câu
        while run and run[0][0].lower() in stop:
            run = run[1:]
            at_start = False
        while run and run[-1][0].lower() in stop:
            run = run[:-1]
        if run and not at_start and len(run) <= MAX_PHRASE:  # 1 tiếng cũng yield; suggest_terms tách theo khoảng trắng
            yield " ".join(t[0] for t in run), run[0][1], run[-1][2]
        i = j + 1


def suggest_terms(chapters, known: set[str] | None = None, min_count: int = 3, limit: int = 200,
                  stop: set[str] | None = None, single_min: int = SINGLE_MIN) -> list[Term]:
    """chapters: iterable (n, text). Trả các cụm viết hoa 2–4 tiếng lặp lại ≥ min_count lần, xếp theo tần suất giảm dần;
    ngay sau mỗi cụm là các tiếng đơn thành phần của nó (Term.parent = cụm cha) nếu tiếng đó đứng riêng, không ở đầu câu,
    ≥ single_min lần. `known`: các cụm đã có trong từ điển (không phân biệt hoa thường) bị bỏ."""
    stop = load_stopwords() if stop is None else stop
    skip = {k.lower() for k in (known or set())}
    terms: dict[str, Term] = {}
    for n, text in chapters:
        for line in text.split("\n"):
            if not line or line[0] == "[":  # dòng [nghỉ …]
                continue
            for phrase, a, b in scan_line(line, stop):
                t = terms.get(phrase)
                if t is None:
                    t = terms[phrase] = Term(phrase, 0, n, _sentence(line, a, b))
                t.count += 1
    ranked = [t for t in terms.values() if " " in t.phrase and t.count >= min_count and t.phrase.lower() not in skip]
    ranked.sort(key=lambda t: (-t.count, t.phrase))
    ranked = ranked[:limit]
    singles = {p: t for p, t in terms.items() if " " not in p and t.count >= single_min and p.lower() not in skip}
    children: dict[str, list[Term]] = {}
    used: set[str] = set()
    for parent in ranked:  # mỗi tiếng đơn chỉ nằm dưới một cụm cha (cụm xuất hiện nhiều hơn)
        for word in dict.fromkeys(parent.phrase.split()):
            if word in singles and word not in used:
                used.add(word)
                s = singles[word]
                children.setdefault(parent.phrase, []).append(Term(s.phrase, s.count, s.chapter, s.example, parent.phrase))
    out: list[Term] = []
    for parent in ranked:
        out.append(parent)
        out.extend(sorted(children.get(parent.phrase, []), key=lambda t: (-t.count, t.phrase)))
    return out
