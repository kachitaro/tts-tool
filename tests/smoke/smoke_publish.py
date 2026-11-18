"""Smoke test laptop đăng bài (giongviet.publisher). Không gọi mạng thật: Discord được giả bằng server cục bộ.
Chạy: python tests/smoke/smoke_publish.py. In "PASS  tên" / "FAIL  tên — lý do"; thoát mã 1 nếu có FAIL (~10 giây).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PY = sys.executable
PORT, FAKE_PORT = 8767, 8768
TOKEN = "tok-" + uuid.uuid4().hex
SECRET_URL = f"http://127.0.0.1:{FAKE_PORT}/hook-secret"
fails = 0


def check(name: str, fn) -> None:
    global fails
    try:
        fn()
        print(f"PASS  {name}", flush=True)
    except Exception as ex:  # noqa: BLE001
        fails += 1
        print(f"FAIL  {name} — {type(ex).__name__}: {str(ex)[:300]}", flush=True)


# ───────────── phần 1: logic lịch, thời gian giả ─────────────
def logic() -> None:
    from giongviet.publisher import channels, worker
    from giongviet.publisher.store import Store, new_post

    tmp = Path(tempfile.mkdtemp(prefix="pub_logic_"))
    (tmp / "secrets.json").write_text(
        json.dumps(
            {"discord": {"webhook": "SECRETWEBHOOK"}, "mastodon": {"instance": "x", "token": "t"}}
        )
    )
    store = Store(tmp)
    calls: list[tuple[str, str]] = []
    behavior = {"discord": "ok", "mastodon": "ok"}

    def fake(ch):
        def f(cfg, text, media, key):
            calls.append((ch, key))
            if behavior[ch] == "fail":
                raise channels.ChannelError("boom SECRETWEBHOOK")

        return f

    channels.CHANNELS["discord"], channels.CHANNELS["mastodon"] = fake("discord"), fake("mastodon")
    now = 1_000_000.0

    def add(pid, chans, when):
        store.create(new_post(pid, chans, "hi", when, None))

    def tick_count(t) -> int:
        n = len(calls)
        worker.tick(store, t)
        return len(calls) - n

    def due_posts_run_once():
        add("p-due-0001", ["discord"], now - 10)
        add("p-future-1", ["discord"], now + 100)
        assert tick_count(now) == 1
        assert store.get("p-due-0001")["status"] == "done"
        assert store.get("p-future-1")["status"] == "pending"
        assert tick_count(now + 1) == 0  # xong rồi thì không đăng lại

    def missed_not_posted():
        add("p-late-0001", ["discord"], now - worker.MISSED_AFTER - 1)
        assert tick_count(now) == 0
        assert store.get("p-late-0001")["status"] == "missed"

    def retry_backoff_and_redact():
        behavior["discord"] = "fail"
        add("p-fail-0001", ["discord"], now - 10)
        assert tick_count(now) == 1
        p = store.get("p-fail-0001")
        assert (p["status"], p["attempts"], p["next_try"]) == ("pending", 1, now + 60), p
        assert "SECRETWEBHOOK" not in json.dumps(p["results"]), p["results"]
        assert tick_count(now + 30) == 0  # chưa tới giờ thử lại
        assert tick_count(now + 61) == 1
        assert tick_count(now + 61 + 301) == 1
        p = store.get("p-fail-0001")
        assert (p["status"], p["attempts"]) == ("error", 3), p
        assert tick_count(now + 10_000) == 0  # đã error: dừng
        behavior["discord"] = "ok"

    def partial_success_not_resent():
        behavior["mastodon"] = "fail"
        add("p-part-0001", ["discord", "mastodon"], now - 10)
        calls.clear()
        worker.tick(store, now)
        assert calls == [("discord", "p-part-0001"), ("mastodon", "p-part-0001")], calls
        behavior["mastodon"] = "ok"
        calls.clear()
        worker.tick(store, now + 61)
        assert calls == [("mastodon", "p-part-0001")], calls  # discord đã xong: không đăng đôi
        assert store.get("p-part-0001")["status"] == "done"

    def running_recovered_after_crash():
        add("p-run-00001", ["discord"], now - 10)
        store.update("p-run-00001", status="running")
        assert Store(tmp).get("p-run-00001")["status"] == "pending"

    def media_cleaned_after_keep():
        add("p-keep-0001", ["discord"], now - 10)
        d = store.post_dir("p-keep-0001")
        d.mkdir(parents=True)
        (d / "a.mp3").write_bytes(b"x")
        store.update("p-keep-0001", filename="a.mp3")
        worker.tick(store, now)
        assert (d / "a.mp3").exists()
        worker.tick(store, now + worker.KEEP + 5)
        assert not d.exists()

    for name, fn in [
        ("lịch: bài đến hạn đăng đúng một lần, bài tương lai chờ", due_posts_run_once),
        ("lịch: bài quá hạn ngưỡng → missed, không đăng", missed_not_posted),
        (
            "lịch: lỗi → backoff 60s/300s, đủ 3 lần thì error, bí mật bị che",
            retry_backoff_and_redact,
        ),
        ("lịch: kênh đã đăng không bị đăng lại khi thử lại kênh khác", partial_success_not_resent),
        ("lịch: bài running khi chết → pending khi mở lại", running_recovered_after_crash),
        ("lịch: file đính kèm bị dọn sau KEEP ngày", media_cleaned_after_keep),
    ]:
        store.posts.clear()  # mỗi test một kho trống, không lẫn bài của test trước
        calls.clear()
        behavior.update(discord="ok", mastodon="ok")
        check(name, fn)


# ───────────── phần 2: HTTP thật ─────────────
received: list[bytes] = []


class FakeDiscord(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        received.append(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


PROD_PORT = 8769


def bridge(laptop: str, laptop_auth: dict) -> None:
    """Máy tạo giọng (python -m giongviet) → cầu nối /api/publish → laptop thật (tiến trình ở trên)."""
    prod_data = Path(tempfile.mkdtemp(prefix="pub_prod_"))
    env = {**os.environ, "TTS_DATA_DIR": str(prod_data), "PORT": str(PROD_PORT)}
    seed = (
        "from giongviet import history; "
        "print(history.save('tts', {'text': 'xin chao'}, b'MP3-BRIDGE-BYTES', 'mp3'))"
    )
    item = subprocess.run(
        [PY, "-c", seed], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()
    proc = subprocess.Popen(
        [PY, "-m", "giongviet"],
        cwd=ROOT,
        env=env,
        stdout=open(prod_data / "server.log", "ab"),
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{PROD_PORT}"
    try:
        for _ in range(240):
            try:
                if httpx.get(base + "/api/settings").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError(
                "server máy tạo giọng không lên: " + (prod_data / "server.log").read_text()[-400:]
            )
        p = httpx.Client(base_url=base, timeout=60)

        def set_pub(url, token=None):
            body = {"publisher_url": url}
            if token is not None:
                body["publisher_token"] = token
            return p.put("/api/settings", json=body)

        def post_body(pid, **kw):
            return {
                "id": pid,
                "source": {"kind": "history", "id": item},
                "channels": ["discord"],
                "caption": "từ máy tạo giọng",
                "when": time.time() - 1,
                **kw,
            }

        def not_configured():
            r = p.post("/api/publish/posts", json=post_body("bridge-test-00"))
            assert r.status_code == 400 and "Chưa cài" in r.json()["error"], r.text

        def settings_never_leak_token():
            assert set_pub("ftp://x").status_code == 400
            r = set_pub(laptop + "/", TOKEN)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["publisher_url"] == laptop and j["publisher_token_set"] is True, j
            assert TOKEN not in r.text and TOKEN not in p.get("/api/settings").text
            # lưu một cài đặt khác không được làm mất token (hồi quy: save() dựng lại từ load())
            assert (
                p.put("/api/settings", json={"notify": True}).json()["publisher_token_set"] is True
            )

        def publish_and_idempotent():
            assert [c["id"] for c in p.get("/api/publish/channels").json() if c["configured"]] == [
                "discord"
            ]
            body = post_body("bridge-test-01")
            assert p.post("/api/publish/posts", json=body).status_code == 200
            lc = httpx.Client(base_url=laptop, headers=laptop_auth, timeout=30)
            for _ in range(40):
                st = next(x for x in lc.get("/api/posts").json() if x["id"] == body["id"])["status"]
                if st == "done":
                    break
                time.sleep(0.25)
            assert st == "done", st
            assert p.post("/api/publish/posts", json=body).status_code == 200  # gửi lại cùng id
            time.sleep(1.2)
            hits = [b for b in received if b"MP3-BRIDGE-BYTES" in b]
            assert len(hits) == 1 and b"giong-noi.mp3" in hits[0], len(hits)
            assert any(x["id"] == body["id"] for x in p.get("/api/publish/posts").json())

        def unknown_source_404():
            r = p.post(
                "/api/publish/posts",
                json={
                    **post_body("bridge-test-02"),
                    "source": {"kind": "history", "id": "0000000000000000-abcd"},
                },
            )
            assert r.status_code == 404, r.text

        def wrong_token_and_unreachable():
            set_pub(laptop, "sai-token")
            r = p.get("/api/publish/channels")
            assert r.status_code == 502 and "token" in r.json()["error"], r.text
            set_pub("http://127.0.0.1:1", TOKEN)
            r = p.get("/api/publish/channels")
            assert r.status_code == 502 and "Không kết nối" in r.json()["error"], r.text
            set_pub(laptop, TOKEN)

        check("máy tạo giọng: chưa cài laptop → 400 nói rõ", not_configured)
        check(
            "máy tạo giọng: token không bao giờ trả ra ngoài và không mất khi lưu cài đặt khác",
            settings_never_leak_token,
        )
        check(
            "máy tạo giọng → laptop: gửi file lịch sử, đăng, gửi lại cùng id không đăng đôi",
            publish_and_idempotent,
        )
        check("máy tạo giọng: nguồn không tồn tại → 404", unknown_source_404)
        check(
            "máy tạo giọng: sai token / laptop tắt → 502 lời dễ hiểu", wrong_token_and_unreachable
        )
    finally:
        proc.terminate()
        proc.wait(30)


def http_part() -> None:
    data = Path(tempfile.mkdtemp(prefix="pub_http_"))
    (data / "secrets.json").write_text(json.dumps({"discord": {"webhook": SECRET_URL}}))
    fake = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeDiscord)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    env = {
        **os.environ,
        "PUBLISHER_DATA": str(data),
        "PUBLISHER_TOKEN": TOKEN,
        "PUBLISHER_TICK": "0.5",
        "PUBLISHER_MAX_MB": "1",
        "PORT": str(PORT),
    }

    def no_heavy_deps():
        code = (
            "import sys, importlib.abc\n"
            "class B(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path, target=None):\n"
            "        if name.split('.')[0] in {'numpy','librosa','soundfile','soxr','edge_tts','vieneu','scipy','numba'}:\n"
            "            raise ImportError('blocked ' + name)\n"
            "sys.meta_path.insert(0, B())\n"
            "import giongviet.publisher.app, giongviet.publisher.__main__\n"
        )
        r = subprocess.run([PY, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-400:]

    def refuses_open_host_without_token():
        e = {**env, "HOST": "0.0.0.0"}
        e.pop("PUBLISHER_TOKEN")
        r = subprocess.run(
            [PY, "-m", "giongviet.publisher"],
            cwd=ROOT,
            env=e,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode != 0 and "PUBLISHER_TOKEN" in (r.stdout + r.stderr), r

    check("laptop: import không cần numpy/librosa/edge-tts", no_heavy_deps)
    check(
        "laptop: HOST ngoài loopback mà thiếu token → từ chối khởi động",
        refuses_open_host_without_token,
    )

    proc = subprocess.Popen(
        [PY, "-m", "giongviet.publisher"],
        cwd=ROOT,
        env=env,
        stdout=open(data / "server.log", "ab"),
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{PORT}"
    auth = {"Authorization": f"Bearer {TOKEN}"}
    try:
        for _ in range(60):
            try:
                if httpx.get(base + "/api/posts", headers=auth).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("publisher không lên: " + (data / "server.log").read_text()[-400:])
        c = httpx.Client(base_url=base, headers=auth, timeout=30)

        def auth_required():
            assert httpx.get(base + "/api/posts").status_code == 401
            assert (
                httpx.get(base + "/api/posts", headers={"Authorization": "Bearer sai"}).status_code
                == 401
            )
            assert c.get("/api/posts").status_code == 200

        def channel_must_be_configured():
            r = c.post(
                "/api/posts",
                data={"id": "chan-test-1", "channels": "mastodon", "when": time.time()},
            )
            assert r.status_code == 400 and "error" in r.json(), r.text

        def bad_id_rejected():
            r = c.post(
                "/api/posts", data={"id": "../x", "channels": "discord", "when": time.time()}
            )
            assert r.status_code == 400, r.text

        def create_is_idempotent_and_delivers_file():
            body = {
                "id": "idem-test-0001",
                "channels": "discord",
                "when": time.time() - 1,
                "caption": "xin chào",
            }
            f = {"file": ("../../chuong1.mp3", b"ID3-fake-audio-bytes")}
            r1 = c.post("/api/posts", data=body, files=f)
            assert r1.status_code == 200, r1.text
            assert r1.json()["filename"] == "chuong1.mp3", r1.json()  # tên bị cắt phần đường dẫn
            r2 = c.post("/api/posts", data=body, files=f)  # retry sau rớt mạng
            assert r2.status_code == 200 and r2.json()["id"] == body["id"]
            for _ in range(40):
                p = next(x for x in c.get("/api/posts").json() if x["id"] == body["id"])
                if p["status"] == "done":
                    break
                time.sleep(0.25)
            assert p["status"] == "done", p
            time.sleep(1.2)  # đủ vài tick để nếu có đăng đôi thì thấy
            hits = [b for b in received if b"ID3-fake-audio-bytes" in b]
            assert len(hits) == 1, f"{len(hits)} lần gửi"
            assert b"chuong1.mp3" in hits[0], hits[0][:300]
            assert json.dumps({"content": "xin chào"}).encode() in hits[0], hits[0][:300]

        def oversize_rejected_and_cleaned():
            r = c.post(
                "/api/posts",
                data={"id": "big-test-0001", "channels": "discord", "when": time.time() + 3600},
                files={"file": ("big.mp3", b"0" * (2 * 1024 * 1024))},
            )
            assert r.status_code == 413, r.status_code
            assert not (data / "media" / "big-test-0001").exists()
            assert all(x["id"] != "big-test-0001" for x in c.get("/api/posts").json())

        def edit_and_delete():
            body = {"id": "edit-test-0001", "channels": "discord", "when": time.time() + 3600}
            assert c.post("/api/posts", data=body).status_code == 200
            r = c.patch("/api/posts/edit-test-0001", json={"caption": "mới"})
            assert r.status_code == 200 and r.json()["caption"] == "mới"
            assert c.delete("/api/posts/edit-test-0001").status_code == 200
            assert c.delete("/api/posts/edit-test-0001").status_code == 404

        check("laptop: thiếu/sai token → 401, đúng token → 200", auth_required)
        check("laptop: kênh chưa cấu hình → 400", channel_must_be_configured)
        check("laptop: id có ký tự đường dẫn → 400", bad_id_rejected)
        check(
            "laptop: gửi lại cùng id không đăng đôi; file tới kênh; tên file bị làm sạch",
            create_is_idempotent_and_delivers_file,
        )
        check("laptop: file quá giới hạn → 413 và không để rác", oversize_rejected_and_cleaned)
        check("laptop: sửa nội dung rồi xoá bài đang chờ", edit_and_delete)
        bridge(base, auth)
    finally:
        proc.terminate()
        proc.wait(10)
        fake.shutdown()


if __name__ == "__main__":
    logic()
    http_part()
    sys.exit(1 if fails else 0)
