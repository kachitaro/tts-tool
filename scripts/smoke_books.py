"""Smoke test chế độ Sách nói (gọi từ scripts/smoke_test.sh): in "PASS  tên" / "FAIL  tên — lý do" mỗi bước.

Dùng: python scripts/smoke_books.py <base_url>
Phần module (dò encoding, làm sạch, EPUB) chạy trực tiếp trên books.py với data tạm; phần API chạy trên server đang chạy.
"""

from __future__ import annotations

import atexit
import io
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

os.environ["TTS_DATA_DIR"] = tempfile.mkdtemp(prefix="smoke_books_")  # chỉ cho phần module; server có data riêng
atexit.register(shutil.rmtree, os.environ["TTS_DATA_DIR"], ignore_errors=True)   # dọn khi thoát
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

import books  # noqa: E402
import lexicon  # noqa: E402
import narrate  # noqa: E402
from engines.registry import ENGINES  # noqa: E402

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
    assert b["stats"] == {"url_lines": 2, "credit_lines": 1, "separators": 3, "ellipsis": 1, "quotes": 1, "join_lines": 1}, b["stats"]
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


# ───────────── 6a bổ sung: tác động từng quy tắc + ngoại lệ ─────────────
def t_rule_impact_module() -> None:
    b = build()
    r = b["rules"]
    assert r["separators"]["count"] == 3 and r["separators"]["examples"][0]["before"] == "***" and r["separators"]["examples"][0]["chapter"] == 1, r["separators"]
    jn = r["join_lines"]["examples"][0]
    assert isinstance(jn["before"], list) and len(jn["before"]) == 2 and jn["after"] == " ".join(jn["before"]), jn  # 2 dòng trước → 1 dòng sau
    assert r["url_lines"]["count"] == 2 and r["credit_lines"]["examples"][0]["before"].startswith("Truyện được dịch"), r["credit_lines"]
    assert r["ellipsis"]["examples"][0]["after"].endswith("…") and r["quotes"]["examples"][0]["after"] == '"Đi thôi."'
    many = "Chương 1\n" + "\n".join(f"Đọc truyện tại https://example.com/{i}" for i in range(80)) + "\nDòng văn bản giữ lại đủ dài để không bị bỏ nhé."
    b = books.build([books.Doc("t", many)], books.default_settings())
    assert b["rules"]["url_lines"]["count"] == 80 and len(b["rules"]["url_lines"]["examples"]) == 50, b["rules"]["url_lines"]["count"]


def t_exceptions_module() -> None:
    s = books.default_settings()
    s["exceptions"] = [{"rule": "separators", "line": "***"}, {"rule": "url_lines", "line": "Đọc truyện tại https://truyenfull.vn/abc"},
                       {"rule": "quotes", "line": "“Đi thôi.”"}]
    b = build(s)
    text = b["chapters"][0]["text"]
    assert "***" in text and "https://truyenfull.vn/abc" in text and "“Đi thôi.”" in text, text      # được giữ nguyên
    assert b["rules"]["separators"]["count"] == 2 and "url_lines" in b["rules"] and b["rules"]["url_lines"]["count"] == 1
    s["exceptions"] = [{"rule": "join_lines", "line": "dâng lên một cảm giác khó tả."}]
    t = build(s)["chapters"][0]["text"]
    assert "trong lòng\ndâng lên" in t, t                                                          # dòng bị ngắt không bị gộp
    try:
        books.validate_exceptions([{"rule": "không_có", "line": "x"}])
    except books.BookError:
        return
    raise AssertionError("quy tắc không tồn tại phải bị từ chối")


def t_rule_impact_api() -> None:
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("r.txt", STORY.encode(), "text/plain"))], data={"title": "Quy tắc smoke"}))
    state["rules"] = d["id"]
    p = j(client.post(f"{B}/api/books/{d['id']}/preview"))
    assert p["rules"]["separators"]["count"] == 3 and p["rules"]["separators"]["examples"][0]["key"] == "***", p["rules"]["separators"]
    p = j(client.post(f"{B}/api/books/{d['id']}/preview", json={"exceptions": [{"rule": "separators", "line": "***"}]}))
    assert p["rules"]["separators"]["count"] == 2, p["rules"]["separators"]
    assert client.post(f"{B}/api/books/{d['id']}/preview", json={"exceptions": [{"rule": "x", "line": "y"}]}).status_code == 400
    j(client.post(f"{B}/api/books/{d['id']}/chapters", json={"exceptions": [{"rule": "separators", "line": "***"}]}))
    b = j(client.get(f"{B}/api/books/{d['id']}"))
    assert b["exceptions"] == [{"rule": "separators", "line": "***"}], b["exceptions"]
    assert "***" in j(client.get(f"{B}/api/books/{d['id']}/chapters/1"))["text"]
    j(client.post(f"{B}/api/books/{d['id']}/chapters"))  # xác nhận lại không gửi body: dùng ngoại lệ đã lưu
    assert "***" in j(client.get(f"{B}/api/books/{d['id']}/chapters/1"))["text"]
    j(client.delete(f"{B}/api/books/{d['id']}"))


# ───────────── 6b: lời thoại (10 ví dụ) ─────────────
DIALOGUE_CASES = [
    ('Hắn nói: “Đi thôi.” Rồi bỏ đi.', [("narr", "Hắn nói:"), ("dlg", "Đi thôi."), ("narr", "Rồi bỏ đi.")]),
    ('"Ngươi là ai?" Một giọng nói vang lên.', [("dlg", "Ngươi là ai?"), ("narr", "Một giọng nói vang lên.")]),
    ("– Đi đâu? – hắn hỏi.", [("dlg", "Đi đâu?"), ("narr", "hắn hỏi.")]),
    ("— Tôi đi đây — anh nói — rồi sẽ quay lại.", [("dlg", "Tôi đi đây"), ("narr", "anh nói"), ("dlg", "rồi sẽ quay lại.")]),
    ("- Chào em! - Chào anh.", [("dlg", "Chào em! Chào anh.")]),
    ('Thuật ngữ "Đấu Khí" rất phổ biến.', [("narr", 'Thuật ngữ "Đấu Khí" rất phổ biến.')]),
    ("Hắn lẩm bẩm “Không thể nào, không thể nào!” rồi im lặng.",
     [("narr", "Hắn lẩm bẩm"), ("dlg", "Không thể nào, không thể nào!"), ("narr", "rồi im lặng.")]),
    ('Hắn nói "đi thôi và cả nhà đều vui.', [("narr", "Hắn nói đi thôi và cả nhà đều vui.")]),
    ("“Đi đâu?” hắn hỏi. “Về nhà.” nàng đáp.",
     [("dlg", "Đi đâu?"), ("narr", "hắn hỏi."), ("dlg", "Về nhà."), ("narr", "nàng đáp.")]),
    ("Anh ấy sống ở Hà Nội - thủ đô.", [("narr", "Anh ấy sống ở Hà Nội - thủ đô.")]),
]


def t_dialogue_cases() -> None:
    bad = [(src, narrate.split_line(src), want) for src, want in DIALOGUE_CASES if narrate.split_line(src) != want]
    assert not bad, bad
    assert narrate.split_line("[nghỉ 1.5s]") == [("narr", "[nghỉ 1.5s]")] and narrate.split_line("   ") == []


