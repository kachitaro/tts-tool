"""Smoke test chế độ Sách nói (gọi từ scripts/smoke_test.sh): in "PASS  tên" / "FAIL  tên — lý do" mỗi bước.

Dùng: python scripts/smoke_books.py <base_url>
Phần module (dò encoding, làm sạch, EPUB) chạy trực tiếp trên books.py với data tạm; phần API chạy trên server đang chạy.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

os.environ["TTS_DATA_DIR"] = tempfile.mkdtemp()  # chỉ cho phần module; server có data riêng
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


def t_disk_api() -> None:
    bid = state["pauses"]
    d = j(client.get(f"{B}/api/books/{bid}/disk"))
    assert d["total"] > 0 and d["audio"] == 0 and d["export"] == 0 and d["other"] == d["total"], d
    lst = j(client.get(f"{B}/api/books"))
    assert next(b for b in lst if b["id"] == bid)["size_bytes"] == d["total"]
    assert client.get(f"{B}/api/books/khong-co/disk").status_code == 404
    assert j(client.post(f"{B}/api/books/{bid}/audio/purge-exported"))["deleted"] == 0
    j(client.delete(f"{B}/api/books/{bid}"))



for name, fn in [
    ("6a+: mỗi quy tắc báo số dòng bị ảnh hưởng + dòng ví dụ (tối đa 50)", t_rule_impact_module),
    ("6a+: ngoại lệ \"Giữ dòng này\" (xoá, thay thế, gộp)", t_exceptions_module),
    ("6b: tách lời thoại — 10 ví dụ (ngoặc kép, gạch thoại, phần dẫn, thuật ngữ, ngoặc không đóng)", t_dialogue_cases),
    ("6b: gộp đoạn cùng giọng thành run, giữ ngắt dòng / đoạn", t_dialogue_runs),
    ("v2.1: đoạn văn → đoạn cắt chỉ ở ranh giới đoạn văn, thẻ nghỉ ở mối nối, đoạn dài cắt ở ranh giới câu", t_paragraph_segments),
    ("v2.1: đổi giọng đúng chỗ xuống đoạn chỉ có một khoảng nghỉ", t_units_no_double_gap),
    ("v2.1: precision mặc định theo VNNI, VIENEU_PRECISION ghi đè, cache_tag tách fp32 / int8", t_precision_default),
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
    ("API: v2.1 GET /api/engines có precision", t_engines_precision_api),
    ("API: v2.1 mức nghỉ đoạn văn / tiêu đề trong cài đặt truyện, kiểm tra khoảng giá trị", t_pause_settings_api),
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
