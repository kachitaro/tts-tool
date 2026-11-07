"""Sách nói (Phase 6a): nhập truyện .txt/.epub, tách chương, làm sạch.

data/books/<book_id>/book.json          cài đặt + nguồn + kết quả tách chương
data/books/<book_id>/source/            file gốc (giữ nguyên)
data/books/<book_id>/chapters/<nnnn>.txt   văn bản chương đã làm sạch (không gồm tiêu đề)
data/books/<book_id>/chapters/<nnnn>.json {n, title, chars, status}

Pipeline: nguồn → giải mã (dò encoding) → [chuẩn hoá ký tự] → tách chương → làm sạch từng chương → ghi.
EPUB đọc bằng thư viện chuẩn (zipfile + xml.etree + html.parser): không thêm phụ thuộc.
"""

from __future__ import annotations

import html.parser
import io
import json
import os
import math
import re
import shutil
import threading
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import html_import
import library

BOOKS = library.DATA / "books"
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_FILES = 5000
MAX_UNZIPPED_BYTES = 300 * 1024 * 1024
SEGMENT_CHARS = int(os.getenv("BOOK_SEGMENT_CHARS", "800"))  # đoạn = đơn vị cache/tạm dừng của hàng đợi audio
MIN_CHAPTER_CHARS = 20       # chương ngắn hơn (mục lục, trang bìa) bị bỏ
MIN_INTRO_CHARS = 100        # phần trước chương đầu tiên chỉ giữ nếu đủ dài ("Mở đầu")
MAX_TITLE_CHARS = 150        # dòng dài hơn không coi là tiêu đề chương
CHARS_PER_SEC = 15.0         # ước tính tốc độ đọc (đo: "Xin chào các bạn." ≈ 1,1 s); 6c sẽ thay bằng RTF đo thật
SOURCE_EXTS = {".txt": "txt", ".text": "txt", ".epub": "epub", ".html": "html", ".htm": "html"}
MASKED_PATH = library.DATA / "masked_words.json"       # từ điển từ bị che bằng dấu * (khởi tạo từ scripts/masked_words.txt)
MASKED_SEED = Path(__file__).resolve().parent / "scripts" / "masked_words.txt"
_lock = threading.Lock()


class BookError(ValueError):
    """Lỗi do dữ liệu người dùng (server trả 400)."""


class NotFound(LookupError):
    pass


# ───────────────────────────── cài đặt mặc định ─────────────────────────────

_NUM = r"(?:\d+|[IVXLCDM]+|[０-９]+)"
_ZH_NUM = r"[0-9０-９零〇一二三四五六七八九十百千万两兩]+"
# Chương 12 | Chương 12: … | Chương XII | 第12章 | 第十二回 | Quyển 2 Chương 5 | Hồi 3
DEFAULT_SPLIT_REGEX = (
    r"^\s*(?:(?:Quyển|Quyen|Tập|Tap)\s+" + _NUM + r"\s*[,:;.\-–—]?\s*)?"
    r"(?:(?:Chương|Chuong|Hồi|Hoi)\s+" + _NUM + r"\b|第\s*" + _ZH_NUM + r"\s*[章回节節])"
)

RULES: list[tuple[str, str]] = [
    ("control_chars", "Bỏ ký tự điều khiển / khoảng trắng đặc biệt, chuẩn hoá Unicode (NFC)"),
    ("quotes", "Chuẩn hoá dấu ngoặc kép (“ ” « » 「 」 → \")"),
    ("ellipsis", "Chuẩn hoá dấu ba chấm (..., 。。。, …… → …)"),
    ("url_lines", "Bỏ dòng chứa URL / tên miền"),
    ("credit_lines", "Bỏ dòng chứa \"nguồn:\" hoặc \"truyện được dịch bởi\""),
    ("separators", "Dòng chỉ có dấu ngăn cảnh (***, ---, ~~~, ooo, ♦…) → [nghỉ Ns]"),
    ("dup_lines", "Bỏ dòng trùng lặp (liền nhau, hoặc lặp ở nhiều chương như đầu/cuối trang)"),
    ("join_lines", "Gộp dòng bị ngắt giữa câu (dòng sau bắt đầu bằng chữ thường)"),
    ("unmask", "Khôi phục từ bị che bằng dấu * (h*m m**n → ham muốn) theo từ điển data/masked_words.json"),
    ("join_numbers", "Ghép số bị tách (2. 513 → 2.513)"),
    ("blank_lines", "Bỏ dòng trống thừa (mỗi dòng là một đoạn văn)"),
]


def default_settings() -> dict:
    return {
        "read_title": True,
        "paragraph_pause_s": PARAGRAPH_PAUSE_S,  # nghỉ giữa hai đoạn văn khi đọc
        "title_pause_s": TITLE_PAUSE_S,          # nghỉ sau tiêu đề chương
        "split": {"regex": DEFAULT_SPLIT_REGEX, "mode": "regex", "ops": [], "selector": html_import.DEFAULT_SELECTOR},
        "clean": {"rules": {name: True for name, _ in RULES}, "custom": [], "separator_pause": 1.5},
        "exceptions": [],  # [{rule, line}]: quy tắc làm sạch không áp dụng cho dòng đó ("Giữ dòng này")
    }


# ───────────────────────────── giải mã ─────────────────────────────

def _cjk_ratio(text: str) -> float:
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return sum("\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf" for c in chars) / len(chars)