def t_dialogue_runs() -> None:
    r = narrate.runs(narrate.split_text('Dòng một.\n– Đi đâu? – hắn hỏi.\n\n"Về nhà." Nàng cười.'))
    assert [(x.kind, x.text, x.new_line) for x in r] == [("narr", "Dòng một.", False), ("dlg", "Đi đâu?", True), ("narr", "hắn hỏi.", False),
                                                          ("dlg", "Về nhà.", True), ("narr", "Nàng cười.", False)], r


# ───────────── 6b: từ điển ─────────────
def E(match, replace="", before=0, after=0, whole=True, case=False):
    return {"match": match, "replace": replace, "pause_before": before, "pause_after": after, "whole_word": whole, "case_sensitive": case}


def t_lexicon_apply() -> None:
    ap = lexicon.apply
    assert ap("Hắn gặp Tiêu Viêm.", [E("Tiêu Viêm", "Tiêu Diễm")]) == "Hắn gặp Tiêu Diễm."
    assert ap("gặp Tiêu Viêm ở đó", [E("Tiêu Viêm", before=0.2)]) == "gặp [nghỉ 0.2s] Tiêu Viêm ở đó"
    assert ap("gặp Tiêu Viêm ở đó", [E("Tiêu Viêm", after=0.3)]) == "gặp Tiêu Viêm [nghỉ 0.3s] ở đó"
    assert ap("a Tiêu Viêm b", [E("Tiêu Viêm", "TV", 0.1, 0.1)]) == "a [nghỉ 0.1s] TV [nghỉ 0.1s] b"
    assert ap("Đấu Khí, đấu khí", [E("Đấu Khí", "X")]) == "X, X"                      # mặc định không phân biệt hoa thường
    assert ap("Đấu Khí, đấu khí", [E("Đấu Khí", "X", case=True)]) == "X, đấu khí"
    assert ap("Tiêu Viêm Đại Sư, Tiêu ViêmX", [E("Tiêu Viêm", "TV")]) == "TV Đại Sư, Tiêu ViêmX"   # nguyên từ
    assert ap("Tiêu ViêmX", [E("Tiêu Viêm", "TV", whole=False)]) == "TVX"
    assert ap("A rồi B", [E("A", "B"), E("B", "C")]) == "B rồi C"                       # một lượt: không nối tiếp A→B→C
    assert ap("Tiêu Viêm", [E("Tiêu Viêm", "truyện")], [E("Tiêu Viêm", "toàn cục")]) == "truyện"          # truyện thắng toàn cục
    assert ap("Tiêu Viêm Đại Sư", [E("Tiêu Viêm", "A")], [E("Tiêu Viêm Đại Sư", "B")]) == "B"             # cụm dài hơn thắng
    assert ap("không đổi", None, None) == "không đổi"


def t_lexicon_validate() -> None:
    for bad in ([E("")], [{"match": "x"}], [E("x", before=9)], [E("x", before=0.05)], [E("a" * 101, "b")], "không phải list"):
        try:
            lexicon.validate(bad)
        except lexicon.LexiconError:
            continue
        raise AssertionError(f"phải bị từ chối: {bad!r}")
    assert lexicon.validate([E("x", before=0.24)])[0]["pause_before"] == 0.2


NAMES = """Chương 1
Hắn nhìn Tiêu Viêm rồi cười. Tiêu Viêm bước vào Vân Lam Tông cùng Dược Lão.
Anh Tiêu Viêm đáp: Nhưng Tiêu Viêm không sợ.
– Dược Lão ở đâu? – Tiêu Viêm hỏi.
Hắn nhìn Vân Lam Tông, rồi nhìn Dược Lão, rồi nhìn Vân Lam Tông.
NASA bay qua Hà Nội. Thiên Địa Huyền Hoàng Vũ Trụ lặp lại.
"""


def t_suggest_terms() -> None:
    terms = lexicon.suggest_terms([(1, NAMES), (2, NAMES)], min_count=2)
    got = {t.phrase: t.count for t in terms}
    # "Tiêu Viêm": 2 lần/chương mid-sentence (sau "nhìn", sau "Anh"→bỏ từ dừng, sau "Nhưng"→bỏ từ dừng) = 3 × 2 chương
    assert got.get("Tiêu Viêm") == 6 and got.get("Vân Lam Tông") == 6 and got.get("Dược Lão") == 4, got
    assert got.get("Hà Nội") == 2 and "NASA" not in got, got            # Hà Nội đứng sau "qua" (giữa câu); NASA viết hoa toàn bộ không phải tên 2+ tiếng
    assert [t.count for t in terms] == sorted((t.count for t in terms), reverse=True)  # xếp theo tần suất
    assert all(" " in t.phrase and 2 <= len(t.phrase.split()) <= 4 for t in terms)
    assert "Thiên Địa Huyền Hoàng Vũ Trụ" not in got                        # 5 tiếng: quá dài
    ex = next(t for t in terms if t.phrase == "Dược Lão").example
    assert "Dược Lão" in ex and not ex.startswith(("–", "-", '"')), ex
    assert not any(t.phrase.split()[0].lower() in lexicon.load_stopwords() for t in terms)


def t_suggest_known_and_stop() -> None:
    assert "Tiêu Viêm" not in {t.phrase for t in lexicon.suggest_terms([(1, NAMES)] * 2, {"tiêu viêm"}, 2)}  # đã có trong từ điển
    only_start = "Tiêu Viêm bước vào. Tiêu Viêm cười. Tiêu Viêm đi. Tiêu Viêm nói."
    assert lexicon.suggest_terms([(1, only_start)], min_count=1) == []                                   # chỉ đứng đầu câu: không đếm
    assert lexicon.suggest_terms([(1, "Rồi Nhưng Anh Hắn bước vào.")], min_count=1, stop={"rồi", "nhưng", "anh", "hắn"}) == []


# ───────────── 6b: API (từ điển, gợi ý, giọng thứ hai, đọc thử) ─────────────
def t_lexicon_api() -> None:
    assert j(client.put(f"{B}/api/lexicon", json=[E("Vân Lam", "Vân Lam", 0.1)])) and j(client.get(f"{B}/api/lexicon"))[0]["match"] == "Vân Lam"
    assert client.put(f"{B}/api/lexicon", json=[E("")]).status_code == 400
    d = j(client.patch(f"{B}/api/books/{state['id']}", json={"lexicon": [E("Tiêu Viêm", "Tiêu Diễm", after=0.5)]}))
    assert d["lexicon"][0]["pause_after"] == 0.5
    assert client.patch(f"{B}/api/books/{state['id']}", json={"lexicon": [E("x")]}).status_code == 400
    out = j(client.post(f"{B}/api/books/{state['id']}/lexicon/apply", json={"text": "Tiêu Viêm ở Vân Lam"}))["text"]
    assert out == "Tiêu Diễm [nghỉ 0.5s] ở [nghỉ 0.1s] Vân Lam", out        # từ điển truyện + toàn cục cùng áp dụng
    j(client.put(f"{B}/api/lexicon", json=[]))
    j(client.patch(f"{B}/api/books/{state['id']}", json={"lexicon": []}))


