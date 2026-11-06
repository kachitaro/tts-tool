"""Smoke test chế độ Sách nói (gọi từ scripts/smoke_test.sh): in "PASS  tên" / "FAIL  tên — lý do" mỗi bước.

Dùng: python scripts/smoke_books.py <base_url>
Phần module (dò encoding, làm sạch, EPUB) chạy trực tiếp trên books.py với data tạm; phần API chạy trên server đang chạy.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

os.environ["TTS_DATA_DIR"] = tempfile.mkdtemp()  # chỉ cho phần module; server có data riêng
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

import books  # noqa: E402

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
client = httpx.Client(timeout=180)
fails = 0


def check(name: str, fn) -> None:
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as ex:  # noqa: BLE001 — in lý do rồi đi tiếp
        fails += 1
        print(f"FAIL  {name} — {type(ex).__name__}: {str(ex)[:200]}")


# ───────────── dữ liệu mẫu ─────────────
STORY = """Tên truyện: Đấu Phá
Nguồn: truyenfull.vn
Truyện được dịch bởi nhóm ABC

Chương 1: Khởi đầu
Hắn đứng lặng người nhìn về phía xa, trong lòng
dâng lên một cảm giác khó tả.
"Ngươi là ai?" Một giọng nói vang lên.
Đọc truyện tại https://truyenfull.vn/abc
***
Màn đêm buông xuống... Hắn thở dài。。。
“Đi thôi.”