def decode_bytes(data: bytes) -> tuple[str, str]:
    """bytes → (văn bản NFC, tên encoding). Dò UTF-8 / UTF-16 / GB18030 / Windows-1258."""
    if data.startswith(b"\xef\xbb\xbf"):
        return unicodedata.normalize("NFC", data[3:].decode("utf-8", "replace")), "utf-8"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return unicodedata.normalize("NFC", data.decode("utf-16", "replace")), "utf-16"
    head = data[:8192]
    if len(head) >= 4 and head.count(b"\x00") > len(head) * 0.2:  # UTF-16 không BOM: byte 0 ở vị trí chẵn (BE) hoặc lẻ (LE)
        enc = "utf-16-be" if head[0::2].count(b"\x00") > head[1::2].count(b"\x00") else "utf-16-le"
        return unicodedata.normalize("NFC", data.decode(enc, "replace")), "utf-16"
    try:
        return unicodedata.normalize("NFC", data.decode("utf-8")), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        gb = data.decode("gb18030")
        if _cjk_ratio(gb) >= 0.5:  # chữ Hán chiếm đa số; byte cp1258 giải mã bằng GB18030 chỉ ra vài chữ Hán rải rác
            return unicodedata.normalize("NFC", gb), "gb18030"
    except UnicodeDecodeError:
        pass
    return unicodedata.normalize("NFC", data.decode("cp1258", "replace")), "windows-1258"


# ───────────────────────────── đọc nguồn ─────────────────────────────

@dataclass
class Doc:
    name: str
    text: str
    title: str = ""
    meta: dict = field(default_factory=dict)   # nguồn HTML: {file, chapter_no, found, chars}


class _Extract(html.parser.HTMLParser):
    """XHTML → văn bản: thẻ khối thành xuống dòng, bỏ script/style; nhớ tiêu đề (h1–h3 / title) đầu tiên."""
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "blockquote", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading = ""     # h1–h3 đầu tiên
        self.doc_title = ""   # <title> (dự phòng khi không có heading)
        self._skip = 0
        self._in: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "title") and self._in is None and not (self.doc_title if tag == "title" else self.heading):
            self._in, self._buf = tag, []

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == self._in:
            text = " ".join("".join(self._buf).split())
            if tag == "title":
                self.doc_title = text
            else:
                self.heading = text
            self._in = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in:
            self._buf.append(data)
        if self._in != "title":  # nội dung <title> trong <head> không phải văn bản truyện
            self.parts.append(data)


def read_epub(data: bytes) -> tuple[list[Doc], dict]:
    """EPUB → (các tài liệu theo thứ tự spine, {title, author}). Raise BookError nếu không phải EPUB hợp lệ."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED_BYTES:
            raise BookError("File EPUB giải nén quá lớn.")
        root = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in root.findall(".//{*}rootfile"))
        opf = ET.fromstring(z.read(opf_path))
        base = PurePosixPath(opf_path).parent
        manifest = {i.get("id"): i.get("href") for i in opf.findall(".//{*}item")}
        spine = [r.get("idref") for r in opf.findall(".//{*}itemref") if r.get("linear") != "no"]
        meta = {"title": "", "author": ""}
        for key, tag in (("title", "{*}title"), ("author", "{*}creator")):
            el = opf.find(f".//{tag}")
            if el is not None and el.text:
                meta[key] = el.text.strip()
        docs: list[Doc] = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            path = str(base / unquote(href.split("#")[0]))
            if path not in z.namelist():
                continue
            parser = _Extract()
            parser.feed(decode_bytes(z.read(path))[0])
            text = "".join(parser.parts)
            docs.append(Doc(PurePosixPath(path).stem, text, parser.heading or parser.doc_title))
    except BookError:
        raise
    except (zipfile.BadZipFile, KeyError, StopIteration, ET.ParseError) as ex:
        raise BookError(f"Không đọc được EPUB: {type(ex).__name__}.") from ex
    return docs, meta


def _natural_key(name: str):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^\w.\-]+", "_", Path(name).name, flags=re.UNICODE).strip("._") or "file"
    return stem[:80]


def _dir(book_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", book_id):
        raise NotFound(book_id)
    return BOOKS / book_id


def _write_json(path: Path, data) -> None:
    library._write_json(path, data)


def read_html(name: str, data: bytes, selector: str = html_import.DEFAULT_SELECTOR) -> Doc:
    """File HTML chương → Doc: văn bản từ khung chương đến hết trang, tiêu đề đã làm sạch (rỗng thì dùng tên file)."""
    title_raw, body, found = html_import.extract(decode_bytes(data)[0], selector)
    title = html_import.clean_title(title_raw)
    return Doc(Path(name).stem, body, title, {"file": name, "chapter_no": html_import.chapter_number(title, name),
                                              "found": found, "chars": len(body.strip())})


def validate_selector(selector: str) -> str:
    try:
        html_import.parse_selector(selector)
    except ValueError as ex:
        raise BookError(str(ex)) from ex
    return selector.strip()


def expand_zip(name: str, data: bytes) -> list[tuple[str, bytes]]:
    """.zip → các file .html/.htm bên trong (bỏ thư mục, file ẩn, __MACOSX và file khác). Giới hạn dung lượng giải nén."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as ex:
        raise BookError(f"'{name}' không phải file zip hợp lệ.") from ex
    infos = [i for i in z.infolist() if not i.is_dir() and Path(i.filename).suffix.lower() in (".html", ".htm")
             and not any(p.startswith((".", "__MACOSX")) for p in PurePosixPath(i.filename).parts)]
    if not infos:
        raise BookError(f"'{name}' không chứa file .html / .htm nào.")
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES or any(i.file_size > MAX_FILE_BYTES for i in infos):
        raise BookError(f"'{name}' quá lớn khi giải nén.")
    return [(i.filename, z.read(i)) for i in infos]