def t_suggest_api() -> None:
    # mỗi dòng thêm hậu tố khác nhau theo chương, nếu không quy tắc "dòng trùng" coi cả thân chương là quảng cáo lặp
    story = "\n".join(f"Chương {i}\n" + "\n".join(l + f" (hồi {i})" for l in NAMES.split("\n")[1:] if l) for i in (1, 2, 3))
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("n.txt", story.encode(), "text/plain"))], data={"title": "Tên riêng smoke"}))
    state["names"] = d["id"]
    assert client.get(f"{B}/api/books/{d['id']}/suggest").status_code == 400           # chưa tách chương
    j(client.post(f"{B}/api/books/{d['id']}/chapters"))
    t = j(client.get(f"{B}/api/books/{d['id']}/suggest?min_count=3"))["terms"]
    got = {x["phrase"]: x["count"] for x in t}
    assert got.get("Tiêu Viêm") == 9 and got.get("Vân Lam Tông") == 9 and t[0]["count"] >= t[-1]["count"], got
    assert t[0]["example"] and t[0]["chapter"] == 1
    j(client.patch(f"{B}/api/books/{d['id']}", json={"lexicon": [E("Tiêu Viêm", before=0.2)]}))
    assert "Tiêu Viêm" not in {x["phrase"] for x in j(client.get(f"{B}/api/books/{d['id']}/suggest?min_count=3"))["terms"]}


def wav_seconds(r: httpx.Response) -> float:
    assert r.status_code == 200 and r.content[:4] == b"RIFF", (r.status_code, r.text[:150])
    return float(r.headers["x-sample-seconds"])


def t_pause_entry_lengthens() -> None:
    bid = state["names"]
    j(client.patch(f"{B}/api/books/{bid}", json={"lexicon": [E("Tiêu Viêm", before=1.0)]}))
    text = {"text": "Hắn nhìn Tiêu Viêm rồi cười."}
    plain = wav_seconds(client.post(f"{B}/api/books/{bid}/speak", json={**text, "use_lexicon": False}))
    paused = wav_seconds(client.post(f"{B}/api/books/{bid}/speak", json=text))
    assert 0.8 <= paused - plain <= 1.8, (plain, paused)     # nghỉ 1 giây (±: tách đoạn tổng hợp làm lệch vài chục ms)


def t_dialogue_voice_api() -> None:
    bid = state["names"]
    text = {"text": 'Hắn nói: “Đi thôi nào, chúng ta về nhà.” Rồi bỏ đi.', "use_lexicon": False}
    off = client.post(f"{B}/api/books/{bid}/speak", json=text)
    wav_seconds(off)
    d = j(client.patch(f"{B}/api/books/{bid}", json={"dialogue_voice": {"enabled": True, "engine": "vieneu", "voice": "Trúc Ly"}}))
    assert d["dialogue_voice"] == {"enabled": True, "engine": "vieneu", "voice": "Trúc Ly"}
    on = client.post(f"{B}/api/books/{bid}/speak", json=text)
    wav_seconds(on)
    assert on.content != off.content, "bật giọng thứ hai mà audio không đổi"
    assert client.patch(f"{B}/api/books/{bid}", json={"dialogue_voice": {"enabled": True, "engine": "vieneu", "voice": "lib:khong-co"}}).status_code == 404
    j(client.patch(f"{B}/api/books/{bid}", json={"dialogue_voice": {"enabled": False, "engine": "vieneu", "voice": "Trúc Ly"}}))


def t_cleanup_names() -> None:
    j(client.delete(f"{B}/api/books/{state['names']}"))


def t_trial_read() -> None:
    bid = state["names"]
    j(client.patch(f"{B}/api/books/{bid}", json={"lexicon": []}))
    t = j(client.post(f"{B}/api/books/{bid}/chapters/2/trial", json={"chars": 900, "offset": 0.3}))
    assert t["total"] >= 1 and t["chars"] > 100, t
    deadline = time.time() + 240
    while True:
        st = j(client.get(f"{B}/api/trials/{t['id']}"))
        assert st["status"] != "error", st
        if st["status"] == "done":
            break
        assert time.time() < deadline, st
        time.sleep(0.5)
    r = client.get(f"{B}/api/trials/{t['id']}/audio")
    assert r.status_code == 200 and r.content[:4] == b"RIFF" and 3 <= st["seconds"] <= 120 and st["done"] == st["total"], st
    assert client.post(f"{B}/api/books/{bid}/chapters/2/trial", json={"chars": 10}).status_code == 400
    assert client.post(f"{B}/api/books/{bid}/chapters/2/trial", json={"offset": 2}).status_code == 400
    assert client.get(f"{B}/api/trials/khong-co").status_code == 404



# ───────────── phần dẫn viết hoa (config/speech_verbs.txt) + gợi ý tên 1 tiếng ─────────────
LEAD_CASES = [
    ("– Đi đâu? – Hắn hỏi.", [("dlg", "Đi đâu?"), ("narr", "Hắn hỏi.")]),
    ("— Không! — Nàng thì thầm, giọng run run.", [("dlg", "Không!"), ("narr", "Nàng thì thầm, giọng run run.")]),
    ("– Anh đi đâu? – Tôi đi chợ.", [("dlg", "Anh đi đâu? Tôi đi chợ.")]),                       # không có động từ nói → câu thoại mới
    ("– Đi đi. – Hắn hỏi: – Về đâu? – Nàng đáp.", [("dlg", "Đi đi."), ("narr", "Hắn hỏi:"), ("dlg", "Về đâu?"), ("narr", "Nàng đáp.")]),
    ("– Về nhà. – Hắn nói một câu rất rất rất dài dòng chỉ để vượt quá giới hạn sáu mươi ký tự cho phép.",
     [("dlg", "Về nhà. Hắn nói một câu rất rất rất dài dòng chỉ để vượt quá giới hạn sáu mươi ký tự cho phép.")]),  # quá 60 ký tự
]


def t_lead_in_cases() -> None:
    bad = [(src, narrate.split_line(src), want) for src, want in LEAD_CASES if narrate.split_line(src) != want]
    assert not bad, bad


def t_speech_verbs_file_editable() -> None:
    path = narrate.SPEECH_VERBS_PATH
    old = path.read_text(encoding="utf-8")
    try:
        assert narrate.split_line("– Xong rồi. – Hắn khịt mũi.") == [("dlg", "Xong rồi. Hắn khịt mũi.")]       # "khịt" chưa có trong danh sách
        path.write_text(old + "khịt\n", encoding="utf-8")
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 2))                                      # mtime đổi chắc chắn
        assert narrate.split_line("– Xong rồi. – Hắn khịt mũi.") == [("dlg", "Xong rồi."), ("narr", "Hắn khịt mũi.")]
    finally:
        path.write_text(old, encoding="utf-8")
        os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 4))


def t_suggest_single() -> None:
    text = "Hắn nhìn Tiêu Viêm rồi cười. Rồi Viêm bước vào Vân Lam Tông.\n" * 6 + "Viêm Viêm bước đi. Viêm nói.\n"
    t = lexicon.suggest_terms([(1, text)], min_count=3)
    names = [(x.phrase, x.parent) for x in t]
    assert names == [("Tiêu Viêm", ""), ("Viêm", "Tiêu Viêm"), ("Vân Lam Tông", "")], names               # tiếng đơn nằm ngay dưới cụm cha
    assert t[1].count == 6 and "Viêm" in t[1].example
    few = "Hắn nhìn Tiêu Viêm rồi cười. Rồi Viêm bước vào.\n" * 4                                           # "Viêm" đứng riêng chỉ 4 lần < 5
    assert [x.phrase for x in lexicon.suggest_terms([(1, few)], min_count=3)] == ["Tiêu Viêm"]
    assert [x.phrase for x in lexicon.suggest_terms([(1, text)], {"viêm"}, 3)] == ["Tiêu Viêm", "Vân Lam Tông"]  # đã có trong từ điển



