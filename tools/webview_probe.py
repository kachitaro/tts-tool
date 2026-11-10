"""Đo nhanh một backend của pywebview (gtk | qt) để chọn cái dùng cho app "Giọng Việt".
Mở một cửa sổ thật (nên chạy trong Xvfb: `xvfb-run -a -s "-screen 0 1280x800x24" <python> tools/webview_probe.py --backend gtk`)
và đo:
  - phát WAV / FLAC / MP3 (canPlayType + play() thật, tắt tiếng, currentTime phải chạy),
  - getUserMedia (micro) + MediaRecorder,
  - kéo thả file từ ngoài vào cửa sổ (một cửa sổ GTK riêng đóng vai file manager, chuột giả bằng XTest),
  - localStorage còn sau khi mở lại (cùng cổng),
  - RAM (PSS, KB) của cả cây tiến trình webview khi rảnh. Có --url để nạp trang thật của tool đang chạy ở tiến trình khác.
In một dòng JSON. Cần: pywebview, python-xlib, pillow; kéo thả cần python3-gi hệ thống (/usr/bin/python3) làm "file manager".
Cách dựng hai venv để so sánh (đã dùng cho bảng trong README):
  GTK: python3 -m venv /tmp/vg && /tmp/vg/bin/pip install pywebview python-xlib pillow \
       && ln -s /usr/lib/python3/dist-packages/gi /tmp/vg/lib/python3.14/site-packages/gi
  Qt : python3 -m venv /tmp/vq && /tmp/vq/bin/pip install pywebview PyQt6 PyQt6-WebEngine qtpy python-xlib pillow
Chạy trong Xvfb nhớ bỏ WAYLAND_DISPLAY (GDK_BACKEND=x11 cho nguồn kéo thả) và với Qt thêm
QTWEBENGINE_CHROMIUM_FLAGS=--autoplay-policy=no-user-gesture-required (không có cờ này play() không do người dùng bấm bị chặn).
Đây là công cụ dùng một lần để so sánh backend, không phải một phần của app.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--backend", choices=["gtk", "qt"], required=True)
ap.add_argument("--url", help="nạp trang này (vd. tool thật) thay cho trang thử cho phần đo RAM")
ap.add_argument("--idle", type=float, default=8, help="giây chờ trước khi đo RAM")
ap.add_argument("--screenshot", help="chụp màn hình Xvfb ra file này")
ap.add_argument("--no-dnd", action="store_true")
ap.add_argument(
    "--no-mic-patch",
    action="store_true",
    help="GTK: không tự cho phép micro (để thấy mặc định bị từ chối)",
)
args = ap.parse_args()

PROBE_ID = uuid.uuid4().hex
os.environ["GV_PROBE_ID"] = PROBE_ID
if args.backend == "gtk":
    os.environ.setdefault("GDK_BACKEND", "x11")
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import webview  # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="webview_probe_"))
REPORT: dict = {"backend": args.backend}
GOT = {
    "page": threading.Event(),
    "drop": threading.Event(),
    "dragenter": threading.Event(),
    "dropEvent": threading.Event(),
}


def make_assets() -> None:
    for ext, codec in (("wav", "pcm_s16le"), ("flac", "flac"), ("mp3", "libmp3lame")):
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                codec,
                str(WORK / f"t.{ext}"),
            ],
            check=True,
        )
    (WORK / "drop-me.txt").write_text("xin chào " * 100, encoding="utf-8")


PAGE = """<!doctype html><meta charset=utf-8><title>probe</title>
<body style="font:16px sans-serif"><div id=zone style="position:fixed;left:300px;top:200px;width:500px;height:300px;border:3px dashed #07a;padding:10px">Thả file vào đây</div><pre id=out></pre>
<script>
const R = { ua: navigator.userAgent, pywebview: !!window.pywebview };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const post = (o) => fetch('/report', { method: 'POST', body: JSON.stringify(o) });
const z = document.getElementById('zone');
for (const ev of ['dragenter', 'dragover']) z.addEventListener(ev, (e) => { e.preventDefault(); if (ev === 'dragenter') post({ dragenter: [...e.dataTransfer.types] }); });
z.addEventListener('drop', async (e) => {
  e.preventDefault();
  post({ dropEvent: { types: [...e.dataTransfer.types], nfiles: e.dataTransfer.files.length, items: e.dataTransfer.items ? e.dataTransfer.items.length : -1, uri: e.dataTransfer.getData('text/uri-list'), text: e.dataTransfer.getData('text/plain').slice(0, 120) } });
  const fs = [...e.dataTransfer.files];
  const info = [];
  for (const f of fs) { let n = -1; try { n = (await f.arrayBuffer()).byteLength; } catch (er) { n = 'ERR ' + er; } info.push({ name: f.name, size: f.size, read: n, path: f.pywebviewFullPath || null }); }
  post({ drop: { files: info, types: [...e.dataTransfer.types] } });
});
(async () => {
  for (let i = 0; i < 100 && !window.__go; i++) await sleep(100);
  R.canPlay = {}; R.play = {};
  for (const [ext, mime] of [['wav', 'audio/wav'], ['flac', 'audio/flac'], ['mp3', 'audio/mpeg']]) {
    const a = new Audio('/t.' + ext); R.canPlay[ext] = a.canPlayType(mime) || 'no';
    a.muted = true;
    try { await a.play(); await sleep(900); R.play[ext] = { ok: a.currentTime > 0.3, t: +a.currentTime.toFixed(2), dur: +(a.duration || 0).toFixed(2) }; a.pause(); }
    catch (e) { R.play[ext] = { ok: false, err: e.name + ': ' + e.message }; }
  }
  R.mediaRecorder = typeof MediaRecorder;
  if (typeof MediaRecorder !== 'undefined') R.recTypes = ['audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav'].filter((t) => MediaRecorder.isTypeSupported(t));
  R.mediaDevices = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  try {
    const s = await navigator.mediaDevices.getUserMedia({ audio: true });
    R.gum = { ok: true, tracks: s.getAudioTracks().length, label: s.getAudioTracks()[0] && s.getAudioTracks()[0].label };
    if (typeof MediaRecorder !== 'undefined') {
      R.gum.rec = {};
      for (const mt of ['', 'audio/webm', 'audio/webm;codecs=opus', 'audio/ogg', 'audio/mp4']) {
        if (mt && !MediaRecorder.isTypeSupported(mt)) { R.gum.rec[mt || 'default'] = 'unsupported'; continue; }
        try {
          const rec = mt ? new MediaRecorder(s, { mimeType: mt }) : new MediaRecorder(s), chunks = [];
          rec.ondataavailable = (e) => chunks.push(e.data);
          const done = new Promise((r) => (rec.onstop = r));
          rec.start(250); await sleep(1100); rec.stop(); await done;
          const blob = new Blob(chunks, { type: rec.mimeType });
          let dec = null;
          if (blob.size) { try { const c = new AudioContext(); const b = await c.decodeAudioData(await blob.arrayBuffer()); dec = +b.duration.toFixed(2); c.close(); } catch (e) { dec = 'decode ERR ' + e.name; } }
          R.gum.rec[mt || 'default'] = { bytes: blob.size, mime: rec.mimeType, decodedSeconds: dec };
        } catch (e) { R.gum.rec[mt || 'default'] = 'ERR ' + e.name + ': ' + e.message; }
      }
    }
    try {   // thu PCM trực tiếp bằng WebAudio (không qua MediaRecorder)
      const c = new AudioContext(); const src = c.createMediaStreamSource(s); const proc = c.createScriptProcessor(4096, 1, 1);
      let n = 0; proc.onaudioprocess = (e) => { n += e.inputBuffer.length; };
      src.connect(proc); proc.connect(c.destination); await sleep(1100);
      R.gum.pcm = { samples: n, rate: c.sampleRate, seconds: +(n / c.sampleRate).toFixed(2) }; proc.disconnect(); src.disconnect(); c.close();
    } catch (e) { R.gum.pcm = 'ERR ' + e.name + ': ' + e.message; }
    s.getTracks().forEach((t) => t.stop());
  } catch (e) { R.gum = { ok: false, err: e.name + ': ' + e.message }; }
  R.notification = typeof Notification === 'undefined' ? 'none' : Notification.permission;
  try { const prev = localStorage.getItem('probe'); R.localStorageBefore = prev; localStorage.setItem('probe', String(Date.now())); } catch (e) { R.localStorageBefore = 'ERR ' + e.name; }
  post({ page: R });
})();
</script>"""


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(WORK), **k)

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path in ("/", "/probe.html"):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        for k, v in d.items():
            REPORT[k] = v
            GOT[k].set()
        self.send_response(204)
        self.end_headers()


def descendants(root: int) -> set[int]:
    kids: dict[int, list[int]] = {}
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                ppid = int((p / "stat").read_text().rsplit(")", 1)[1].split()[1])
            except OSError, ValueError, IndexError:
                continue
            kids.setdefault(ppid, []).append(int(p.name))
    out, todo = {root}, [root]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c not in out:
                out.add(c)
                todo.append(c)
    return out


def tree_pss() -> dict:
    """PSS (KB) của cả cây tiến trình của probe (python + các tiến trình WebKit* / QtWebEngine* sinh ra)."""
    out, total = {}, 0
    me = os.getpid()
    pids = descendants(me)
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            pid = int(p.name)
            if pid not in pids:
                if PROBE_ID.encode() not in (p / "environ").read_bytes():
                    continue
            name = (p / "comm").read_text().strip()
            pss = sum(
                int(line.split()[1])
                for line in (p / "smaps_rollup").read_text().splitlines()
                if line.startswith("Pss:")
            )
        except OSError, ValueError:
            continue
        out[f"{name}:{p.name}" + ("*" if pid == me else "")] = pss
        total += pss
    return {"total_kb": total, "procs": out}


def do_drag(win):
    """File manager giả (GTK, python3 hệ thống) bắt đầu kéo một file; chuột giả bằng XTest thả vào vùng #zone của trang."""
    from Xlib import X, display
    from Xlib.ext import xtest

    src = subprocess.Popen(
        [
            "/usr/bin/python3",
            str(Path(__file__).with_name("webview_dnd_source.py")),
            str(WORK / "drop-me.txt"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert src.stdout.readline().strip() == "ready"
    d = display.Display()
    move = lambda x, y: (xtest.fake_input(d, X.MotionNotify, x=x, y=y), d.sync())  # noqa: E731
    time.sleep(0.5)
    move(110, 60)
    time.sleep(0.2)
    xtest.fake_input(d, X.ButtonPress, 1)
    d.sync()
    time.sleep(0.2)
    tx, ty = (
        300 + 250 + (win.x or 0),
        200 + 150 + (win.y or 0),
    )  # tâm #zone (cửa sổ không có WM nên không viền)
    sx, sy = 110, 60
    for i in range(1, 41):
        move(int(sx + (tx - sx) * i / 40), int(sy + (ty - sy) * i / 40))
        time.sleep(0.03)
    time.sleep(0.4)
    if args.screenshot:
        from PIL import ImageGrab

        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(
            args.screenshot.replace(".png", "-drag.png")
        )
    xtest.fake_input(d, X.ButtonRelease, 1)
    d.sync()
    return src


def allow_mic_gtk(win) -> None:
    """pywebview/GTK không trả lời permission-request nên WebKitGTK từ chối micro: tự cho phép (chỉ trang 127.0.0.1 của tool)."""
    import gi

    gi.require_version("WebKit2", "4.1")
    from gi.repository import WebKit2
    from webview.platforms.gtk import BrowserView

    def on_perm(_wv, req):
        if isinstance(req, WebKit2.UserMediaPermissionRequest):
            req.allow()
            return True
        return False

    BrowserView.instances[win.uid].webview.connect("permission-request", on_perm)


def runner(win) -> None:
    try:
        win.events.loaded.wait(20)
        if args.backend == "gtk" and not args.no_mic_patch:
            allow_mic_gtk(win)
        win.evaluate_js("window.__go = true")
        REPORT["page_loaded"] = GOT["page"].wait(40)
        if args.url:
            win.load_url(args.url)
            time.sleep(args.idle)
        else:
            time.sleep(args.idle)
        if args.screenshot:
            from PIL import ImageGrab

            ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(args.screenshot)
        REPORT["win"] = [win.x, win.y, win.width, win.height]
        REPORT["ram"] = tree_pss()
        if not args.no_dnd and not args.url:
            src = do_drag(win)  # nguồn kéo phải còn sống cho tới khi trang nhận xong
            REPORT["drop_received"] = GOT["dropEvent"].wait(8)
            GOT["drop"].wait(3)
            src.terminate()
    except Exception as ex:  # noqa: BLE001
        REPORT["probe_error"] = f"{type(ex).__name__}: {ex}"
    finally:
        win.destroy()


def main() -> None:
    make_assets()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/probe.html"
    win = webview.create_window("probe", url, width=1000, height=700, x=250, y=40)
    t0 = time.time()
    store = str(WORK / "profile")
    webview.start(runner, win, gui=args.backend, private_mode=False, storage_path=store)
    REPORT["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(REPORT, ensure_ascii=False))
    srv.shutdown()


try:
    main()
finally:
    import shutil

    shutil.rmtree(WORK, ignore_errors=True)