def html_warnings(docs: list[Doc]) -> list[str]:
    """Cảnh báo khi nhập HTML: không thấy khung chương, nội dung quá ngắn, trùng số chương, thiếu chương."""
    items = [d for d in docs if d.meta.get("file")]
    out: list[str] = []
    for d in items:
        if not d.meta["found"]:
            out.append(f"{d.meta['file']}: không tìm thấy khung chương, đã lấy cả <body> (kiểm tra selector trong phần Tách chương).")
        elif d.meta["chars"] < 200:
            out.append(f"{d.meta['file']}: nội dung rất ngắn ({d.meta['chars']} ký tự), kiểm tra lại.")
    by_no: dict[int, list[str]] = {}
    for d in items:
        if d.meta["chapter_no"] is not None:
            by_no.setdefault(d.meta["chapter_no"], []).append(d.meta["file"])
    for no, files in sorted(by_no.items()):
        if len(files) > 1:
            out.append(f"Trùng số chương {no}: {', '.join(files)}.")
    if len(by_no) >= 2:
        missing = [n for n in range(min(by_no), max(by_no) + 1) if n not in by_no]
        if missing:
            shown = ", ".join(map(str, missing[:30])) + (f" … và {len(missing) - 30} chương nữa" if len(missing) > 30 else "")
            out.append(f"Thiếu chương: {shown}.")
    unnumbered = sum(1 for d in items if d.meta["chapter_no"] is None)
    if unnumbered:
        out.append(f"{unnumbered} file không xác định được số chương (xếp cuối, theo tên file).")
    return out


def load_docs(book_id: str, selector: str | None = None) -> list[Doc]:
    book = get(book_id)
    selector = selector or book["split"].get("selector") or html_import.DEFAULT_SELECTOR
    docs: list[Doc] = []
    for s in book["sources"]:
        raw = (_dir(book_id) / "source" / s["file"]).read_bytes()
        if s["kind"] == "html":
            docs.append(read_html(s["name"], raw, selector))
        elif s["kind"] == "epub":
            docs += read_epub(raw)[0]
        else:
            docs.append(Doc(Path(s["name"]).stem, decode_bytes(raw)[0]))
    return docs


# ───────────────────────────── lưu trữ ─────────────────────────────