# ───────────── v2.1: đoạn văn, khoảng nghỉ, precision, dung lượng ─────────────
def t_paragraph_segments() -> None:
    book = {"read_title": True, "paragraph_pause_s": 0.6, "title_pause_s": 1.2}
    meta = {"title": "Chương 1"}
    body = "Đoạn A ngắn.\n\nĐoạn B ngắn.\n[nghỉ 1.5s]\nĐoạn C ngắn.\n[nghỉ 2s]"
    paras = books.paragraphs(book, meta, body)
    assert paras == [["Chương 1", 1.2], ["Đoạn A ngắn.", 0.6], ["Đoạn B ngắn.", 1.5], ["Đoạn C ngắn.", 2.0]], paras       # dấu ngăn cảnh thay khoảng nghỉ đoạn
    assert narrate.join_paras(paras) == "Chương 1\n[nghỉ 1.2s]\nĐoạn A ngắn.\n[nghỉ 0.6s]\nĐoạn B ngắn.\n[nghỉ 1.5s]\nĐoạn C ngắn."  # không thẻ sau đoạn cuối
    assert books.paragraphs({**book, "read_title": False}, meta, body)[0][0] == "Đoạn A ngắn."
    assert "[nghỉ" not in narrate.join_paras(books.paragraphs({**book, "paragraph_pause_s": 0, "title_pause_s": 0}, meta, "Đoạn A.\nĐoạn B."))  # 0 = không nghỉ
    # chỉ cắt ở ranh giới đoạn văn
    segs = narrate.split_segments(paras, 25)
    assert [[t for t, _ in s.paras] for s in segs] == [["Chương 1", "Đoạn A ngắn."], ["Đoạn B ngắn."], ["Đoạn C ngắn."]], [s.paras for s in segs]
    assert not any(s.cont for s in segs)
    # thẻ nghỉ ở mối nối: cuối đoạn trước; đoạn cuối chương không có
    assert [narrate.segment_text(segs, k).endswith("]") for k in range(3)] == [True, True, False]
    assert narrate.segment_text(segs, 1) == "Đoạn B ngắn.\n[nghỉ 1.5s]"
    # đoạn văn dài hơn giới hạn mới cắt, ở ranh giới câu; mối nối giữa các mảnh không có thẻ nghỉ đoạn văn
    long = " ".join(f"Đây là câu số {i} của đoạn văn rất dài." for i in range(1, 11))
    segs = narrate.split_segments([["Mở", 0.6], [long, 0.6], ["Cuối.", 0.6]], 120)
    assert len(segs) > 3 and all(len(narrate.join_paras(s.paras)) <= 120 for s in segs), [len(narrate.join_paras(s.paras)) for s in segs]
    assert [s.cont for s in segs][:2] == [False, False] and any(s.cont for s in segs)
    first_piece = next(k for k, s in enumerate(segs) if s.paras[0][0].startswith("Đây là câu số 1 "))
    for k, s in enumerate(segs[:-1]):
        nxt_cont = segs[k + 1].cont
        assert narrate.segment_text(segs, k).rstrip().endswith("]") == (not nxt_cont), (k, narrate.segment_text(segs, k)[-30:])
    assert first_piece == 1 and all(s.paras[0][0].endswith(".") for s in segs[1:-1])                        # cắt ở dấu chấm câu
    # excerpt theo đoạn văn
    ex = books.excerpt_paras([["x" * 100 + ".", 0.6]] * 6, 300)
    assert 3 <= len(ex) <= 4, len(ex)
    assert books.excerpt_paras([["a" * 10, 0.6], ["b" * 10, 0.6], ["c" * 10, 0.6]], 5, 0.99)[0][0].startswith("c")


def t_units_no_double_gap() -> None:
    e = ENGINES["vieneu"]
    us = narrate.units("Hắn nói với nàng.\n[nghỉ 0.6s]\n– Đi thôi.", (e, "a"), (e, "b"), True)
    kinds = [(u.kind, u.pause) for u in us]
    assert kinds == [("text", False), ("silence", True), ("text", False)], kinds                          # đổi giọng ngay chỗ xuống đoạn: chỉ một khoảng nghỉ
    assert 0.4 < us[1].seconds < 0.6, us[1].seconds
    us = narrate.units("Hắn nói với nàng.\n– Đi thôi.", (e, "a"), (e, "b"), True)
    assert [(u.kind, u.pause) for u in us] == [("text", False), ("silence", False), ("text", False)]      # không có thẻ: khoảng nghỉ đổi giọng nhỏ như cũ


def t_precision_default() -> None:
    from engines import vieneu

    old = os.environ.pop("VIENEU_PRECISION", None)
    real = vieneu.has_vnni
    try:
        vieneu.has_vnni = lambda: True
        assert vieneu.default_precision() == "int8"
        vieneu.has_vnni = lambda: False
        assert vieneu.default_precision() == "fp32"
        os.environ["VIENEU_PRECISION"] = "int8"
        assert vieneu.default_precision() == "int8"                 # ghi đè được dù CPU không có VNNI
        vieneu.has_vnni = lambda: True
        os.environ["VIENEU_PRECISION"] = "FP32"
        assert vieneu.default_precision() == "fp32"
        os.environ["VIENEU_PRECISION"] = "bf16"
        assert vieneu.default_precision() == "int8"                 # giá trị lạ: tự chọn theo CPU
        eng = ENGINES["vieneu"]
        os.environ["VIENEU_PRECISION"] = "int8"
        tag_int8 = eng.cache_tag()
        os.environ["VIENEU_PRECISION"] = "fp32"
        assert tag_int8.endswith("-int8") and eng.cache_tag() == eng._mode and tag_int8 != eng.cache_tag()  # cache fp32 / int8 tách nhau
    finally:
        vieneu.has_vnni = real
        os.environ.pop("VIENEU_PRECISION", None)
        if old is not None:
            os.environ["VIENEU_PRECISION"] = old


def t_engines_precision_api() -> None:
    e = j(client.get(f"{B}/api/engines"))
    assert e["vieneu"]["precision"] in ("fp32", "int8") and e["edge"]["precision"] is None, {k: v["precision"] for k, v in e.items()}


def t_pause_settings_api() -> None:
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("p.txt", STORY.encode(), "text/plain"))], data={"title": "Nghỉ smoke"}))
    bid = d["id"]
    assert d["paragraph_pause_s"] == 0.6 and d["title_pause_s"] == 1.2, (d["paragraph_pause_s"], d["title_pause_s"])
    b = j(client.patch(f"{B}/api/books/{bid}", json={"paragraph_pause_s": 0.8, "title_pause_s": 0}))
    assert b["paragraph_pause_s"] == 0.8 and b["title_pause_s"] == 0
    for body in ({"paragraph_pause_s": 7}, {"title_pause_s": 5.1}, {"paragraph_pause_s": 0.05}, {"paragraph_pause_s": -1}):
        assert client.patch(f"{B}/api/books/{bid}", json=body).status_code == 400, body
    state["pauses"] = bid


