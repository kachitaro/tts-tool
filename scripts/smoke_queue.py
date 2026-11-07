"""Smoke test hàng đợi tạo audio sách nói (Phase 6c). Tự khởi động server riêng (cổng 8766, data tạm, đoạn nhỏ) để
kill -9 / SIGINT giữa chừng rồi khởi động lại. Cần VieNeu (giọng "Hải Đăng") và ffmpeg; chạy: python scripts/smoke_queue.py
In "PASS  tên" / "FAIL  tên — lý do" mỗi bước. Thoát mã 1 nếu có FAIL. Mất ~3 phút (sinh audio thật bằng model).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"
DATA = Path(tempfile.mkdtemp(prefix="smoke_queue_"))
PY = sys.executable
client = httpx.Client(base_url=BASE, timeout=120)
fails = 0
proc: subprocess.Popen | None = None
state: dict = {}


def check(name: str, fn) -> None:
    global fails
    try:
        fn()
        print(f"PASS  {name}", flush=True)
    except Exception as ex:  # noqa: BLE001
        fails += 1
        print(f"FAIL  {name} — {type(ex).__name__}: {str(ex)[:300]}", flush=True)


def start_server() -> None:
    global proc
    env = {**os.environ, "PORT": str(PORT), "TTS_DATA_DIR": str(DATA), "BOOK_SEGMENT_CHARS": "90"}
    proc = subprocess.Popen([PY, "server.py"], cwd=ROOT, env=env, stdout=open(DATA / "server.log", "ab"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            if client.get("/api/queue").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("server không lên: " + (DATA / "server.log").read_text(errors="replace")[-500:])


def stop_server(sig: int = signal.SIGINT, wait: float = 90) -> float:
    global proc
    t = time.time()
    proc.send_signal(sig)
    proc.wait(timeout=wait)
    proc = None
    return time.time() - t


def q(bid: str | None = None) -> dict:
    return client.get("/api/queue", params={"book": bid} if bid else None).json()


def wait_for(cond, timeout: float = 150, step: float = 0.25, what: str = "điều kiện"):
    t = time.time()
    while time.time() - t < timeout:
        v = cond()
        if v:
            return v
        time.sleep(step)
    raise TimeoutError(f"quá {timeout}s chờ {what}; trạng thái: {json.dumps(q(state.get('id')), ensure_ascii=False)[:400]}")


def chapters() -> list[dict]:
    return client.get(f"/api/books/{state['id']}/chapters").json()


def statuses() -> list[str]:
    return [c["status"] for c in chapters()]


def post(path: str, body=None) -> httpx.Response:
    return client.post(path, json=body if body is not None else {})


def run_all(**kw) -> dict:
    r = post(f"/api/books/{state['id']}/queue/run", kw)
    assert r.status_code == 200, r.text
    return r.json()


def running_at(n: int, seg: int):
    s = q(state["id"])
    return s if s["running"] and s["running"]["n"] == n and s["running"]["seg_done"] >= seg else None


def idle() -> dict | None:
    s = q(state["id"])
    return s if s["state"] == "idle" and not s["running"] else None


def story() -> bytes:
    def ch(i: int) -> str:
        return (f"Chương {i}: Tiêu đề {i}\nĐây là câu thứ nhất của chương {i}, đủ dài để tạo thành một đoạn riêng biệt nhé.\n"
                f"Đây là câu thứ hai của chương {i}, cũng được viết dài như vậy để chia thêm một đoạn nữa.\n"
                f"Đây là câu thứ ba của chương {i}, và nó cũng dài như hai câu trước đó cho đủ ba đoạn.\n")
    return "\n".join(ch(i) for i in (1, 2, 3)).encode()


# ───────────── các bước ─────────────
def t_priority_lock() -> None:
    """Khoá model: việc tương tác đang chờ được nhận khoá trước việc nền đã chờ từ trước."""
    import contextvars
    import threading

    sys.path.insert(0, str(ROOT))
    from engines.base import BACKGROUND, PriorityLock

    lock, order, held = PriorityLock(), [], threading.Event()

    def holder():
        with lock:
            held.set()
            time.sleep(0.4)

    def waiter(name: str, background: bool):
        BACKGROUND.set(background)
        with lock:
            order.append(name)
            time.sleep(0.05)

    threading.Thread(target=holder).start()
    held.wait()
    ts = []
    for name, bg in (("nền", True), ("tương tác", False)):  # nền vào hàng chờ trước, tương tác sau
        ts.append(threading.Thread(target=contextvars.copy_context().run, args=(waiter, name, bg)))
        ts[-1].start()
        time.sleep(0.1)
    for t in ts:
        t.join(5)
    assert order == ["tương tác", "nền"], order


def t_setup() -> None:
    d = client.post("/api/books/import", files=[("files", ("q.txt", story(), "text/plain"))], data={"title": "Hàng đợi smoke", "author": "Tôi"}).json()
    state["id"] = d["id"]
    assert post(f"/api/books/{d['id']}/chapters").status_code == 200
    chs = chapters()
    assert [c["status"] for c in chs] == ["pending"] * 3 and all(c["chars"] > 150 for c in chs), chs


def t_run_and_kill9() -> None:
    r = run_all()
    assert r["added"] == [1, 2, 3] and r["state"] in ("running", "idle"), r
    wait_for(lambda: running_at(2, 1), what="chương 2 xong đoạn đầu")
    assert statuses()[0] == "done"
    o = client.get("/api/overview").json()                                   # đang chạy: current khớp hàng đợi
    cur = o["current"]
    assert cur and cur["book"] == state["id"] and cur["chapters"] == 3 and cur["done"] >= 1 and cur["chapter"] == 2 and cur["state"] == "running", cur
    assert next(b for b in o["books"] if b["id"] == state["id"])["running"] is True
    state["c1_mtime"] = (DATA / "books" / state["id"] / "audio" / "0001.flac").stat().st_mtime_ns
    stop_server(signal.SIGKILL, 20)
    saved = json.loads((DATA / "queue.json").read_text())
    assert [i["n"] for i in saved["items"]] == [2, 3] and not saved["paused"], saved["items"]
    assert any((DATA / "books" / state["id"] / "audio" / "0002.parts").glob("*.flac")), "đoạn đã dựng phải còn trên đĩa"


def t_restart_resumes() -> None:
    start_server()
    first = q(state["id"])
    assert first["counts"].get("done") == 1 and first["state"] == "running", first["counts"]
    wait_for(idle, timeout=200, what="hàng đợi chạy xong sau khi khởi động lại")
    assert statuses() == ["done"] * 3
    assert (DATA / "books" / state["id"] / "audio" / "0001.flac").stat().st_mtime_ns == state["c1_mtime"], "chương 1 đã xong không được dựng lại"
    assert not list((DATA / "books" / state["id"] / "audio").glob("*.parts")), "thư mục .parts phải được dọn"
    f = q()["finish"]
    assert f["done"] >= 2 and f["errors"] == 0, f


def t_export() -> None:
    bid = state["id"]

    def wait_job(jid: str) -> dict:
        return wait_for(lambda: (lambda s: s if s["status"] != "running" else None)(client.get(f"/api/exports/{jid}").json()), 120, 0.3, "việc xuất")

    j = post(f"/api/books/{bid}/export", {"kind": "mp3zip", "kbps": 64}).json()
    s = wait_job(j["id"])
    assert s["status"] == "done" and s["chapters"] == 3, s
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/books/{bid}/export/{s['file']}").content))
    names = z.namelist()
    assert len(names) == 3 and names[0].startswith("0001 - ") and all(n.endswith(".mp3") for n in names), names
    p = Path(tempfile.mkdtemp()) / "c1.mp3"
    p.write_bytes(z.read(names[0]))
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-of", "json", "-show_format", "-show_streams", str(p)], capture_output=True, text=True).stdout)
    st, tags = info["streams"][0], {k.lower(): v for k, v in info["format"].get("tags", {}).items()}
    assert st["codec_name"] == "mp3" and st["channels"] == 1 and 60_000 <= int(info["format"]["bit_rate"]) <= 70_000, (st, info["format"])
    assert tags["title"].startswith("1. Chương 1") and tags["album"] == "Hàng đợi smoke" and tags["artist"] == "Tôi" and tags["track"] == "1/3", tags
    state["c1_seconds"] = float(info["format"]["duration"])
    j = post(f"/api/books/{bid}/export", {"kind": "m4b"}).json()
    s = wait_job(j["id"])
    assert s["status"] == "done", s
    m = Path(tempfile.mkdtemp()) / "b.m4b"
    m.write_bytes(client.get(f"/api/books/{bid}/export/{s['file']}").content)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-of", "json", "-show_chapters", "-show_format", str(m)], capture_output=True, text=True).stdout)
    ch = info["chapters"]
    assert len(ch) == 3 and ch[0]["tags"]["title"].startswith("1. Chương 1") and float(ch[0]["start_time"]) == 0, ch
    total = sum(c["audio_seconds"] for c in chapters())
    assert abs(float(info["format"]["duration"]) - total) < 1.5, (info["format"]["duration"], total)  # audio_seconds làm tròn 0,1 s
    assert abs(float(ch[1]["start_time"]) - state["c1_seconds"]) < 0.3, (ch[1]["start_time"], state["c1_seconds"])
    assert client.get(f"/api/books/{bid}/chapters/2/audio.mp3").headers["content-type"] == "audio/mpeg"
    assert all(".tmp" not in f["name"] for f in q(bid)["exports"]), q(bid)["exports"]                    # file tạm đang ghi dở không được liệt kê
    assert post(f"/api/books/{bid}/export", {"kind": "mp3zip", "kbps": 128}).status_code == 400


def t_regenerate_pause_trial_priority() -> None:
    bid = state["id"]
    before = (DATA / "books" / bid / "audio" / "0001.flac").read_bytes()
    r = run_all(regenerate=True)
    assert r["added"] == [1, 2, 3], r
    wait_for(lambda: running_at(1, 1), what="chương 1 chạy")
    s = q(bid)
    assert s["inhibit"] == "on", s["inhibit"]
    if shutil.which("systemd-inhibit"):
        listing = subprocess.run(["systemd-inhibit", "--list"], capture_output=True, text=True).stdout
        assert "Giọng Việt đang tạo sách nói" in listing, listing
    # Đọc thử chen vào, có tiến độ, xong trước khi cả hàng đợi chạy hết
    t = post(f"/api/books/{bid}/chapters/3/trial", {"chars": 120, "offset": 0.0}).json()
    assert t["total"] >= 1
    def trial_done():
        x = client.get(f"/api/trials/{t['id']}").json()
        assert 0 <= x["done"] <= x["total"], x
        return x if x["status"] in ("done", "error") else None

    ts = wait_for(trial_done, 120, 0.3, "đọc thử")
    assert ts["status"] == "done" and ts["done"] == ts["total"] and ts["seconds"] > 1, ts
    assert client.get(f"/api/trials/{t['id']}/audio").content[:4] == b"RIFF"
    assert q(bid)["state"] == "running", "đọc thử phải xong khi hàng đợi chương còn đang chạy (chen vào, không đợi hết hàng)"
    # nghe thử tương tác vào khoá model trước việc nền
    t0 = time.time()
    r = client.get(f"/api/books/{bid}/chapters/1/sample")
    took = time.time() - t0
    assert r.status_code == 200 and r.content[:4] == b"RIFF", r.status_code
    assert q(bid)["state"] != "idle", f"▶ mất {took:.0f}s, hàng đợi đã chạy xong: không chứng minh được ưu tiên"
    # focus: chương 3 lên trước chương 2
    items = json.loads((DATA / "queue.json").read_text())["items"]
    if [i["n"] for i in items][:3] == [1, 2, 3]:  # chương 1 đang chạy, 2 và 3 đang chờ
        assert client.post(f"/api/books/{bid}/queue/focus", json={"n": 3}).json()["moved"] is True
        order = [i["n"] for i in json.loads((DATA / "queue.json").read_text())["items"]]
        assert order.index(3) < order.index(2), order
    # tạm dừng: chờ xong đoạn đang chạy rồi dừng, không cắt giữa đoạn
    post("/api/queue/pause")
    s = wait_for(lambda: (lambda x: x if x["state"] == "paused" else None)(q(bid)), 120, 0.3, "tạm dừng")
    assert s["running"] is None and s["queued"] >= 1, s
    segs_at_pause = [(c["n"], c["status"], (c.get("segments") or {}).get("done")) for c in chapters()]
    time.sleep(4)
    assert [(c["n"], c["status"], (c.get("segments") or {}).get("done")) for c in chapters()] == segs_at_pause, "đang tạm dừng mà vẫn dựng"
    assert "queued" in statuses()
    post("/api/queue/resume")
    wait_for(idle, timeout=240, what="chạy xong sau khi tiếp tục")
    assert statuses() == ["done"] * 3
    assert (DATA / "books" / bid / "audio" / "0001.flac").read_bytes() != before, "Tạo lại phải cho audio mới"
    s = q(bid)
    assert s["inhibit"] == "off", s["inhibit"]
    if shutil.which("systemd-inhibit"):
        assert "Giọng Việt đang tạo sách nói" not in subprocess.run(["systemd-inhibit", "--list"], capture_output=True, text=True).stdout


def t_cancel_and_inhibit_toggle() -> None:
    bid = state["id"]
    assert post("/api/queue/settings", {"inhibit_sleep": False}).json()["inhibit_sleep"] is False
    run_all(regenerate=True, chapters=[1, 2, 3])
    wait_for(lambda: running_at(1, 0), what="chương 1 chạy")
    assert q(bid)["inhibit"] in ("off", "unavailable"), "đã tắt checkbox thì không giữ khoá"
    if shutil.which("systemd-inhibit"):
        assert "Giọng Việt đang tạo sách nói" not in subprocess.run(["systemd-inhibit", "--list"], capture_output=True, text=True).stdout
    r = post("/api/queue/cancel", {"book": bid}).json()
    assert r["cancelled"] >= 1, r
    wait_for(idle, timeout=120, what="dừng sau khi huỷ")
    st = statuses()
    assert "queued" not in st and "running" not in st and "pending" in st, st
    post("/api/queue/settings", {"inhibit_sleep": True})


def t_sigint_clean() -> None:
    bid = state["id"]
    run_all(regenerate=True, chapters=[1, 2, 3])  # bỏ qua cache để chắc chắn có đoạn đang chạy dở khi dừng
    wait_for(lambda: running_at(2, 1), what="chạy tới chương 2")
    took = stop_server(signal.SIGINT, 90)
    assert took < 60, f"tắt server mất {took:.0f}s"
    saved = json.loads((DATA / "queue.json").read_text())
    assert saved["items"] and not saved["paused"], saved
    c = json.loads(next((DATA / "books" / bid / "chapters").glob("0002.json")).read_text())
    assert c["status"] in ("queued", "done"), c["status"]  # không kẹt ở "running"
    assert not list((DATA / "books" / bid / "audio").glob("*.tmp")), "không để lại file tạm"
    start_server()
    wait_for(idle, timeout=240, what="chạy xong sau SIGINT + khởi động lại")
    assert statuses() == ["done"] * 3


def t_stale_and_priority_of_settings() -> None:
    bid = state["id"]
    assert not any(c["stale"] for c in chapters())
    assert client.patch(f"/api/books/{bid}", json={"lexicon": [{"match": "câu", "replace": "", "pause_before": 0.2, "pause_after": 0,
                                                                  "whole_word": True, "case_sensitive": False}]}).status_code == 200
    assert all(c["stale"] for c in chapters()), "đổi từ điển thì chương đã dựng thành lỗi thời"
    run_all(chapters=[1])  # không regenerate: chương đã xong bị bỏ qua
    assert q(bid)["queued"] == 0
    r = run_all(stale_only=True, regenerate=True, limit=1)
    assert r["added"] == [1], r
    wait_for(idle, timeout=120, what="tạo lại chương lỗi thời")
    cs = chapters()
    assert [c["stale"] for c in cs] == [False, True, True], [c["stale"] for c in cs]


def t_pause_settings_stale() -> None:
    bid = state["id"]
    base = [c["stale"] for c in chapters()]                                  # t_stale để lại chương 2, 3 lỗi thời
    for body in ({"paragraph_pause_s": 0.9}, {"title_pause_s": 0.5}, {"read_title": False}):
        assert client.patch(f"/api/books/{bid}", json=body).status_code == 200
        assert all(c["stale"] for c in chapters() if c["status"] == "done"), f"{body} phải làm chương đã dựng thành lỗi thời"
        assert client.patch(f"/api/books/{bid}", json={"paragraph_pause_s": 0.6, "title_pause_s": 1.2, "read_title": True}).status_code == 200
        assert [c["stale"] for c in chapters()] == base, "trả lại cài đặt cũ thì trạng thái lỗi thời trở lại như trước"
    # precision nằm trong chữ ký (qua cache_tag): đổi cache_tag thì lỗi thời. Kiểm trực tiếp, không cần chạy lại server.
    sys.path.insert(0, str(ROOT))
    import bookq
    from engines.registry import ENGINES

    e, book = ENGINES["vieneu"], {"speed": 0, "normalize": True, "lexicon": [], "read_title": True}
    old = os.environ.get("VIENEU_PRECISION")
    try:
        os.environ["VIENEU_PRECISION"] = "fp32"
        a = bookq.signature(book, (e, "Hải Đăng"), None, [])
        os.environ["VIENEU_PRECISION"] = "int8"
        b = bookq.signature(book, (e, "Hải Đăng"), None, [])
    finally:
        os.environ.pop("VIENEU_PRECISION", None) if old is None else os.environ.__setitem__("VIENEU_PRECISION", old)
    assert a != b, "đổi precision phải đổi chữ ký (chương đã dựng thành lỗi thời)"


def t_disk_purge_exported() -> None:
    bid = state["id"]
    audio = DATA / "books" / bid / "audio"
    d0 = client.get(f"/api/books/{bid}/disk").json()
    assert d0["audio"] > 100_000 and d0["total"] >= d0["audio"] + d0["export"], d0
    assert next(b for b in client.get("/api/books").json() if b["id"] == bid)["size_bytes"] == d0["total"]
    assert q(bid)["purgeable"]["chapters"] == 0, q(bid)["purgeable"]            # chưa xuất lần nào sau khi tạo lại
    s = client.post(f"/api/books/{bid}/export", json={"kind": "mp3zip"}).json()
    wait_for(lambda: (lambda x: x if x["status"] != "running" else None)(client.get(f"/api/exports/{s['id']}").json()), 60, 0.3, "xuất")
    pg = q(bid)["purgeable"]
    assert pg["chapters"] == 3 and pg["bytes"] > 100_000, pg
    r = client.post(f"/api/books/{bid}/audio/purge-exported").json()
    assert r["deleted"] == 3 and r["freed"] == pg["bytes"], r
    assert statuses() == ["exported"] * 3 and not list(audio.glob("*.flac"))
    d1 = client.get(f"/api/books/{bid}/disk").json()
    assert d1["audio"] == 0 and d1["total"] < d0["total"] and d1["export"] > 0, (d0, d1)   # file xuất (zip + mp3) không bị xoá
    assert client.get(f"/api/books/{bid}/chapters/1/audio.mp3").status_code == 409
    assert client.post(f"/api/books/{bid}/export", json={"kind": "m4b"}).status_code == 400        # không còn chương nào để xuất
    assert client.post(f"/api/books/{bid}/queue/run", json={}).status_code == 400                # "đã xuất" không phải chưa xong
    assert client.post(f"/api/books/{bid}/queue/run", json={"chapters": [1, 2]}).json()["added"] == []  # bỏ qua chương đã xuất
    # tạo lại một chương đã xuất: dựng lại, hết dấu "đã xuất"
    r = run_all(chapters=[2], regenerate=True)
    assert r["added"] == [2], r
    wait_for(idle, timeout=120, what="tạo lại chương đã xuất")
    c = {x["n"]: x for x in chapters()}
    assert [c[1]["status"], c[2]["status"], c[3]["status"]] == ["exported", "done", "exported"], [x["status"] for x in c.values()]
    assert (audio / "0002.flac").is_file() and not c[2].get("exported")
    zs = client.post(f"/api/books/{bid}/export", json={"kind": "mp3zip"}).json()
    assert zs["total"] == 1, zs                                                                    # chỉ chương còn nguồn
    wait_for(lambda: (lambda x: x if x["status"] != "running" else None)(client.get(f"/api/exports/{zs['id']}").json()), 60, 0.3, "xuất")
    run_all(chapters=[1, 3], regenerate=True)
    wait_for(idle, timeout=200, what="tạo lại các chương đã xuất")
    assert statuses() == ["done"] * 3


def t_errors_and_guards() -> None:
    bid = state["id"]
    assert post(f"/api/books/{bid}/queue/run", {"chapters": [99]}).status_code == 400
    assert client.delete(f"/api/books/{bid}").status_code == 200  # không còn việc chạy nên xoá được
    assert client.get(f"/api/queue", params={"book": bid}).status_code == 404
    assert q()["queued"] == 0


def main() -> None:
    try:
        start_server()
        for name, fn in [
            ("khoá model: tương tác vào trước việc nền", t_priority_lock),
            ("hàng đợi: nhập truyện 3 chương, tách chương", t_setup),
            ("hàng đợi: chạy tất cả → kill -9 giữa chừng → queue.json + đoạn đã dựng còn trên đĩa", t_run_and_kill9),
            ("hàng đợi: khởi động lại tự chạy tiếp, chương xong không dựng lại, .parts được dọn", t_restart_resumes),
            ("xuất: MP3 zip (64k mono, ID3) + .m4b có 3 chương, tổng thời lượng khớp", t_export),
            ("hàng đợi: Tạo lại, Đọc thử chen vào có tiến độ, ▶ tương tác, focus, tạm dừng ở ranh giới đoạn, systemd-inhibit", t_regenerate_pause_trial_priority),
            ("hàng đợi: tắt checkbox chống ngủ, huỷ hàng đợi", t_cancel_and_inhibit_toggle),
            ("hàng đợi: SIGINT giữa chừng dừng sạch (<60s), khởi động lại chạy tiếp", t_sigint_clean),
            ("hàng đợi: đổi từ điển → chương lỗi thời, chạy lại chỉ các chương lỗi thời", t_stale_and_priority_of_settings),
            ("v2.1: đổi mức nghỉ / đọc tiêu đề / precision → chương lỗi thời, trả lại thì hết", t_pause_settings_stale),
            ("v2.1: dung lượng từng truyện, xoá nguồn FLAC chương đã xuất → trạng thái 'đã xuất', tạo lại", t_disk_purge_exported),
            ("hàng đợi: lỗi đầu vào, xoá truyện", t_errors_and_guards),
        ]:
            check(name, fn)
    finally:
        if proc is not None:
            proc.kill()
        if fails:
            print("--- cuối server.log:", (DATA / "server.log").read_text(errors="replace")[-1500:])
        shutil.rmtree(DATA, ignore_errors=True)
    sys.exit(1 if fails else 0)


main()