def get(book_id: str) -> dict:
    path = _dir(book_id) / "book.json"
    if not path.is_file():
        raise NotFound(book_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save(book: dict) -> None:
    with _lock:
        _write_json(_dir(book["id"]) / "book.json", book)


def list_books() -> list[dict]:
    out = []
    for p in sorted(BOOKS.glob("*/book.json")) if BOOKS.is_dir() else []:
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({k: b.get(k) for k in ("id", "title", "author", "status", "created_at")}
                   | {"chapters": b.get("chapters", {}).get("count", 0), "chars": b.get("chapters", {}).get("chars", 0),
                      "size_bytes": disk_usage(b["id"])["total"]})
    return sorted(out, key=lambda b: b["created_at"] or "", reverse=True)


def delete(book_id: str) -> None:
    with _lock:
        get(book_id)
        shutil.rmtree(_dir(book_id))


def import_files(files: list[tuple[str, bytes]], title: str, author: str, voice: dict) -> dict:
    """Tạo truyện nháp từ các file .txt / .epub / .html / .htm / .zip (zip chứa html) — giữ file gốc trong source/. Chưa tách chương.
    File HTML xếp theo số chương (trong tiêu đề, không có thì trong tên file), không theo bảng chữ cái."""
    if not files:
        raise BookError("Chưa chọn file nào.")
    for name, data in files:
        if Path(name).suffix.lower() != ".zip" and SOURCE_EXTS.get(Path(name).suffix.lower()) is None:
            raise BookError(f"'{name}': chỉ nhận .txt, .epub, .html, .htm và .zip (chứa html).")
        if len(data) > MAX_FILE_BYTES:
            raise BookError(f"'{name}' quá lớn (tối đa {MAX_FILE_BYTES // 2**20} MB).")
    expanded: list[tuple[str, bytes]] = []
    for name, data in files:
        expanded += expand_zip(name, data) if Path(name).suffix.lower() == ".zip" else [(name, data)]
    files = expanded
    if len(files) > MAX_FILES:
        raise BookError(f"Tối đa {MAX_FILES} file mỗi lần nhập.")

    def order(f: tuple[str, bytes]):
        if SOURCE_EXTS[Path(f[0]).suffix.lower()] == "html":
            no = read_html(f[0], f[1]).meta["chapter_no"]
            return (no if no is not None else float("inf"), _natural_key(f[0]))
        return (float("inf"), _natural_key(f[0]))

    files = sorted(files, key=order)
    sources, epub_meta = [], {}
    for i, (name, data) in enumerate(files, 1):
        kind = SOURCE_EXTS[Path(name).suffix.lower()]
        if kind == "html":
            d = read_html(name, data)
            info = {"encoding": "html", "title": d.title, "chapter_no": d.meta["chapter_no"], "chars": d.meta["chars"]}
        elif kind == "epub":
            docs, meta = read_epub(data)
            epub_meta = epub_meta or meta
            info = {"encoding": "epub", "docs": len(docs)}
        else:
            text, enc = decode_bytes(data)
            info = {"encoding": enc, "chars": len(text)}
        sources.append({"name": name, "file": f"{i:04d}-{_safe_name(name)}", "kind": kind, "bytes": len(data), **info})
    title = title.strip() or epub_meta.get("title") or Path(files[0][0]).stem
    author = author.strip() or epub_meta.get("author", "")
    with _lock:
        base = library.slugify(title)
        book_id, n = base, 2
        while (BOOKS / book_id).exists():
            book_id, n = f"{base}-{n}", n + 1
        d = BOOKS / book_id
        (d / "source").mkdir(parents=True)
        (d / "chapters").mkdir()
        for s, (_, data) in zip(sources, files):
            (d / "source" / s["file"]).write_bytes(data)
        book = {
            "id": book_id, "title": title[:200], "author": author[:200], "voice": voice, "speed": 0, "normalize": True,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "draft",
            "sources": sources, "chapters": {"count": 0, "chars": 0}, **default_settings(),
            "lexicon": [], "dialogue_voice": {"enabled": False, **voice},
        }
        _write_json(d / "book.json", book)
    docs = load_docs(book_id)
    # Gợi ý chế độ tách: nhiều file hoặc regex không tìm thấy ≥ 2 chương mà có nhiều tài liệu → mỗi file một chương
    if len(files) > 1 or any(s["kind"] == "html" for s in sources) or (len(docs) > 1 and len(split_regex(docs, book["split"]["regex"])) < 2):
        book["split"]["mode"] = "per_file"
    save(book)
    return book


# ───────────────────────────── tách chương ─────────────────────────────

@dataclass
class Raw:
    title: str
    lines: list[str] = field(default_factory=list)


def compile_split(pattern: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as ex:
        raise BookError(f"Regex tách chương không hợp lệ: {ex}") from ex


def _is_heading(rx: re.Pattern, line: str) -> bool:
    s = line.strip()
    return 0 < len(s) <= MAX_TITLE_CHARS and bool(rx.match(s))


def split_regex(docs: list[Doc], pattern: str) -> list[Raw]:
    rx = compile_split(pattern)
    chapters: list[Raw] = [Raw("")]
    for doc in docs:
        for line in doc.text.split("\n"):
            if _is_heading(rx, line):
                chapters.append(Raw(line.strip()))
            else:
                chapters[-1].lines.append(line)
    return chapters


def split_per_file(docs: list[Doc], pattern: str) -> list[Raw]:
    rx = compile_split(pattern)
    out = []
    for doc in docs:
        lines = doc.text.split("\n")
        first = next((i for i, l in enumerate(lines) if l.strip()), None)
        if first is not None and _is_heading(rx, lines[first]):
            out.append(Raw(lines[first].strip(), lines[first + 1:]))
        else:
            out.append(Raw(doc.title or doc.name, lines))
    return out


def apply_ops(chapters: list[Raw], ops: list[dict]) -> list[Raw]:
    """Gộp / tách thủ công, áp dụng lần lượt. merge: {"op":"merge","i":k} gộp chương k với k+1 (tiêu đề k+1 thành dòng văn bản);
    split: {"op":"split","i":k,"line":L,"title":"…"} tách chương k trước dòng L (1 = dòng đầu của thân chương)."""
    chs = [Raw(c.title, list(c.lines)) for c in chapters]
    for op in ops:
        try:
            i = int(op["i"])
            if op["op"] == "merge":
                nxt = chs.pop(i + 1)
                chs[i].lines += ([nxt.title] if nxt.title else []) + nxt.lines
            elif op["op"] == "split":
                if "contains" in op:  # tách tại dòng đầu tiên chứa đoạn văn bản này (người dùng không thấy số dòng gốc)
                    needle = str(op["contains"]).strip().lower()
                    line = next((k + 1 for k, l in enumerate(chs[i].lines) if needle and needle in l.lower()), 0)
                    if not line:
                        raise BookError(f"Không thấy dòng nào chứa '{op['contains']}' trong chương {i + 1}.")
                else:
                    line = int(op["line"])
                if not 1 <= line <= len(chs[i].lines):
                    raise BookError(f"Không tách được: chương {i + 1} chỉ có {len(chs[i].lines)} dòng.")
                head, tail = chs[i].lines[: line - 1], chs[i].lines[line - 1:]
                chs[i].lines = head
                chs.insert(i + 1, Raw(str(op.get("title") or "").strip(), tail))
            else:
                raise BookError(f"Thao tác không hợp lệ: {op['op']}")
        except (KeyError, IndexError, TypeError, ValueError) as ex:
            if isinstance(ex, BookError):
                raise
            raise BookError(f"Thao tác gộp/tách không hợp lệ: {op}") from ex
    return chs


# ───────────────────────────── làm sạch ─────────────────────────────

_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_URL = re.compile(r"(?i)(?:https?://|ftp://|www\.)\S+|\b[\w-]+\.(?:com|net|org|vn|info|io|me|cc|xyz|top|co|tv)\b(?:/\S*)?")
_CREDIT = re.compile(r"(?i)nguồn\s*:|truyện được dịch bởi")
_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‟": '"', "«": '"', "»": '"', "「": '"', "」": '"', "『": '"', "』": '"',
                         "‘": "'", "’": "'", "‚": "'", "‛": "'"})