def t_settings_info() -> None:
    i = j(client.get(f"{B}/api/settings/info"))
    assert i["segment_chars"] > 0 and i["cache_max_bytes"] > 0 and i["cache_bytes"] >= 0 and i["precision"] in ("fp32", "int8") and i["vieneu_mode"], i


def t_settings_default_voice() -> None:
    assert j(client.get(f"{B}/api/settings")) == {"default_voice": None, "notify": True}
    vs = j(client.get(f"{B}/api/voices/vieneu"))
    pick = next(v for v in vs if v["id"] != "Hải Đăng" and v.get("usable", True))               # khác giọng mặc định của tool để thấy rõ tác dụng
    got = j(client.put(f"{B}/api/settings", json={"default_voice": {"engine": "vieneu", "voice": pick["id"]}}))
    assert got == {"default_voice": {"engine": "vieneu", "voice": pick["id"]}, "notify": True} and j(client.get(f"{B}/api/settings")) == got
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("s.txt", STORY.encode(), "text/plain"))], data={"title": "Giọng mặc định smoke"}))
    assert d["voice"] == {"engine": "vieneu", "voice": pick["id"]}, d["voice"]                      # truyện mới dùng giọng mặc định người dùng chọn
    j(client.delete(f"{B}/api/books/{d['id']}"))
    for bad in ({"engine": "khong-co", "voice": "x"}, {"engine": "vieneu", "voice": "Giọng không tồn tại"}, {"engine": "vieneu", "voice": "lib:khong-co"}, {"engine": "vieneu", "voice": ""}):
        assert client.put(f"{B}/api/settings", json={"default_voice": bad}).status_code in (400, 404), bad
    assert j(client.get(f"{B}/api/settings")) == got, "lưu sai không được làm mất lựa chọn cũ"
    assert j(client.put(f"{B}/api/settings", json={"default_voice": None})) == {"default_voice": None, "notify": True}
    # notify: tắt/bật độc lập, không đụng giọng mặc định; PUT không gửi default_voice thì giữ nguyên
    assert j(client.put(f"{B}/api/settings", json={"default_voice": {"engine": "vieneu", "voice": pick["id"]}, "notify": False})) == {"default_voice": {"engine": "vieneu", "voice": pick["id"]}, "notify": False}
    assert j(client.put(f"{B}/api/settings", json={"notify": True})) == {"default_voice": {"engine": "vieneu", "voice": pick["id"]}, "notify": True}
    assert j(client.put(f"{B}/api/settings", json={"default_voice": None})) == {"default_voice": None, "notify": True}
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("s.txt", STORY.encode(), "text/plain"))], data={"title": "Giọng mặc định smoke 2"}))
    assert d["voice"] == {"engine": "vieneu", "voice": "Hải Đăng"}, d["voice"]                      # bỏ chọn → mặc định của tool
    j(client.delete(f"{B}/api/books/{d['id']}"))


def t_title_pattern_inference_with_server() -> None:
    """Mẫu do titlepattern.js suy ra từ MỘT dòng ví dụ phải được server nhận (biên dịch được) và tìm đúng dòng tiêu đề."""
    import json
    import shutil
    import subprocess

    if not shutil.which("node"):
        return
    pats = json.loads(subprocess.run(["node", str(Path(__file__).resolve().parent.parent / "tests" / "js" / "print_patterns.mjs")], capture_output=True, text=True, check=True).stdout)
    body = "Nội dung của phần này đủ dài để không bị coi là quá ngắn và bị bỏ đi khi tách chương nhé các bạn."
    text = "\n".join(["Chương 1: Mở màn", body, "Hồi 2. Biến cố", body, "Chapter 3", body, "第4章 开始", body, "5. Cuối cùng", body, "Mở đầu", body])
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("p.txt", text.encode(), "text/plain"))], data={"title": "Mẫu tiêu đề smoke"}))
    want = {"Chương 5: Gặp gỡ": "Chương 1: Mở màn", "Hồi 5. Gặp gỡ": "Hồi 2. Biến cố", "Chapter 5": "Chapter 3", "第5章 开始": "第4章 开始", "5. Cuối cùng": "5. Cuối cùng", "Mở đầu": "Mở đầu"}
    for example, pat in pats.items():
        p = j(client.post(f"{B}/api/books/{d['id']}/preview", json={"regex": pat, "mode": "regex"}))
        titles = [c["title"] for c in p["chapters"]]
        assert want[example] in titles and sum(t != want[example] for t in titles) <= 1, (example, pat, titles)  # chỉ cho phép thêm đoạn "Mở đầu" trước tiêu đề đầu tiên
    j(client.delete(f"{B}/api/books/{d['id']}"))


def t_overview_api() -> None:
    o = j(client.get(f"{B}/api/overview"))
    assert set(o) == {"queue", "books", "current"} and o["queue"]["state"] in ("idle", "running", "paused", "pausing") and isinstance(o["books"], list), list(o)
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("o.txt", STORY.encode(), "text/plain"))], data={"title": "Tổng quan smoke"}))
    mine = lambda: next(b for b in j(client.get(f"{B}/api/overview"))["books"] if b["id"] == d["id"])  # noqa: E731
    b = mine()
    assert b["status"] == "draft" and b["done"] == 0 and b["running"] is False and b["queued"] == 0 and b["chapters"] == 0, b
    j(client.post(f"{B}/api/books/{d['id']}/chapters"))
    b = mine()
    assert b["status"] == "ready" and b["chapters"] == 5 and b["done"] == 0 and "size_bytes" in b and b["title"] == "Tổng quan smoke", b
    assert {x["id"] for x in j(client.get(f"{B}/api/overview"))["books"]} == {x["id"] for x in j(client.get(f"{B}/api/books"))}   # cùng danh sách với /api/books
    assert j(client.get(f"{B}/api/overview"))["current"] is None, "không có việc nào đang chạy thì current phải null"
    j(client.delete(f"{B}/api/books/{d['id']}"))


def t_disk_api() -> None:
    bid = state["pauses"]
    d = j(client.get(f"{B}/api/books/{bid}/disk"))
    assert d["total"] > 0 and d["audio"] == 0 and d["export"] == 0 and d["other"] == d["total"], d
    lst = j(client.get(f"{B}/api/books"))
    assert next(b for b in lst if b["id"] == bid)["size_bytes"] == d["total"]
    assert client.get(f"{B}/api/books/khong-co/disk").status_code == 404
    assert j(client.post(f"{B}/api/books/{bid}/audio/purge-exported"))["deleted"] == 0
    j(client.delete(f"{B}/api/books/{bid}"))



# ───────────── nhập file HTML chương truyện ─────────────
FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "chapter_sample.html"
EXPECTED = Path(__file__).resolve().parent / "vi-du-chuong-1.txt"


