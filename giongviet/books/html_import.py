"""Nhập chương truyện từ file HTML đã lưu từ trình duyệt (Phase "nhập HTML").

Chỉ thư viện chuẩn, không đụng tới đĩa / mạng: books/store.py gọi các hàm ở đây khi nhập và khi áp quy tắc làm sạch;
tools/clean_html.py (công cụ dòng lệnh độc lập) cũng import lại từ đây.

  extract(html, selector)   → (tiêu đề thô, văn bản, tìm thấy khung?)  lấy từ khung chương ĐẾN HẾT TRANG
  clean_title(raw)          → "Chương N: Tiêu đề" (bỏ tên trang / "Chương N:" lặp, IN HOA → chữ thường)
  chapter_number(title, filename)
  unmask / join_split_numbers / find_masked  → ba quy tắc làm sạch dùng chung với books/store.py
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_SELECTOR = "#chapter-c"
SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "button", "form"}
VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "source", "wbr"}
BREAK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "li", "blockquote"}
_SELECTOR = re.compile(r"^([a-zA-Z][\w-]*)?(?:#([\w-]+))?((?:\.[\w-]+)*)$")


# ─────────────────────────── trích văn bản từ HTML ───────────────────────────


def parse_selector(selector: str) -> tuple[str, str, tuple[str, ...]]:
    """Selector đơn giản: "#id", ".class", "tag", "tag#id.class1.class2". Raise ValueError nếu không hiểu."""
    m = _SELECTOR.match(selector.strip())
    if not selector.strip() or not m or not any(m.groups()):
        raise ValueError(
            f"Selector '{selector}' không hợp lệ (chỉ nhận dạng #id, .class, tag hoặc tag#id.class)."
        )
    return (
        (m.group(1) or "").lower(),
        m.group(2) or "",
        tuple(c for c in m.group(3).split(".") if c),
    )


class ChapterExtractor(HTMLParser):
    """Lấy văn bản từ thẻ khớp `selector` ĐẾN HẾT TRANG (không tắt khi gặp thẻ đóng của khung): HTML lỗi có thể đẩy nội dung ra
    ngoài khung. Bỏ script / style / khối quảng cáo. Nhớ nội dung <title>."""

    def __init__(self, selector: str = DEFAULT_SELECTOR):
        super().__init__(convert_charrefs=True)
        self.sel_tag, self.sel_id, self.sel_classes = parse_selector(selector)
        self.capturing = False
        self.skip_depth = 0  # đang ở trong script/style/quảng cáo
        self.skip_stack: list[str] = []
        self.parts: list[str] = []
        self.title = ""
        self._in_title = False

    def _is_start(self, tag: str, a: dict) -> bool:
        if self.sel_tag and tag != self.sel_tag:
            return False
        if self.sel_id and a.get("id") != self.sel_id:
            return False
        classes = (a.get("class") or "").split()
        return all(c in classes for c in self.sel_classes)

    @staticmethod
    def _is_ad(attrs: dict) -> bool:
        blob = f"{attrs.get('id', '')} {attrs.get('class', '')}".lower()
        return bool(re.search(r"\bads?\b|ads[-_]|[-_]ads|advert|banner|quang-?cao", blob))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        if not self.capturing and self._is_start(tag, a):
            self.capturing = True
            return
        if tag in VOID_TAGS:
            if tag == "br" and self.capturing and not self.skip_depth:
                self.parts.append("\n")
            return
        if self.skip_depth or tag in SKIP_TAGS or self._is_ad(a):
            self.skip_depth += 1
            self.skip_stack.append(tag)
            return
        if self.capturing and tag in BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self.skip_depth:
            # đóng đúng thẻ đã mở trong vùng bỏ qua (HTML lỗi: bỏ qua thẻ đóng lạc)
            if tag in self.skip_stack:
                while self.skip_stack:
                    t = self.skip_stack.pop()
                    self.skip_depth -= 1
                    if t == tag:
                        break
            return
        if self.capturing and tag in BREAK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self.capturing and not self.skip_depth:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self.capturing and not self.skip_depth:
            # xuống dòng trong mã nguồn chỉ là định dạng → dấu cách
            self.parts.append(re.sub(r"\s+", " ", data))


def extract(html: str, selector: str = DEFAULT_SELECTOR) -> tuple[str, str, bool]:
    """(tiêu đề thô, văn bản, tìm thấy khung?). Không thấy khung thì lấy cả <body> (found=False)."""
    p = ChapterExtractor(selector)
    p.feed(html)
    p.close()
    found = p.capturing
    if not found:
        p = ChapterExtractor(selector)
        p.capturing = True
        p.feed(html)
        p.close()
    return p.title.strip(), "".join(p.parts), found


# ───────────────────────────── tiêu đề, số chương ─────────────────────────────


def clean_title(raw: str) -> str:
    t = re.split(r"\s+[|–-]\s+(?:Truyen|truyện|TruyenFull)", raw, flags=re.I)[0]
    t = re.sub(r"^.*?(?=Chương\s+\d)", "", t)  # bỏ tên truyện phía trước
    t = re.sub(r"^(Chương\s+\d+)\s*:\s*\1\s*:\s*", r"\1: ", t, flags=re.I)  # "Chương 1: Chương 1:"
    head, _, rest = t.partition(":")
    if rest and rest.strip().upper() == rest.strip():  # phần sau dấu : viết IN HOA
        rest = " " + rest.strip().lower().capitalize()
    t = (head + (":" + rest if rest else "")).strip()
    return re.sub(r"\s+", " ", t)


def chapter_number(title: str, filename: str = "") -> int | None:
    """Số chương: trong tiêu đề ("Chương N"), không có thì số cuối cùng trong tên file (1, 2, 10 — không theo bảng chữ cái)."""
    m = re.search(r"Chương\s+(\d+)", title, re.I)
    if m:
        return int(m.group(1))
    nums = re.findall(r"\d+", Path(filename).stem)
    return int(nums[-1]) if nums else None


# ───────────────────────── từ bị che, số bị tách ─────────────────────────


def load_masked_words(path: Path) -> list[str]:
    """Đọc file .txt (mỗi dòng một từ, '#' là chú thích): cụm dài khớp trước."""
    if not path.exists():
        return []
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(unicodedata.normalize("NFC", line))
    return sorted(set(words), key=len, reverse=True)


@lru_cache(maxsize=8)
def _patterns(words: tuple[str, ...]):
    pats = []
    for w in sorted(set(words), key=len, reverse=True):
        # mỗi ký tự chữ có thể bị thay bằng "*"; phải có ít nhất một "*"
        body = "".join(f"(?:{re.escape(c)}|\\*)" if c.isalpha() else re.escape(c) for c in w)
        pats.append((re.compile(rf"(?<![\w*])(?=[\w ]*\*)(?i:{body})(?![\w*])"), w))
    return pats


def build_unmask_patterns(words) -> list:
    return _patterns(tuple(words))


def keep_case(src: str, word: str) -> str:
    return word[0].upper() + word[1:] if src[:1].isupper() else word


def unmask(text: str, patterns) -> str:
    if "*" not in text:
        return text
    for pat, word in patterns:
        # dòng chỉ toàn dấu * (ngăn cảnh "***") khớp với mọi từ: phải còn ít nhất một chữ thật mới khôi phục
        text = pat.sub(
            lambda m, w=word: (
                keep_case(m.group(0), w) if re.search(r"\w", m.group(0)) else m.group(0)
            ),
            text,
        )
    return text


_MASKED_TOKEN = re.compile(r"[\w*]*\*[\w*]*")


def find_masked(text: str) -> list[str]:
    """Từ còn dấu * kẹp giữa chữ (chưa khôi phục được): "h*m", "th*ch"…; bỏ dòng dấu * thuần (ngăn cảnh)."""
    return [t for t in _MASKED_TOKEN.findall(text) if re.search(r"\w", t.replace("_", ""))]


def masked_matches(masked: str, correct: str) -> bool:
    """Từ bị che `masked` ("m**n") có đúng là `correct` ("muốn") bị che bớt chữ không?"""
    if "*" not in masked or "*" in correct or not correct.strip():
        return False
    body = "".join(
        f"(?:{re.escape(c)}|\\*)" if c.isalpha() else re.escape(c)
        for c in unicodedata.normalize("NFC", correct.strip())
    )
    return re.fullmatch(f"(?i:{body})", unicodedata.normalize("NFC", masked.strip())) is not None


_THOUSANDS = [
    (re.compile(r"(\d)\.\s+(\d{3})(?!\d)"), r"\1.\2"),
    (re.compile(r"(\d),\s+(\d{3})(?!\d)"), r"\1,\2"),
]


def join_split_numbers(text: str) -> str:
    """ "2. 513" → "2.513", "2, 513" → "2,513" (trang truyện tách số ở dấu phân cách hàng nghìn)."""
    for rx, rep in _THOUSANDS:
        text = rx.sub(rep, text)
    return text


# ───────────────────── làm sạch trọn gói (cho tools/clean_html.py) ─────────────────────

SEPARATOR_RE = re.compile(r"^[\s=\-–—_~*•♦◆oO0.·]{3,}$")


def clean_body(text: str, patterns) -> tuple[str, list[str]]:
    """Văn bản trích từ HTML → văn bản sạch (mỗi dòng một đoạn văn, ngăn cảnh = "***") và danh sách từ còn bị che.
    Dùng cho tools/clean_html.py; tab Sách nói áp từng bước qua các quy tắc làm sạch của books/store.py."""
    text = unicodedata.normalize("NFC", text).replace("\xa0", " ")
    text = join_split_numbers(unmask(text, patterns))
    out: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if SEPARATOR_RE.match(line):
            line = "***"
        if not line or (line == "***" and (not out or out[-1] == "***")):
            continue
        out.append(line)
    while out and out[-1] == "***":
        out.pop()
    return "\n".join(out), sorted(set(find_masked("\n".join(out))))