_ELLIPSIS = re.compile(r"\.{3,}|…{2,}|。{2,}|\.\s?\.\s?\.(?:\s?\.)*")
_FANCY = "◆◇♦♢※★☆●○■□▪❖✦✧✱✲§"
_SEP = re.compile(
    r"^(?:[*＊\-–—_=~～#+·•]\s*){3,}$|^(?:[oO]\s*){3,}$|^(?:[" + re.escape(_FANCY) + r"]\s*)+$"
    r"|^(?=.*[=\-–—_~*•·])(?=(?:\s*\S){3})[\s=\-–—_~*•·oO]+$"   # trộn: "--- ------oOo---- -----"
)
_PAUSE_LINE = re.compile(r"^\[nghỉ [^\]]*\]$", re.IGNORECASE)
_TERMINATORS = set(".!?…\"”'’)]}。！？:;」』»")


def validate_clean(cfg: dict) -> dict:
    """Kiểm tra và chuẩn hoá cấu hình làm sạch (regex tuỳ chỉnh phải biên dịch được; separator_pause 0.1–5)."""
    out = default_settings()["clean"]
    out["rules"].update({k: bool(v) for k, v in (cfg.get("rules") or {}).items() if k in out["rules"]})
    pause = float(cfg.get("separator_pause", out["separator_pause"]))
    if not 0.1 <= pause <= 5:
        raise BookError("separator_pause phải từ 0.1 đến 5 giây.")
    out["separator_pause"] = round(pause, 1)
    for r in cfg.get("custom") or []:
        pattern = str(r.get("pattern", ""))
        if not pattern:
            raise BookError("Quy tắc tuỳ chỉnh thiếu regex.")
        try:
            re.compile(pattern)
        except re.error as ex:
            raise BookError(f"Regex '{pattern}' không hợp lệ: {ex}") from ex
        out["custom"].append({"pattern": pattern, "replace": str(r.get("replace", "")), "enabled": bool(r.get("enabled", True))})
    return out


def _stat(stats: dict, key: str, n: int = 1) -> None:
    stats[key] = stats.get(key, 0) + n


MAX_EXAMPLES = 50     # số dòng ví dụ tối đa lưu cho mỗi quy tắc (đếm thì đếm hết)
MAX_EXCEPTIONS = 5000


def validate_exceptions(items) -> list[dict]:
    """Danh sách ngoại lệ [{rule, line}]: quy tắc `rule` không áp dụng cho dòng `line`. Bỏ trùng."""
    names = {n for n, _ in RULES}
    out, seen = [], set()
    for it in items or []:
        rule, line = str(it.get("rule", "")), str(it.get("line", "")).strip()
        if rule not in names or not line:
            raise BookError("Ngoại lệ phải có quy tắc hợp lệ và nội dung dòng.")
        if (rule, line) not in seen:
            seen.add((rule, line))
            out.append({"rule": rule, "line": line[:1000]})
    if len(out) > MAX_EXCEPTIONS:
        raise BookError(f"Tối đa {MAX_EXCEPTIONS} ngoại lệ.")
    return out


class Ctx:
    """Gom thống kê + dòng ví dụ của từng quy tắc trong một lần build, và tra ngoại lệ."""

    def __init__(self, exceptions: list[dict], masked_words: list[str] | None = None) -> None:
        self.exc = {(e["rule"], e["line"]) for e in exceptions}
        self.unmask_patterns = html_import.build_unmask_patterns(masked_words or [])
        self.masked_unknown: dict[str, dict] = {}   # từ còn bị che chưa khôi phục được → {count, chapter, title, example}
        self.stats: dict = {}
        self.events: dict[str, list[dict]] = {}
        self.chapter = 0
        self.title = ""

    def keep(self, rule: str, line: str) -> bool:
        return (rule, line) in self.exc

    def hit(self, rule: str, key: str | None, before, after: str = "") -> None:
        _stat(self.stats, rule)
        ev = self.events.setdefault(rule, [])
        if len(ev) < MAX_EXAMPLES:
            ev.append({"chapter": self.chapter, "title": self.title, "key": key, "before": before, "after": after})


def boilerplate_lines(chapters: list[Raw]) -> set[str]:
    """Dòng dài (≥ 20 ký tự) xuất hiện ở ≥ max(3, nửa số chương) chương: đầu/cuối trang của web truyện."""
    n = len(chapters)
    if n < 3:
        return set()
    seen: dict[str, int] = {}
    for ch in chapters:
        for line in {l.strip() for l in ch.lines if len(l.strip()) >= 20}:
            seen[line] = seen.get(line, 0) + 1
    need = max(3, math.ceil(n / 2))
    return {l for l, c in seen.items() if c >= need}