def html_variant(n: int, title: str | None = None, unknown: str = "") -> bytes:
    """Bản sao fixture thành 'chương n': đổi số trong <title>, thêm hậu tố riêng cho từng đoạn (nếu không quy tắc 'dòng trùng' sẽ coi
    cả thân chương giống nhau giữa các chương là quảng cáo lặp)."""
    h = FIXTURE.read_text(encoding="utf-8")
    h = re.sub(r"<title>.*?</title>", f"<title>{title or f'Cảnh Sát Hình Sự La Phi - Chương {n}: Chương {n}: TIÊU ĐỀ SỐ {n} | TruyenFull.vn'}</title>", h, count=1, flags=re.S)
    h = h.replace("<br>", f" (hồi {n})<br>") + (f"<p>{unknown}</p>" if unknown else "")
    return h.encode()


def html_book(files, **settings):
    """Nhập (name, bytes) vào truyện tạm (module trực tiếp) → (book, built)."""
    b = books.import_files(files, "", "", {"engine": "vieneu", "voice": "x"})
    st = books.overrides(b, {})
    for k, v in settings.items():
        st["clean"]["rules"][k] = v
    return b, books.build(books.load_docs(b["id"]), st)


def t_html_fixture_matches_example() -> None:
    exp = EXPECTED.read_text(encoding="utf-8")
    b, built = html_book([("chapter_sample.html", FIXTURE.read_bytes())], quotes=False)
    assert b["split"]["mode"] == "per_file" and len(built["chapters"]) == 1
    c = built["chapters"][0]
    got = c["title"] + "\n\n" + c["text"].replace("[nghỉ 1.5s]", "***")      # ngăn cảnh = quy tắc [nghỉ] có sẵn
    assert c["title"] == "Chương 1: Bức tranh tức giận (1)", c["title"]
    assert got + "\n" == exp, "khác vi-du-chuong-1.txt (so khớp chặt, chỉ tắt quy tắc ngoặc kép)"
    assert b["title"] == "Cảnh Sát Hình Sự La Phi", b["title"]                                  # tên truyện từ <title> file đầu tiên
    assert "*" not in c["text"] and "ham muốn" in c["text"].lower() or "*" not in c["text"], c["text"][:200]
    assert built["stats"]["unmask"] == 2 and built["stats"]["join_numbers"] == 1, built["stats"]
    assert built["warnings"] == [] and built["masked_unknown"] == [], (built["warnings"], built["masked_unknown"])
    # cũng khớp khi chuẩn hoá ngoặc kép cả hai bên (quy tắc ngoặc kép bật)
    _, built3 = html_book([("chapter_sample.html", FIXTURE.read_bytes())])
    c3 = built3["chapters"][0]
    q = lambda t: t.translate(books._QUOTES)  # noqa: E731
    assert q(c3["title"] + "\n\n" + c3["text"].replace("[nghỉ 1.5s]", "***") + "\n") == q(exp)
    # không có " - Chương" trong <title>: tên file đầu tiên; tên người dùng nhập luôn thắng
    page = "<html><head><title>Không có số</title></head><body><p>" + "Nội dung đủ dài. " * 20 + "</p></body></html>"
    b4 = books.import_files([("truyen_x.html", page.encode())], "", "", {"engine": "vieneu", "voice": "x"})
    assert b4["title"] == "truyen_x", b4["title"]
    b5 = books.import_files([("a.html", FIXTURE.read_bytes())], "Tên tự đặt", "", {"engine": "vieneu", "voice": "x"})
    assert b5["title"] == "Tên tự đặt"


def t_html_outside_frame_kept() -> None:
    _, built = html_book([("c.html", FIXTURE.read_bytes())])
    t = built["chapters"][0]["text"]
    assert "Hồi ức của ông cũng giống như phủ đầy bụi" in t and "Ông cho là hồi ức kia sẽ không bao giờ bị chạm đến nữa" in t, "đoạn ngoài khung chương bị mất"
    assert "ads" not in t.lower() and "function" not in t and "var " not in t, "script / quảng cáo lọt vào văn bản"
    assert t.splitlines().index("Mở Đầu") < next(i for i, l in enumerate(t.splitlines()) if l.startswith("Hồi ức của ông"))


def t_html_order_dupes_missing() -> None:
    files = [("chuong-10.html", html_variant(10)), ("chuong-1.html", html_variant(1)), ("chuong-2.html", html_variant(2))]
    b, built = html_book(files)
    assert [s["name"] for s in b["sources"]] == ["chuong-1.html", "chuong-2.html", "chuong-10.html"], [s["name"] for s in b["sources"]]
    assert [c["title"] for c in built["chapters"]] == ["Chương 1: Tiêu đề số 1", "Chương 2: Tiêu đề số 2", "Chương 10: Tiêu đề số 10"], [c["title"] for c in built["chapters"]]
    assert built["warnings"] == ["Thiếu chương: 3, 4, 5, 6, 7, 8, 9."], built["warnings"]
    # thiếu / trùng
    _, built = html_book([("a.html", html_variant(1)), ("b.html", html_variant(2)), ("c.html", html_variant(4))])
    assert built["warnings"] == ["Thiếu chương: 3."], built["warnings"]
    _, built = html_book([("a.html", html_variant(1)), ("b.html", html_variant(2)), ("b-copy.html", html_variant(2)), ("c.html", html_variant(5))])
    assert "Trùng số chương 2: b-copy.html, b.html." in built["warnings"] and "Thiếu chương: 3, 4." in built["warnings"], built["warnings"]
    # tiêu đề không có số → số trong tên file (không theo bảng chữ cái: 1, 2, 10)
    no_title = lambda n: html_variant(n, title="Cảnh Sát Hình Sự La Phi | TruyenFull.vn")  # noqa: E731
    b, _ = html_book([("truyen_c10.html", no_title(10)), ("truyen_c2.html", no_title(2)), ("truyen_c1.html", no_title(1))])
    assert [s["chapter_no"] for s in b["sources"]] == [1, 2, 10], b["sources"]
    # tiêu đề: bỏ tên trang + "Chương N:" lặp, IN HOA → chữ thường
    from html_import import clean_title
    assert clean_title("Truyện X - Chương 7: Chương 7: ĐẠI CHIẾN BẮT ĐẦU | TruyenFull.vn") == "Chương 7: Đại chiến bắt đầu"


def t_html_selector() -> None:
    page = ('<html><head><title>X - Chương 3: Một | TruyenFull.vn</title></head><body><div class="intro">Lời giới thiệu không lấy.</div>'
            '<div class="noidung" id="main"><p>Đoạn một của chương ba, đủ dài để không bị coi là chương rỗng nhé.</p></div>'
            '<p>Đoạn ngoài khung vẫn phải giữ lại vì HTML lỗi hay đẩy nội dung ra ngoài khung chương.</p></body></html>').encode()
    b = books.import_files([("c3.html", page)], "Selector " + os.urandom(2).hex(), "", {"engine": "vieneu", "voice": "x"})
    st = books.overrides(b, {})
    built = books.build(books.load_docs(b["id"], st["split"]["selector"]), st)               # #chapter-c không có → cả <body> + cảnh báo
    assert any("không tìm thấy khung chương" in w for w in built["warnings"]) and "Lời giới thiệu" in built["chapters"][0]["text"], built["warnings"]
    for sel in (".noidung", "#main", "div.noidung", "div#main.noidung"):
        st = books.overrides(b, {"selector": sel})
        built = books.build(books.load_docs(b["id"], st["split"]["selector"]), st)
        t = built["chapters"][0]["text"]
        assert "Lời giới thiệu" not in t and "Đoạn ngoài khung vẫn phải giữ lại" in t and not any("khung" in w for w in built["warnings"]), (sel, t, built["warnings"])
    for bad in ("", "div > p", "#"):
        try:
            books.validate_selector(bad)
        except books.BookError:
            continue
        raise AssertionError(f"selector {bad!r} phải bị từ chối")