Chương 2:
Sáng hôm sau, mặt trời lên cao. Hắn thức dậy sớm và chuẩn bị lên đường tới thành phố.
* * *
Chương XII
Chuyện cũ được nhắc lại. Hắn nhớ về thời thơ ấu và những người bạn đã khuất, lòng nặng trĩu.
Quyển 2 Chương 5
Mở màn quyển hai với nhiều biến cố bất ngờ xảy ra khiến cả thành phố rúng động không thôi.
♦
Kết thúc đoạn này ở đây nhé các bạn.
第12章 开始
这是中文章节的内容，用来测试章节分割是否正确，需要足够长的文本。
"""
VI = "Chương 1: Khởi đầu\nHôm nay trời đẹp lắm, tôi muốn đi dạo quanh hồ cùng bạn bè vào buổi chiều.\nẶ ặ ẳ ỹ\n" * 10
ZH = "第1章 开始\n今天天气很好，我想和朋友们一起去湖边散步。\n他静静地站在那里，望着远方。\n" * 10
TONES = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}


def enc1258(text: str) -> bytes:
    out = b""
    for c in unicodedata.normalize("NFC", text):
        try:
            out += c.encode("cp1258")
            continue
        except UnicodeEncodeError:
            pass
        d = unicodedata.normalize("NFD", c)
        tone = next((m for m in d[1:] if m in TONES), "")
        base = unicodedata.normalize("NFC", d[0] + "".join(m for m in d[1:] if m not in TONES))
        out += base.encode("cp1258") + (tone.encode("cp1258") if tone else b"")
    return out


def make_epub() -> bytes:
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w")
    z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
    z.writestr("OEBPS/content.opf", '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Truyện EPUB</dc:title><dc:creator>Tác giả A</dc:creator></metadata><manifest><item id="a" href="c1.xhtml" media-type="application/xhtml+xml"/><item id="b" href="c2.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
    z.writestr("OEBPS/c1.xhtml", '<html><body><h1>Chương 1: Mở đầu</h1><p>Hắn đứng lặng người nhìn về phía xa và thở dài một hơi thật sâu.</p></body></html>')
    z.writestr("OEBPS/c2.xhtml", '<html><body><h2>Chương 2: Tiếp</h2><p>Sáng hôm sau mặt trời lên cao và hắn lên đường đi về phía thành phố.</p></body></html>')
    z.close()
    return buf.getvalue()


# ───────────── module: encoding, làm sạch, EPUB ─────────────
def t_encodings() -> None:
    cases = {"utf-8": (VI.encode(), "utf-8", VI), "utf-8 BOM": (b"\xef\xbb\xbf" + VI.encode(), "utf-8", VI),
             "utf-16 BOM": (VI.encode("utf-16"), "utf-16", VI), "utf-16-le": (VI.encode("utf-16-le"), "utf-16", VI),
             "utf-16-be": (VI.encode("utf-16-be"), "utf-16", VI), "gb18030": (ZH.encode("gb18030"), "gb18030", ZH),
             "windows-1258": (enc1258(VI), "windows-1258", VI)}
    for name, (data, want_enc, want_text) in cases.items():
        text, enc = books.decode_bytes(data)
        assert enc == want_enc, f"{name}: dò ra {enc}"
        assert text == unicodedata.normalize("NFC", want_text), f"{name}: nội dung sai"


def build(settings=None, docs=None):
    return books.build(docs or [books.Doc("t", STORY)], settings or books.default_settings())


def t_default_regex_and_clean() -> None:
    b = build()
    titles = [c["title"] for c in b["chapters"]]
    assert titles == ["Chương 1: Khởi đầu", "Chương 2:", "Chương XII", "Quyển 2 Chương 5", "第12章 开始"], titles
    # "Nguồn: truyenfull.vn" bị quy tắc URL bắt trước (tên miền), "Truyện được dịch bởi" bị quy tắc credit
    assert b["stats"] == {"url_lines": 2, "credit_lines": 1, "separators": 3, "join_lines": 1}, b["stats"]
    c1 = b["chapters"][0]["text"]
    assert "http" not in c1 and "Nguồn" not in c1 and "dâng lên" in c1 and "trong lòng dâng" in c1, c1  # URL bỏ, dòng bị ngắt được gộp
    assert "[nghỉ 1.5s]" in c1 and '"Đi thôi."' in c1 and "buông xuống…" in c1, c1                   # ngăn cảnh, ngoặc kép, ba chấm


def t_rule_toggles() -> None:
    s = books.default_settings()
    s["clean"]["rules"]["separators"] = False
    assert "[nghỉ" not in "\n".join(c["text"] for c in build(s)["chapters"])
    s = books.default_settings()
    s["clean"]["separator_pause"] = 2.5
    assert "[nghỉ 2.5s]" in build(s)["chapters"][0]["text"]
    s = books.default_settings()
    s["clean"]["custom"] = [{"pattern": "Hắn", "replace": "Anh ta", "enabled": True}]
    assert "Anh ta đứng lặng" in build(s)["chapters"][0]["text"]
    try:
        books.validate_clean({"custom": [{"pattern": "("}]})
    except books.BookError:
        return
    raise AssertionError("regex sai phải bị từ chối")


def t_separators() -> None:
    seps = ["***", "* * *", "---", "~~~", "ooo", "♦", "◆ ◆ ◆", "======", "— — —", "OOO"]
    for sep in seps:
        doc = books.Doc("t", f"Chương 1\nDòng văn bản thứ nhất đủ dài để giữ lại.\n{sep}\nDòng văn bản thứ hai đủ dài để giữ lại.")
        text = books.build([doc], books.default_settings())["chapters"][0]["text"]
        assert "[nghỉ 1.5s]" in text, f"{sep!r} → {text!r}"
    keep = books.build([books.Doc("t", "Chương 1\nOoo, anh ấy nói vậy đấy nhé các bạn.\n-- Xin chào.")], books.default_settings())["chapters"][0]["text"]
    assert "[nghỉ" not in keep, keep  # câu thường bắt đầu bằng "Ooo," / "--" có chữ không bị coi là ngăn cảnh


def t_ops() -> None:
    s = books.default_settings()
    s["split"]["ops"] = [{"op": "merge", "i": 1}]
    assert len(build(s)["chapters"]) == 4
    s["split"]["ops"] = [{"op": "split", "i": 1, "contains": "Màn đêm", "title": "Phần 2"}]
    chs = build(s)["chapters"]
    assert len(chs) == 6 and chs[1]["title"] == "Phần 2", [c["title"] for c in chs]


def t_epub() -> None:
    docs, meta = books.read_epub(make_epub())
    assert meta == {"title": "Truyện EPUB", "author": "Tác giả A"} and len(docs) == 2, (meta, len(docs))
    assert [c["title"] for c in build(docs=docs)["chapters"]] == ["Chương 1: Mở đầu", "Chương 2: Tiếp"]
    try:
        books.read_epub(b"not a zip")
    except books.BookError:
        return
    raise AssertionError("EPUB hỏng phải bị từ chối")


# ───────────── API ─────────────
def j(r: httpx.Response, status: int = 200):
    assert r.status_code == status, f"HTTP {r.status_code}: {r.text[:150]}"
    return r.json()


state: dict = {}


def t_import_txt() -> None:
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("truyen.txt", STORY.encode("utf-16"), "text/plain"))],
                      data={"title": "Truyện smoke", "author": "Tôi"}))
    assert d["status"] == "draft" and d["sources"][0]["encoding"] == "utf-16" and d["split"]["mode"] == "regex", d
    state["id"] = d["id"]


def t_preview() -> None:
    p = j(client.post(f"{B}/api/books/{state['id']}/preview"))
    assert len(p["chapters"]) == 5 and p["stats"]["separators"] == 3 and p["dropped"] == 1, p["stats"]
    assert client.get(f"{B}/api/books/{state['id']}").json()["status"] == "draft"  # xem trước không ghi gì


def t_preview_errors() -> None:
    assert client.post(f"{B}/api/books/{state['id']}/preview", json={"regex": "("}).status_code == 400
    assert client.post(f"{B}/api/books/{state['id']}/preview", json={"mode": "x"}).status_code == 400
    assert client.post(f"{B}/api/books/{state['id']}/preview", json={"ops": [{"op": "split", "i": 1, "contains": "không có đâu"}]}).status_code == 400
    assert client.patch(f"{B}/api/books/{state['id']}", json={"clean": {"custom": [{"pattern": "("}]}}).status_code == 400


def t_preview_ops() -> None:
    p = j(client.post(f"{B}/api/books/{state['id']}/preview", json={"ops": [{"op": "merge", "i": 1}]}))
    assert len(p["chapters"]) == 4 and p["chapters"][0]["raw"] == 1, p["chapters"][:1]


def t_confirm_and_chapters() -> None:
    b = j(client.post(f"{B}/api/books/{state['id']}/chapters"))
    assert b["status"] == "ready" and b["chapters"]["count"] == 5, b["chapters"]
    chs = j(client.get(f"{B}/api/books/{state['id']}/chapters"))
    assert [c["status"] for c in chs] == ["pending"] * 5 and all(c["est_seconds"] > 0 for c in chs)
    c1 = j(client.get(f"{B}/api/books/{state['id']}/chapters/1"))
    assert "http" not in c1["text"] and "[nghỉ 1.5s]" in c1["text"] and c1["reading_text"].startswith("Chương 1: Khởi đầu\n\n"), c1["reading_text"][:80]
    j(client.get(f"{B}/api/books/{state['id']}/chapters/99"), 404)


def t_settings() -> None:
    d = j(client.patch(f"{B}/api/books/{state['id']}", json={"read_title": False, "speed": 100, "clean": {"separator_pause": 2, "custom": [
        {"pattern": "Hắn", "replace": "Anh ta", "enabled": True}]}}))
    assert d["read_title"] is False and d["speed"] == 100 and d["clean"]["separator_pause"] == 2
    j(client.post(f"{B}/api/books/{state['id']}/chapters"))  # tách lại với cài đặt đã lưu
    c1 = j(client.get(f"{B}/api/books/{state['id']}/chapters/1"))
    assert "[nghỉ 2s]" in c1["text"] and "Anh ta đứng lặng" in c1["text"] and not c1["reading_text"].startswith("Chương"), c1["reading_text"][:80]
    client.patch(f"{B}/api/books/{state['id']}", json={"speed": 0})


def t_sample() -> None:
    r = client.get(f"{B}/api/books/{state['id']}/chapters/2/sample")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF" and len(r.content) > 20000, (r.status_code, len(r.content))


def t_multi_files() -> None:
    files = [("files", (f"chuong{i}.txt", f"Nội dung chương số {i} đủ dài để không bị bỏ đi vì quá ngắn nhé các bạn.".encode(), "text/plain")) for i in (10, 2, 1)]
    d = j(client.post(f"{B}/api/books/import", files=files, data={"title": "Nhiều file smoke"}))
    assert [s["name"] for s in d["sources"]] == ["chuong1.txt", "chuong2.txt", "chuong10.txt"] and d["split"]["mode"] == "per_file", d["sources"]
    p = j(client.post(f"{B}/api/books/{d['id']}/preview"))
    assert [c["title"] for c in p["chapters"]] == ["chuong1", "chuong2", "chuong10"], p["chapters"]
    state["multi"] = d["id"]


def t_epub_import() -> None:
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("b.epub", make_epub(), "application/epub+zip"))]))
    assert d["title"] == "Truyện EPUB" and d["author"] == "Tác giả A", (d["title"], d["author"])
    p = j(client.post(f"{B}/api/books/{d['id']}/preview"))
    assert [c["title"] for c in p["chapters"]] == ["Chương 1: Mở đầu", "Chương 2: Tiếp"]
    state["epub"] = d["id"]


def t_bad_imports() -> None:
    assert client.post(f"{B}/api/books/import", files=[("files", ("a.pdf", b"x", "application/pdf"))]).status_code == 400
    assert client.post(f"{B}/api/books/import", files=[("files", ("a.epub", b"xx", "application/epub+zip"))]).status_code == 400
    assert client.post(f"{B}/api/books/zzz/preview").status_code == 404


def t_list_delete() -> None:
    titles = {b["title"] for b in j(client.get(f"{B}/api/books"))}
    assert {"Truyện smoke", "Nhiều file smoke", "Truyện EPUB"} <= titles, titles
    for k in ("id", "multi", "epub"):
        j(client.delete(f"{B}/api/books/{state[k]}"))
    assert j(client.get(f"{B}/api/books")) == []
    j(client.get(f"{B}/api/books/{state['id']}"), 404)


for name, fn in [
    ("sách nói: dò encoding UTF-8 / UTF-16 / GB18030 / Windows-1258", t_encodings),
    ("sách nói: regex mặc định nhận Chương 12 / XII / 第12章 / Quyển 2 Chương 5 + làm sạch", t_default_regex_and_clean),
    ("sách nói: bật/tắt từng quy tắc, nghỉ ngăn cảnh chỉnh được, quy tắc tuỳ chỉnh", t_rule_toggles),
    ("sách nói: các dạng dấu ngăn cảnh → [nghỉ 1.5s], không nhầm câu thường", t_separators),
    ("sách nói: gộp / tách chương thủ công", t_ops),
    ("sách nói: đọc EPUB (thư viện chuẩn), EPUB hỏng bị từ chối", t_epub),
    ("API: nhập .txt UTF-16 → truyện nháp", t_import_txt),
    ("API: xem trước chương (không ghi gì ra đĩa)", t_preview),
    ("API: regex / mode / thao tác tách / quy tắc sai → 400", t_preview_errors),
    ("API: xem trước với gộp thủ công", t_preview_ops),
    ("API: xác nhận tách chương, danh sách chương, đọc chương, 404", t_confirm_and_chapters),
    ("API: cài đặt (tắt đọc tiêu đề, nghỉ ngăn cảnh 2s, quy tắc tuỳ chỉnh) áp dụng khi tách lại", t_settings),
    ("API: ▶ nghe thử đầu chương trả WAV", t_sample),
    ("API: nhập nhiều .txt → mỗi file một chương, sắp xếp tự nhiên", t_multi_files),
    ("API: nhập .epub lấy tên truyện / tác giả", t_epub_import),
    ("API: file không hỗ trợ / EPUB hỏng / truyện không tồn tại", t_bad_imports),
    ("API: danh sách và xoá truyện", t_list_delete),
]:
    check(name, fn)

sys.exit(1 if fails else 0)