def clean_lines(lines: list[str], cfg: dict, ctx: Ctx, boiler: set[str]) -> list[str]:
    rules = cfg["rules"]
    pause = f"[nghỉ {cfg['separator_pause']:g}s]"
    out: list[str] = []
    for raw in lines:
        s0 = s = raw.strip()
        if s and rules["unmask"] and "*" in s and not ctx.keep("unmask", s0):
            t = html_import.unmask(s, ctx.unmask_patterns)
            if t != s:
                ctx.hit("unmask", s0, s0, t)
                s = t
        if s and rules["join_numbers"] and not ctx.keep("join_numbers", s0):
            t = html_import.join_split_numbers(s)
            if t != s:
                ctx.hit("join_numbers", s0, s0, t)
                s = t
        if s and rules["quotes"] and not ctx.keep("quotes", s0):
            t = s.translate(_QUOTES)
            if t != s:
                ctx.hit("quotes", s0, s0, t)
                s = t
        if s and rules["ellipsis"] and not ctx.keep("ellipsis", s0):
            t = _ELLIPSIS.sub("…", s)
            if t != s:
                ctx.hit("ellipsis", s0, s0, t)
                s = t
        if s and rules["url_lines"] and _URL.search(s) and not ctx.keep("url_lines", s0):
            ctx.hit("url_lines", s0, s0); continue
        if s and rules["credit_lines"] and _CREDIT.search(s) and not ctx.keep("credit_lines", s0):
            ctx.hit("credit_lines", s0, s0); continue
        if s and rules["separators"] and _SEP.match(s) and not ctx.keep("separators", s0):
            out.append(pause); ctx.hit("separators", s0, s0, pause); continue
        if s and rules["dup_lines"] and s in boiler and not ctx.keep("dup_lines", s0):
            ctx.hit("dup_lines", s0, s0); continue
        out.append(s)
    if rules["dup_lines"]:  # dòng dài liền nhau giống hệt nhau
        dedup: list[str] = []
        for s in out:
            if s and len(s) >= 12 and dedup and dedup[-1] == s and not ctx.keep("dup_lines", s):
                ctx.hit("dup_lines", s, s); continue
            dedup.append(s)
        out = dedup
    if rules["join_lines"]:  # gộp dòng bị ngắt giữa câu
        joined: list[str] = []
        for s in out:
            prev = joined[-1] if joined else ""
            if (prev and s and prev[-1] not in _TERMINATORS and not _PAUSE_LINE.match(prev) and not _PAUSE_LINE.match(s)
                    and (s[0].islower() or s[0] in ",;.)") and not ctx.keep("join_lines", s)):
                merged = f"{prev} {s}"
                ctx.hit("join_lines", s, [prev, s], merged)
                joined[-1] = merged; continue
            joined.append(s)
        out = joined
    text = "\n".join(out)
    for r in cfg["custom"]:
        if r["enabled"]:
            rx = re.compile(r["pattern"], re.MULTILINE)
            for m in rx.finditer(text):
                try:
                    after = m.expand(r["replace"])
                except (re.error, IndexError):
                    after = r["replace"]
                ctx.hit("custom", None, m.group(0)[:300], after[:300])
            text = rx.sub(r["replace"], text)
    if rules["blank_lines"]:  # mỗi dòng là một đoạn văn
        lines = text.strip("\n").split("\n") if text.strip("\n") else []
        for i, s in enumerate(lines):
            if not s and 0 < i < len(lines) - 1:
                ctx.hit("blank_lines", None, f"(dòng trống giữa «{lines[i - 1][-40:]}» và «{next((x for x in lines[i + 1:] if x), '')[:40]}»)")
        lines = [s for s in lines if s]
    else:
        text = re.sub(r"\n{3,}", "\n\n", text).strip("\n")  # tối đa một dòng trống giữa các đoạn
        lines = text.split("\n") if text else []
    if rules["separators"]:  # ngăn cảnh ở đầu / cuối chương không ngăn gì; ngăn cảnh liên tiếp chỉ giữ một
        tidy: list[str] = []
        for s in lines:
            if _PAUSE_LINE.match(s) and (not tidy or _PAUSE_LINE.match(tidy[-1])):
                continue
            tidy.append(s)
        while tidy and _PAUSE_LINE.match(tidy[-1]):
            tidy.pop()
        lines = tidy
    if rules["unmask"]:  # từ còn dấu * mà từ điển chưa có: báo để người dùng điền "từ đúng là…"
        for s in lines:
            if "*" in s and not _PAUSE_LINE.match(s):
                for tok in html_import.find_masked(s):
                    e = ctx.masked_unknown.setdefault(tok, {"count": 0, "chapter": ctx.chapter, "title": ctx.title, "example": s[:300]})
                    e["count"] += 1
    return lines


def _clean_doc_chars(d: Doc, ctx: Ctx) -> None:
    """Quy tắc control_chars: chuẩn hoá từng dòng (ngoại lệ thì giữ nguyên dòng đó)."""
    text = d.text.replace("\r\n", "\n").replace("\r", "\n")
    new = _CTRL.sub("", unicodedata.normalize("NFC", text.replace("\u00a0", " ").replace("\u3000", " ")))
    if new == text:
        d.text = text
        return
    ctx.title = d.name
    old_lines, new_lines = text.split("\n"), new.split("\n")
    for k, (o, n) in enumerate(zip(old_lines, new_lines)):
        if o != n:
            key = o.strip()
            if ctx.keep("control_chars", key):
                new_lines[k] = o
            else:
                ctx.hit("control_chars", key, key, n.strip())
    d.text = "\n".join(new_lines)