def t_masked_unknown_and_dictionary() -> None:
    from html_import import masked_matches
    assert masked_matches("m**n", "muốn") and masked_matches("Th*ch", "thích") and not masked_matches("m**n", "muộn!") and not masked_matches("muốn", "muốn")
    assert not masked_matches("m**n", "mạnh") and not masked_matches("m*n", "muốn")                  # số chữ phải bằng nhau, chữ không bị che phải giống
    b, built = html_book([("c.html", html_variant(1, unknown="Hắn nhìn zz*zz và q*t rồi nói h*m m**n."))])
    got = {u["word"]: u for u in built["masked_unknown"]}
    assert set(got) == {"zz*zz", "q*t"} and got["zz*zz"]["count"] >= 1 and "zz*zz" in got["zz*zz"]["example"], got   # "h*m m**n" đã khôi phục
    assert "ham muốn" in built["chapters"][0]["text"]
    # thêm "từ đúng là…" → áp dụng lại ngay
    try:
        books.add_masked_word("q*t", "quên")
    except books.BookError:
        pass
    else:
        raise AssertionError("'quên' (5 chữ) không khớp 'q*t'")
    words = books.add_masked_word("q*t", "qút")
    assert "qút" in words and books.add_masked_word("q*t", "qút").count("qút") == 1                # không trùng
    st = books.overrides(b, {})
    built = books.build(books.load_docs(b["id"]), st)
    assert [u["word"] for u in built["masked_unknown"]] == ["zz*zz"] and "qút" in built["chapters"][0]["text"], built["masked_unknown"]
    # tắt quy tắc → không khôi phục, không báo
    st["clean"]["rules"]["unmask"] = False
    built = books.build(books.load_docs(b["id"]), st)
    assert built["masked_unknown"] == [] and "h*m m**n" in built["chapters"][0]["text"] and "unmask" not in built["stats"]
    # "Giữ dòng này" (ngoại lệ) áp dụng cho quy tắc mới
    st = books.overrides(b, {"exceptions": [{"rule": "unmask", "line": "Hắn nhìn zz*zz và q*t rồi nói h*m m**n. (hồi 1)"}]})
    built = books.build(books.load_docs(b["id"]), st)
    assert "h*m m**n" in built["chapters"][0]["text"], built["chapters"][0]["text"][-120:]


def t_join_numbers_blank_lines_rules() -> None:
    doc = books.Doc("t", "Chương 1\nGiá là 2. 513 đồng, thêm 1, 200 nữa.\n\n\nDòng sau khá dài để chương không bị bỏ đi vì quá ngắn nhé.\n\nDòng cuối.")
    st = books.default_settings()
    c = books.build([doc], st)["chapters"][0]["text"]
    assert "2.513" in c and "1,200" in c and "\n\n" not in c, repr(c)
    st["clean"]["rules"].update(join_numbers=False, blank_lines=False)
    c = books.build([books.Doc("t", doc.text)], st)["chapters"][0]["text"]
    assert "2. 513" in c and "\n\n" in c and "\n\n\n" not in c, repr(c)                             # không còn quy tắc: giữ tối đa 1 dòng trống như cũ
    b = books.build([books.Doc("t", doc.text)], books.default_settings())
    assert b["stats"]["join_numbers"] == 1 and b["stats"]["blank_lines"] == 3, b["stats"]
    assert b["rules"]["blank_lines"]["examples"][0]["before"].startswith("(dòng trống giữa")


def t_html_zip_import() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in (3, 1, 2):
            z.writestr(f"truyen/chuong-{n}.html", html_variant(n))
        z.writestr("truyen/readme.txt", "bỏ qua")
        z.writestr("__MACOSX/truyen/._chuong-1.html", "rác")
    b = books.import_files([("truyen.zip", buf.getvalue())], "Zip " + os.urandom(2).hex(), "", {"engine": "vieneu", "voice": "x"})
    assert [s["name"] for s in b["sources"]] == ["truyen/chuong-1.html", "truyen/chuong-2.html", "truyen/chuong-3.html"] and b["split"]["mode"] == "per_file", b["sources"]
    for bad_zip, why in ((b"khong phai zip", "zip hỏng"), (_zip_of({"a.txt": "x"}), "zip không có html")):
        try:
            books.import_files([("x.zip", bad_zip)], "", "", {"engine": "vieneu", "voice": "x"})
        except books.BookError:
            continue
        raise AssertionError(f"{why} phải bị từ chối")


def _zip_of(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, c in files.items():
            z.writestr(n, c)
    return buf.getvalue()


def t_html_api() -> None:
    files = [("files", (n, html_variant(i, unknown="Có zz*zz lạ ở đây." if i == 1 else ""), "text/html")) for n, i in (("c10.html", 10), ("c1.html", 1), ("c2.html", 2))]
    d = j(client.post(f"{B}/api/books/import", files=files, data={"title": "HTML smoke"}))
    bid = d["id"]
    assert d["split"]["mode"] == "per_file" and d["split"]["selector"] == "#chapter-c" and [s["chapter_no"] for s in d["sources"]] == [1, 2, 10], d["sources"]
    p = j(client.post(f"{B}/api/books/{bid}/preview"))
    assert [c["title"] for c in p["chapters"]] == ["Chương 1: Tiêu đề số 1", "Chương 2: Tiêu đề số 2", "Chương 10: Tiêu đề số 10"], p["chapters"]
    assert p["warnings"] == ["Thiếu chương: 3, 4, 5, 6, 7, 8, 9."], p["warnings"]
    assert [u["word"] for u in p["masked_unknown"]] == ["zz*zz"], p["masked_unknown"]
    assert {"unmask", "join_numbers", "blank_lines"} <= set(p["rules"]) and p["rules"]["unmask"]["count"] == 6, {k: v["count"] for k, v in p["rules"].items()}
    cat = {r["name"] for r in j(client.get(f"{B}/api/books/{bid}"))["rules_catalog"]}
    assert {"unmask", "join_numbers", "blank_lines"} <= cat
    # từ điển từ bị che: sai → 400, đúng → thêm và xem trước lại hết cảnh báo
    assert client.post(f"{B}/api/masked-words", json={"masked": "zz*zz", "correct": "khác hẳn"}).status_code == 400
    words = j(client.post(f"{B}/api/masked-words", json={"masked": "zz*zz", "correct": "zzazz"}))
    assert "zzazz" in words and "zzazz" in j(client.get(f"{B}/api/masked-words"))
    p = j(client.post(f"{B}/api/books/{bid}/preview"))
    assert p["masked_unknown"] == [], p["masked_unknown"]
    # selector tuỳ chỉnh: ghi đè khi xem trước, lưu qua PATCH, sai → 400
    assert client.post(f"{B}/api/books/{bid}/preview", json={"selector": "div >"}).status_code == 400
    p = j(client.post(f"{B}/api/books/{bid}/preview", json={"selector": "#khong-co"}))
    assert sum("không tìm thấy khung chương" in w for w in p["warnings"]) == 3, p["warnings"]
    assert client.patch(f"{B}/api/books/{bid}", json={"split": {"selector": "x y"}}).status_code == 400
    assert j(client.patch(f"{B}/api/books/{bid}", json={"split": {"selector": ".chapter-c"}}))["split"]["selector"] == ".chapter-c"
    b = j(client.post(f"{B}/api/books/{bid}/chapters"))
    assert b["status"] == "ready" and b["chapters"]["count"] == 3 and b["split"]["selector"] == ".chapter-c"
    assert "Hồi ức của ông" in j(client.get(f"{B}/api/books/{bid}/chapters/1"))["text"]
    j(client.delete(f"{B}/api/books/{bid}"))
    # zip qua API; file không hỗ trợ vẫn bị từ chối
    z = _zip_of({"a/ch1.html": html_variant(1), "a/ch2.html": html_variant(2)})
    d = j(client.post(f"{B}/api/books/import", files=[("files", ("truyen.zip", z, "application/zip"))], data={"title": "Zip API"}))
    assert [s["name"] for s in d["sources"]] == ["a/ch1.html", "a/ch2.html"], d["sources"]
    j(client.delete(f"{B}/api/books/{d['id']}"))
    assert client.post(f"{B}/api/books/import", files=[("files", ("a.docx", b"x", "application/zip"))]).status_code == 400
    assert client.post(f"{B}/api/books/import", files=[("files", ("a.zip", b"khong phai zip", "application/zip"))]).status_code == 400



for name, fn in [
    ("6a+: mỗi quy tắc báo số dòng bị ảnh hưởng + dòng ví dụ (tối đa 50)", t_rule_impact_module),
    ("6a+: ngoại lệ \"Giữ dòng này\" (xoá, thay thế, gộp)", t_exceptions_module),
    ("6b: tách lời thoại — 10 ví dụ (ngoặc kép, gạch thoại, phần dẫn, thuật ngữ, ngoặc không đóng)", t_dialogue_cases),
    ("6b: gộp đoạn cùng giọng thành run, giữ ngắt dòng / đoạn", t_dialogue_runs),
    ("v2.1: đoạn văn → đoạn cắt chỉ ở ranh giới đoạn văn, thẻ nghỉ ở mối nối, đoạn dài cắt ở ranh giới câu", t_paragraph_segments),
    ("v2.1: đổi giọng đúng chỗ xuống đoạn chỉ có một khoảng nghỉ", t_units_no_double_gap),
    ("v2.1: precision mặc định theo VNNI, VIENEU_PRECISION ghi đè, cache_tag tách fp32 / int8", t_precision_default),
    ("HTML: fixture thật khớp vi-du-chuong-1.txt (3 quy tắc mới, ngăn cảnh → [nghỉ])", t_html_fixture_matches_example),
    ("HTML: đoạn 'Hồi ức của ông…' nằm ngoài khung chương không bị mất; script / quảng cáo bị bỏ", t_html_outside_frame_kept),
    ("HTML: chương 1/2/10 xếp đúng thứ tự, báo thiếu / trùng chương, tiêu đề sạch", t_html_order_dupes_missing),
    ("HTML: selector khung chương chỉnh được, không thấy khung → cả body + cảnh báo", t_html_selector),
    ("HTML: từ bị che lạ được báo, thêm 'từ đúng là…' áp dụng lại ngay, ngoại lệ", t_masked_unknown_and_dictionary),
    ("HTML: quy tắc ghép số bị tách và bỏ dòng trống thừa (bật/tắt, thống kê)", t_join_numbers_blank_lines_rules),
    ("HTML: nhập file .zip chứa html (bỏ file khác, zip hỏng / không có html bị từ chối)", t_html_zip_import),
    ("6b+: phần dẫn viết hoa sau gạch thoại (5 ví dụ)", t_lead_in_cases),
    ("6b+: config/speech_verbs.txt sửa được, có hiệu lực ngay", t_speech_verbs_file_editable),
    ("6b+: gợi ý tên 1 tiếng chỉ khi là thành phần cụm đã gợi ý, đứng riêng ≥ 5 lần", t_suggest_single),
    ("6b: từ điển — đọc thành, nghỉ trước/sau, nguyên từ, hoa/thường, ưu tiên, không nối tiếp", t_lexicon_apply),
    ("6b: từ điển — kiểm tra dữ liệu sai", t_lexicon_validate),
    ("6b: gợi ý tên riêng — bỏ đầu câu, từ dừng, 2–4 tiếng, xếp theo tần suất, câu ví dụ", t_suggest_terms),
    ("6b: gợi ý tên riêng — bỏ cụm đã có trong từ điển, chỉ đứng đầu câu thì không đếm", t_suggest_known_and_stop),
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
    ("API: nhập 3 file HTML, xem trước (thứ tự, cảnh báo, từ bị che), từ điển từ bị che, selector, zip", t_html_api),
    ("API: v2.1 GET /api/engines có precision", t_engines_precision_api),
    ("API: v2.1 mức nghỉ đoạn văn / tiêu đề trong cài đặt truyện, kiểm tra khoảng giá trị", t_pause_settings_api),
    ("API: GET /api/settings/info (chế độ chạy, độ chính xác, cỡ đoạn, dung lượng bộ nhớ tạm — chỉ đọc)", t_settings_info),
    ("API: GET/PUT /api/settings — giọng mặc định (kiểm tra giọng, truyện mới dùng giọng đó, bỏ chọn)", t_settings_default_voice),
    ("API: mẫu tiêu đề suy ra từ một dòng ví dụ (node) được server chấp nhận và tìm đúng chương", t_title_pattern_inference_with_server),
    ("API: GET /api/overview (chỉ đọc: hàng đợi + truyện + tiến độ, current null khi rảnh)", t_overview_api),
    ("API: v2.1 dung lượng từng truyện, xoá nguồn FLAC khi chưa có gì đã xuất", t_disk_api),
    ("API: 6a+ tác động quy tắc, ngoại lệ lưu và dùng lại khi tách chương", t_rule_impact_api),
    ("API: 6b từ điển toàn cục + của truyện, /lexicon/apply", t_lexicon_api),
    ("API: 6b gợi ý tên riêng (400 khi chưa tách chương, bỏ cụm đã có)", t_suggest_api),
    ("API: 6b mục từ điển nghỉ trước 1s làm audio dài thêm ~1s", t_pause_entry_lengthens),
    ("API: 6b giọng thứ hai cho lời thoại đổi audio, giọng không tồn tại → 404", t_dialogue_voice_api),
    ("API: 6c Đọc thử 1 phút qua hàng đợi (job có tiến độ, chars/offset, lỗi đầu vào)", t_trial_read),
    ("API: dọn truyện thử của 6b", t_cleanup_names),
    ("API: nhập nhiều .txt → mỗi file một chương, sắp xếp tự nhiên", t_multi_files),
    ("API: nhập .epub lấy tên truyện / tác giả", t_epub_import),
    ("API: file không hỗ trợ / EPUB hỏng / truyện không tồn tại", t_bad_imports),
    ("API: danh sách và xoá truyện", t_list_delete),
]:
    check(name, fn)

sys.exit(1 if fails else 0)