def load_masked() -> list[str]:
    """Từ điển từ bị che: data/masked_words.json; chưa có thì khởi tạo từ scripts/masked_words.txt."""
    try:
        return [str(w) for w in json.loads(MASKED_PATH.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        words = html_import.load_masked_words(MASKED_SEED)
        MASKED_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write_json(MASKED_PATH, words)
        return words


def add_masked_word(masked: str, correct: str) -> list[str]:
    """Thêm `correct` vào từ điển nếu `masked` đúng là nó bị che bớt chữ (m**n → muốn). Raise BookError nếu không khớp."""
    masked, correct = unicodedata.normalize("NFC", masked.strip()), unicodedata.normalize("NFC", correct.strip())
    if not html_import.masked_matches(masked, correct):
        raise BookError(f"'{correct}' không khớp với '{masked}': các chữ không bị che phải giống nhau và số chữ phải bằng nhau.")
    with _lock:
        words = load_masked()
        if correct.lower() not in {w.lower() for w in words}:
            words.append(correct)
            _write_json(MASKED_PATH, words)
    return words


def build(docs: list[Doc], settings: dict) -> dict:
    """Tách chương + làm sạch → {"chapters": [{n, title, text}], "stats": {...}, "rules": {tên: {count, examples}},
    "dropped": số chương rỗng bị bỏ}. settings: {"split": {regex, mode, ops}, "clean": {...}, "exceptions": [...]}."""
    split, clean = settings["split"], validate_clean(settings["clean"])
    if split["mode"] not in ("regex", "per_file"):
        raise BookError("mode phải là 'regex' hoặc 'per_file'.")
    ctx = Ctx(validate_exceptions(settings.get("exceptions")), load_masked() if clean["rules"]["unmask"] else [])
    for d in docs:
        if clean["rules"]["control_chars"]:
            _clean_doc_chars(d, ctx)
        else:
            d.text = d.text.replace("\r\n", "\n").replace("\r", "\n")
    raw = (split_per_file if split["mode"] == "per_file" else split_regex)(docs, split["regex"])
    raw = apply_ops(raw, split.get("ops") or [])
    boiler = boilerplate_lines(raw) if clean["rules"]["dup_lines"] else set()
    chapters, dropped = [], 0
    for i, ch in enumerate(raw):
        ctx.chapter, ctx.title = len(chapters) + 1, ch.title
        body = clean_lines(ch.lines, clean, ctx, boiler)
        text = "\n".join(body)
        title = ch.title
        if not title and i == 0:  # phần trước chương đầu tiên
            if len(text) < MIN_INTRO_CHARS:
                dropped += bool(text); continue
            title = "Mở đầu"
        if len(text) < MIN_CHAPTER_CHARS:
            dropped += 1; continue
        chapters.append({"n": len(chapters) + 1, "title": title, "text": text, "raw": i})
    rules = {name: {"count": ctx.stats.get(name, 0), "examples": ctx.events.get(name, [])}
             for name in [n for n, _ in RULES] + ["custom"] if ctx.stats.get(name)}
    unknown = [{"word": w, **v} for w, v in sorted(ctx.masked_unknown.items(), key=lambda kv: (-kv[1]["count"], kv[0]))][:200]
    return {"chapters": chapters, "stats": ctx.stats, "rules": rules, "dropped": dropped, "masked_unknown": unknown,
            "warnings": html_warnings(docs)}


def overrides(book: dict, body: dict) -> dict:
    """Cài đặt hiệu lực = cài đặt đã lưu, ghi đè bởi body (regex, mode, ops, clean, exceptions) — dùng cho xem trước."""
    split = dict(book["split"])
    for k in ("regex", "mode", "ops", "selector"):
        if body.get(k) is not None:
            split[k] = body[k]
    if "selector" in split:
        split["selector"] = validate_selector(split["selector"])
    exceptions = body["exceptions"] if body.get("exceptions") is not None else book.get("exceptions", [])
    return {"split": split, "clean": body.get("clean") or book["clean"], "exceptions": exceptions}


def summarize(built: dict) -> list[dict]:
    return [{"n": c["n"], "title": c["title"], "chars": len(c["text"]), "est_seconds": round(len(c["text"]) / CHARS_PER_SEC),
             "raw": c["raw"], "head": c["text"][:120].replace("\n", " ")} for c in built["chapters"]]


def confirm(book_id: str, built: dict, settings: dict) -> dict:
    """Ghi chapters/ (thay toàn bộ chương cũ) và lưu cài đặt tách/làm sạch vào book.json."""
    if not built["chapters"]:
        raise BookError("Không tìm thấy chương nào. Hãy chỉnh regex hoặc chọn chế độ 'mỗi file một chương'.")
    book = get(book_id)
    with _lock:
        d = _dir(book_id) / "chapters"
        shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(audio_dir(book_id), ignore_errors=True)  # chương đánh số lại: audio cũ không còn khớp
        d.mkdir()
        for c in built["chapters"]:
            (d / f"{c['n']:04d}.txt").write_text(c["text"], encoding="utf-8")
            _write_json(d / f"{c['n']:04d}.json", {"n": c["n"], "title": c["title"], "chars": len(c["text"]), "status": "pending"})
        book["split"], book["clean"] = settings["split"], validate_clean(settings["clean"])
        book["exceptions"] = validate_exceptions(settings.get("exceptions"))
        book["status"] = "ready"
        book["chapters"] = {"count": len(built["chapters"]), "chars": sum(len(c["text"]) for c in built["chapters"])}
        _write_json(_dir(book_id) / "book.json", book)
    return book


def audio_dir(book_id: str) -> Path:
    return _dir(book_id) / "audio"


def chapter_audio(book_id: str, n: int) -> Path:
    """File audio hoàn chỉnh của chương (FLAC 48 kHz mono, nguồn gốc cho MP3/m4b)."""
    return audio_dir(book_id) / f"{n:04d}.flac"


def parts_dir(book_id: str, n: int) -> Path:
    """Các đoạn đã dựng của chương đang làm dở (xoá khi chương xong)."""
    return audio_dir(book_id) / f"{n:04d}.parts"


def update_chapter(book_id: str, n: int, **fields) -> dict:
    """Ghi thêm trường vào chapters/<nnnn>.json (status, segments, audio_seconds…). Giá trị None thì xoá trường."""
    path = _dir(book_id) / "chapters" / f"{n:04d}.json"
    with _lock:
        meta = json.loads(path.read_text(encoding="utf-8"))
        for k, v in fields.items():
            if v is None:
                meta.pop(k, None)
            else:
                meta[k] = v
        _write_json(path, meta)
    return meta


def list_chapters(book_id: str) -> list[dict]:
    out = []
    for p in sorted((_dir(book_id) / "chapters").glob("*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        out.append({**c, "est_seconds": round(c["chars"] / CHARS_PER_SEC)})
    return out


def chapter_text(book_id: str, n: int) -> tuple[dict, str]:
    d = _dir(book_id) / "chapters"
    meta_path, txt = d / f"{n:04d}.json", d / f"{n:04d}.txt"
    if not meta_path.is_file() or not txt.is_file():
        raise NotFound(f"{book_id}/{n}")
    return json.loads(meta_path.read_text(encoding="utf-8")), txt.read_text(encoding="utf-8")


def reading_text(book: dict, meta: dict, body: str) -> str:
    """Văn bản đưa cho engine: tiêu đề chương (nếu bật đọc tiêu đề) + thân chương."""
    return f"{meta['title']}\n\n{body}" if book.get("read_title", True) and meta.get("title") else body


PARAGRAPH_PAUSE_S = 0.6   # mặc định: khoảng lặng giữa hai đoạn văn
TITLE_PAUSE_S = 1.2       # mặc định: khoảng lặng sau tiêu đề chương
_PAUSE_TAG = re.compile(r"^\[nghỉ\s*([\d.,]+)\s*s?\]$", re.IGNORECASE)


def pauses(book: dict) -> tuple[float, float]:
    """(paragraph_pause_s, title_pause_s) của truyện; truyện cũ chưa có thì dùng mặc định."""
    return (float(book.get("paragraph_pause_s", PARAGRAPH_PAUSE_S)), float(book.get("title_pause_s", TITLE_PAUSE_S)))


def validate_pause(value, label: str, high: float) -> float:
    """0 (không nghỉ) hoặc 0.1–high giây."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise BookError(f"{label} phải là số giây.")
    if v != 0 and not 0.1 <= v <= high:
        raise BookError(f"{label} phải là 0 (không nghỉ) hoặc từ 0.1 đến {high:g} giây.")
    return round(v, 1)


def paragraphs(book: dict, meta: dict, body: str, title: bool = True) -> list[list]:
    """Chương → [[văn bản đoạn, giây nghỉ sau đoạn]]: tiêu đề (nếu bật đọc tiêu đề) + mỗi dòng của thân chương là một đoạn văn.
    Dòng `[nghỉ Ns]` (dấu ngăn cảnh) không phải đoạn: nó thay khoảng nghỉ sau đoạn trước đó."""
    pp, tp = pauses(book)
    out: list[list] = []
    if title and book.get("read_title", True) and meta.get("title"):
        out.append([meta["title"].strip(), tp])
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        m = _PAUSE_TAG.match(s)
        if m:
            if out:
                out[-1][1] = float(m.group(1).replace(",", "."))
            continue
        out.append([s, pp])
    return out


def excerpt_paras(paras: list[list], limit: int = 300, offset: float = 0.0) -> list[list]:
    """Các đoạn văn đầu tiên đủ ~limit ký tự, bắt đầu ở đoạn gần vị trí `offset` (0..1) của chương; đoạn cuối quá dài
    (> 1,5 × limit) bị cắt ở ranh giới câu."""
    start = 0
    if offset > 0 and paras:
        goal, acc = offset * sum(len(t) + 1 for t, _ in paras), 0
        start = len(paras) - 1
        for k, (t, _) in enumerate(paras):
            if acc >= goal:
                start = k
                break
            acc += len(t) + 1
    out, total = [], 0
    for t, g in paras[start:]:
        if total >= limit:
            break
        if total + len(t) > limit * 1.5:
            room = int(limit * 1.5) - total
            cut = max(t.rfind(c, 0, room) for c in ".!?…")
            out.append([t[: cut + 1] if cut > 0 else t[: max(limit - total, 1)], g])
            break
        out.append([t, g])
        total += len(t)
    return out


def disk_usage(book_id: str) -> dict:
    """Dung lượng (byte) đã dùng của truyện: audio gốc (FLAC + đoạn dở), file xuất (mp3 cache, zip, m4b), nguồn + văn bản chương."""
    root = _dir(book_id)

    def size(path: Path) -> int:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0

    audio, export = size(root / "audio"), size(root / "export")
    total = size(root)
    return {"total": total, "audio": audio, "export": export, "other": total - audio - export}


def purgeable(book_id: str) -> tuple[int, int]:
    """(số chương, số byte) FLAC có thể xoá: chương đã dựng xong và đã xuất (MP3 zip hoặc m4b) ít nhất một lần."""
    n = size = 0
    for c in list_chapters(book_id):
        f = chapter_audio(book_id, c["n"])
        if c.get("status") == "done" and c.get("exported") and f.is_file():
            n += 1
            size += f.stat().st_size
    return n, size


def purge_exported(book_id: str) -> tuple[int, int]:
    """Xoá FLAC của chương đã xuất; chương chuyển sang status "exported" (cần Tạo lại nếu muốn sửa hoặc xuất lại)."""
    n = freed = 0
    for c in list_chapters(book_id):
        f = chapter_audio(book_id, c["n"])
        if c.get("status") == "done" and c.get("exported") and f.is_file():
            freed += f.stat().st_size
            f.unlink()
            update_chapter(book_id, c["n"], status="exported")
            n += 1
    return n, freed


def iter_chapters(book_id: str):
    """(n, văn bản đã làm sạch) của từng chương, theo thứ tự."""
    for p in sorted((_dir(book_id) / "chapters").glob("*.txt")):
        yield int(p.stem), p.read_text(encoding="utf-8")
