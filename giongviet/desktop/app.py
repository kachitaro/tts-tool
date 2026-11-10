#!/usr/bin/env python3
"""Giọng Việt — app cửa sổ riêng (pywebview + WebKitGTK). Chạy: giong-viet  (hoặc: python -m giongviet.desktop)

Cách chạy:
  - uvicorn chạy trong một luồng nền ở cổng trống chỉ nghe 127.0.0.1 (cổng chọn ngẫu nhiên lần đầu rồi nhớ để giữ localStorage);
  - cửa sổ mở ngay với màn chờ "Đang khởi động…", nạp giao diện khi /api/engines trả 200;
  - chỉ một bản cho mỗi thư mục dữ liệu: mở lần 2 đưa cửa sổ đang có lên trước rồi thoát;
  - nhớ kích thước / vị trí / phóng to-thu nhỏ cửa sổ (~/.config/giong-viet/window.json);
  - đóng cửa sổ khi đang tạo sách nói thì hỏi: chạy nền (khay hệ thống, hoặc thu nhỏ nếu không có khay) hoặc tạm dừng và thoát.
Vẫn chạy kiểu cũ được: python -m giongviet rồi mở trình duyệt (dùng khi chạy từ xa).

  -m giongviet.desktop --selftest   khởi động server + cửa sổ ẩn, kiểm tra các luồng chính, đóng sạch (dùng trong tests/smoke/smoke_test.sh)
  GV_DEBUG=1          bật menu chuột phải đầy đủ (có Inspect) và mở bảng debug
  GV_DEBUG_CORNERS=1  viền đỏ quanh vùng bo góc cửa sổ (chụp màn hình kiểm tra trên máy thật)
  GV_CORNER_RADIUS=N  ép bán kính bo góc (px) thay vì đọc từ GTK theme
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import logging.handlers
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from fastapi import (  # cấp module: FastAPI cần phân giải kiểu của tham số (file này có `from __future__ import annotations`)
    HTTPException,
    Request,
)
from fastapi.responses import FileResponse

from giongviet.paths import ROOT, WEB  # noqa: E402  (desktop/app.py có hàm paths() riêng, đừng import module paths)

APP_NAME, APP_ID = "Giọng Việt", "giong-viet"
DEBUG = os.getenv("GV_DEBUG") == "1"
ICON_SVG = Path(__file__).resolve().parent / "giong-viet.svg"
log = logging.getLogger("giong-viet")


def _xdg(env: str, default: str) -> Path:
    return Path(os.getenv(env) or Path.home() / default) / APP_ID


def paths() -> dict:
    """Thư mục của app (đọc env lúc gọi để --selftest chuyển hết sang thư mục tạm)."""
    runtime = Path(
        os.getenv("GV_RUNTIME_DIR")
        or os.getenv("XDG_RUNTIME_DIR")
        or f"/tmp/{APP_ID}-{os.getuid()}"
    )
    return {
        "config": _xdg("XDG_CONFIG_HOME", ".config"),
        "state": _xdg("XDG_STATE_HOME", ".local/state"),
        "share": _xdg("XDG_DATA_HOME", ".local/share"),
        "runtime": runtime,
    }


def data_dir() -> Path:
    return Path(os.getenv("TTS_DATA_DIR", ROOT / "data")).resolve()


def setup_logging(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / "app.log"
    h = logging.handlers.RotatingFileHandler(f, maxBytes=512_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.INFO)
    if sys.stderr and sys.stderr.isatty():
        root.addHandler(logging.StreamHandler(sys.stderr))
    return f


# ───────────── một bản duy nhất ─────────────
class SingleInstance:
    """Khoá flock + socket unix cho mỗi thư mục dữ liệu (hai server trên một data/ không được hỗ trợ). Bản thứ hai gửi "raise"."""

    def __init__(self, runtime: Path, key: str) -> None:
        runtime.mkdir(parents=True, exist_ok=True)
        self.lock_path = runtime / f"{APP_ID}-{key}.lock"
        self.sock_path = runtime / f"{APP_ID}-{key}.sock"
        self._fd: int | None = None
        self._srv: socket.socket | None = None

    def acquire(self) -> bool:
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd
        return True

    def ask_existing(self, token: str = "", route: str = "") -> bool:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        try:
            s.connect(str(self.sock_path))
            s.sendall(f"raise\t{token}\t{route}\n".encode())
            return s.recv(16).startswith(b"ok")
        except OSError:
            return False
        finally:
            s.close()

    def acquire_or_raise(self, token: str = "", route: str = "", timeout: float = 20) -> str:
        """ "owner": bản này là bản duy nhất · "raised": bản khác đang chạy và đã được nhắc đưa cửa sổ lên · "failed"."""
        end = time.time() + timeout
        while True:
            if self.acquire():
                return "owner"
            if self.ask_existing(token, route):
                return "raised"
            if time.time() > end:
                return "failed"
            time.sleep(
                0.2
            )  # bản kia đang khởi động (chưa mở socket) hoặc đang thoát (chưa nhả khoá)

    def serve(self, on_raise) -> None:
        self.sock_path.unlink(missing_ok=True)
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(str(self.sock_path))
        os.chmod(self.sock_path, 0o600)
        srv.listen(4)
        self._srv = srv

        def loop() -> None:
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                try:
                    msg = conn.recv(1024).decode(errors="replace").rstrip("\n").split("\t")
                    if msg[0] == "raise":
                        try:
                            on_raise(*(msg[1:3] + ["", ""])[:2])
                        except Exception:  # noqa: BLE001
                            log.exception("không đưa được cửa sổ lên trước")
                        conn.sendall(b"ok\n")
                except OSError:
                    pass
                finally:
                    conn.close()

        threading.Thread(target=loop, name="single-instance", daemon=True).start()

    def close(self) -> None:
        if self._srv:
            self._srv.close()
            self._srv = None
        self.sock_path.unlink(missing_ok=True)
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class Prefs:
    """Trạng thái cửa sổ: width, height, x, y, maximized, zoom, port, save_dir."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.d = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            self.d = {}
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def get(self, k: str, default: Any = None) -> Any:
        return self.d.get(k, default)

    def update(self, **kw) -> None:
        with self._lock:
            self.d.update({k: v for k, v in kw.items() if v is not None})

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.d, indent=1), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                log.exception("không ghi được %s", self.path)

    def save_soon(self, delay: float = 1.0) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(delay, self.save)
        self._timer.daemon = True
        self._timer.start()


# màn chờ không nạp /css của server nên nhúng nguyên file bo góc (một nguồn duy nhất cho cả giao diện thật lẫn màn chờ)
CORNER_CSS = (WEB / "css" / "app-window.css").read_text(encoding="utf-8")


def splash(msg: str, sub: str = "", detail: str = "", spinning: bool = True) -> str:
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    return f"""<!doctype html><html lang="vi" class="app-window"><meta charset="utf-8"><title>{APP_NAME}</title>
<style>
{CORNER_CSS}
:root{{--bg:#f7f6f3;--text:#1d1b16;--muted:#6a665b;--accent:#2f6f5e;--line:#e3e0d8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14161a;--text:#eceae4;--muted:#a29e92;--accent:#58b79f;--line:#333842}}}}
html,body{{height:100%;margin:0;background:var(--bg);color:var(--text);font:18px/1.5 system-ui,"Noto Sans",sans-serif}}
main{{min-height:100%;display:grid;place-content:center;justify-items:center;gap:14px;text-align:center;padding:24px;box-sizing:border-box}}
.logo{{font-size:34px;font-weight:700}} .logo b{{color:var(--accent)}}
.spin{{width:34px;height:34px;border:4px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:s 1s linear infinite}}
@keyframes s{{to{{transform:rotate(360deg)}}}}
p{{margin:0;color:var(--muted)}} .msg{{color:var(--text);font-weight:600}}
pre{{max-width:72ch;text-align:left;white-space:pre-wrap;color:var(--muted);font-size:13px;margin:0}}
@media (prefers-reduced-motion:reduce){{.spin{{animation:none}}}}
</style>
<main><div class="logo"><b>Giọng</b> Việt</div>{'<div class="spin" role="status" aria-label="Đang chờ"></div>' if spinning else ""}
<p class="msg">{esc(msg)}</p><p>{esc(sub)}</p>{f"<details><summary>Xem chi tiết</summary><pre>{esc(detail)}</pre></details>" if detail else ""}</main></html>"""


def norm_route(r: str) -> str:
    """Đường dẫn trong giao diện để mở thẳng tới (vd. /doc, /sach/them). Chỉ nhận ký tự an toàn."""
    r = (r or "").strip().lstrip("#")
    return r if re.fullmatch(r"/[A-Za-z0-9_\-./%]*", r) else ""


def http(url: str, method: str = "GET", timeout: float = 10) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        data=b"{}" if method == "POST" else None,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


ZOOMS = [0.5, 0.67, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]


class Api:
    """Hàm Python gọi từ JS qua window.pywebview.api (xem web/js/appenv.js). Mọi trạng thái để ở app._ vì pywebview lộ thuộc tính công khai."""

    def __init__(self, app: App) -> None:
        self._app = app

    def info(self) -> dict[str, Any]:
        a = self._app
        return {
            "app": True,
            "backend": "gtk",
            "debug": DEBUG,
            "tray": a.tray_ok,
            "port": a.port,
            "zoom": a.zoom,
        }

    def save_dialog(self, name: str) -> dict[str, Any]:
        """Hộp thoại "Lưu thành…" gốc. Trả {ok, token, path}; dữ liệu đưa sau qua save_url (từ server) hoặc PUT /_app/save/<token> (từ blob)."""
        import webview

        a = self._app
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", Path(str(name)).name)[:120] or "tai-ve"
        start = a.prefs.get("save_dir") or a.gtk.downloads_dir()
        res = a.window.create_file_dialog(
            webview.FileDialog.SAVE, directory=start, save_filename=name
        )
        if not res:
            return {"ok": False}
        path = Path(res if isinstance(res, str) else res[0])
        a.prefs.update(save_dir=str(path.parent))
        a.prefs.save_soon()
        tok = secrets.token_urlsafe(16)
        a.save_targets[tok] = path
        return {"ok": True, "token": tok, "path": str(path)}

    def save_url(self, token: str, url: str) -> dict[str, Any]:
        """Chép một đường dẫn trên server (/api/…) vào file đã chọn (không đọc cả file vào bộ nhớ trình duyệt)."""
        a = self._app
        dest = a.save_targets.pop(token, None)
        if dest is None:
            return {"ok": False, "error": "Phiên lưu đã hết hạn."}
        if not url.startswith("/") or url.startswith("//"):
            return {"ok": False, "error": "Đường dẫn không hợp lệ."}
        part = dest.with_name(dest.name + ".part")
        try:
            with (
                urllib.request.urlopen(f"http://127.0.0.1:{a.port}{url}", timeout=120) as r,
                part.open("wb") as f,
            ):
                shutil.copyfileobj(r, f, 1 << 20)
            part.replace(dest)
            return {"ok": True, "path": str(dest), "bytes": dest.stat().st_size}
        except urllib.error.HTTPError as ex:
            try:
                msg = json.loads(ex.read()).get("error")
            except ValueError, OSError:
                msg = None
            return {"ok": False, "error": msg or f"Server trả lỗi {ex.code}."}
        except OSError as ex:
            return {"ok": False, "error": f"Không ghi được file: {ex.strerror or ex}"}
        finally:
            part.unlink(missing_ok=True)

    def dropped_files(self) -> list[dict[str, Any]]:
        """File vừa được thả vào cửa sổ (WebKitGTK không đưa File cho trang). Mỗi file có URL dùng một lần để fetch."""
        a = self._app
        end = time.time() + 0.8
        while (
            not a.drops and time.time() < end
        ):  # DOM drop có thể tới trước tín hiệu kéo thả của GTK một chút
            time.sleep(0.03)
        with a.lock:
            paths, a.drops = a.drops, []
        out = []
        for p in paths:
            try:
                if not p.is_file():
                    continue
                st = p.stat()
            except OSError:
                continue
            tok = secrets.token_urlsafe(16)
            a.drop_files[tok] = p
            out.append(
                {
                    "name": p.name,
                    "url": f"/_app/drop/{tok}",
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "type": mimetypes.guess_type(p.name)[0] or "",
                }
            )
        return out

    def zoom(self, how: str) -> float:
        a = self._app
        z = a.zoom
        if how == "in":
            z = next((s for s in ZOOMS if s > z + 1e-6), ZOOMS[-1])
        elif how == "out":
            z = next((s for s in reversed(ZOOMS) if s < z - 1e-6), ZOOMS[0])
        else:
            z = 1.0
        a.set_zoom(z)
        return z

    def close_choice(self, choice: str) -> bool:
        """Trả lời hộp hỏi khi đóng cửa sổ lúc đang tạo sách nói: "background" | "quit" | (khác = ở lại)."""
        a = self._app
        if choice == "background":
            a.go_background()
        elif choice == "quit":
            a.quit(pause=True)
        return True


class App:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.selftest = args.selftest
        self.P = paths()
        self.prefs = Prefs(self.P["config"] / "window.json")
        self.lock = threading.Lock()
        self.window = None
        self.gtk = None
        self.port = 0
        self.sock: socket.socket | None = None
        self.uv = None
        self.server_thread: threading.Thread | None = None
        self.server_error = ""
        self.save_targets: dict[str, Path] = {}
        self.drop_files: dict[str, Path] = {}
        self.drops: list[Path] = []
        self.zoom = float(self.prefs.get("zoom", 1.0) or 1.0)
        self.tray = None
        self.tray_ok = False
        self.bg = False
        self.quitting = False
        self.raises = 0
        self.si: SingleInstance | None = None
        self.results: list[tuple[bool, str, str]] = []  # selftest
        self.selftest_force_close = False
        self.url_loaded = False
        self.t_start = time.time()
        self.pref_port_at_start = self.prefs.get("port")
        self.route = norm_route(getattr(args, "route", ""))
        self._geo_timer: threading.Timer | None = None

    # ───────────── server ─────────────
    def listen_socket(self) -> socket.socket:
        for port in [
            p for p in [self.prefs.get("port")] if isinstance(p, int) and 1024 <= p < 65536
        ] + [0]:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))  # chỉ loopback: không ai ngoài máy này vào được
            except OSError:
                s.close()
                continue
            return s
        raise OSError("không có cổng trống")

    def start_server(self) -> None:
        import uvicorn

        from giongviet import (
            server,  # nặng (numpy, librosa, engines…): làm ở luồng nền để màn chờ hiện ngay
        )

        self.add_routes(server.app)
        cfg = uvicorn.Config(
            server.app, log_level="warning", access_log=False, timeout_graceful_shutdown=15
        )
        self.uv = uvicorn.Server(cfg)

        def serve() -> None:
            try:
                self.uv.run(sockets=[self.sock])
            except BaseException:  # noqa: BLE001
                self.server_error = traceback.format_exc()
                log.error("server dừng: %s", self.server_error)

        self.server_thread = threading.Thread(target=serve, name="uvicorn", daemon=True)
        self.server_thread.start()

    def add_routes(self, fastapi_app) -> None:
        """Hai route chỉ có trong app cửa sổ riêng (không nằm trong server.py): nhận blob để lưu file, và phát lại file vừa kéo thả."""

        @fastapi_app.put("/_app/save/{token}")
        async def app_save(token: str, request: Request):
            dest = self.save_targets.pop(token, None)
            if dest is None:
                raise HTTPException(404, "Phiên lưu đã hết hạn.")
            part, n = dest.with_name(dest.name + ".part"), 0
            try:
                with part.open("wb") as f:
                    async for chunk in request.stream():
                        f.write(chunk)
                        n += len(chunk)
                part.replace(dest)
            except OSError as ex:
                part.unlink(missing_ok=True)
                raise HTTPException(500, f"Không ghi được file: {ex.strerror or ex}") from ex
            return {"ok": True, "path": str(dest), "bytes": n}

        @fastapi_app.get("/_app/drop/{token}")
        def app_drop(token: str) -> FileResponse:
            p = self.drop_files.pop(token, None)  # dùng một lần
            if p is None or not p.is_file():
                raise HTTPException(404, "File đã hết hạn.")
            return FileResponse(
                p, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            )

    def wait_ready(self, timeout: float = 240) -> None:
        url = f"http://127.0.0.1:{self.port}/api/engines"
        t = time.time()
        while time.time() - t < timeout:
            if self.server_thread is not None and not self.server_thread.is_alive():
                raise RuntimeError(self.server_error or "server đã dừng bất ngờ")
            try:
                if http(url, timeout=3)[0] == 200:
                    return
            except urllib.error.URLError, OSError, TimeoutError:
                pass
            time.sleep(0.25)
        raise TimeoutError("server không trả lời /api/engines")

    def stop_server(self, wait: float = 130) -> bool:
        """Tắt server như Ctrl+C: chờ nốt đoạn đang dựng, trả chương dở về hàng đợi, nhả systemd-inhibit. True nếu luồng đã dừng."""
        if self.uv is not None:
            self.uv.should_exit = True
        if self.server_thread is not None:
            self.server_thread.join(wait)
            return not self.server_thread.is_alive()
        return True

    def server_get(self, path: str) -> Any:
        return json.loads(http(f"http://127.0.0.1:{self.port}{path}")[1])

    def busy(self) -> bool:
        """Đang tạo sách nói? (hàng đợi đang chạy hoặc đang dừng ở ranh giới đoạn; tạm dừng hẳn thì không tính)."""
        try:
            bookq = sys.modules.get("giongviet.books.jobs")
            return bool(bookq and bookq.Q.status()["state"] in ("running", "pausing"))
        except Exception:  # noqa: BLE001
            return False

    # ───────────── cửa sổ ─────────────
    def set_zoom(self, z: float) -> None:
        self.zoom = z
        self.gtk.set_zoom(self.window, z)
        self.prefs.update(zoom=z)
        self.prefs.save_soon()

    def save_geometry(self) -> None:
        try:
            g = self.gtk.geometry(self.window)
        except Exception:  # noqa: BLE001
            return
        upd = {"maximized": g["maximized"]}
        if not g["maximized"]:
            upd.update(width=g["width"], height=g["height"])
            if not self.gtk.is_wayland():  # Wayland không cho ứng dụng biết / đặt vị trí cửa sổ
                upd.update(x=g["x"], y=g["y"])
        self.prefs.update(**upd)
        self.prefs.save()

    def on_closing(self) -> bool:
        """Chạy ở luồng giao diện: trả False để chặn việc đóng."""
        if self.quitting or self.selftest_force_close:
            return True  # đang thoát chủ động
        if self.busy():
            threading.Thread(target=self.ask_close, daemon=True).start()
            return False
        self.save_geometry()
        return True

    def geo_changed(self, *_) -> None:
        """Kéo / đổi cỡ cửa sổ bắn rất nhiều sự kiện: chờ yên 2 giây rồi mới ghi."""
        if self._geo_timer:
            self._geo_timer.cancel()
        self._geo_timer = threading.Timer(2.0, self.save_geometry)
        self._geo_timer.daemon = True
        self._geo_timer.start()

    def ask_close(self) -> None:
        try:
            r = self.window.evaluate_js(
                "typeof window.gvAppClose === 'function' ? (window.gvAppClose(), 'ok') : 'none'"
            )
        except Exception:  # noqa: BLE001
            r = "none"
        if (
            r != "ok"
        ):  # trang chưa nạp xong / không hỏi được: an toàn nhất là không mất việc đang làm
            log.warning("không hỏi được người dùng khi đóng cửa sổ, chạy nền tiếp")
            self.go_background()

    def go_background(self) -> None:
        self.save_geometry()
        with self.lock:
            self.bg = True
        if self.tray_ok and self.ensure_tray():
            self.tray.show()
            threading.Thread(target=self.tray_poll, name="tray-poll", daemon=True).start()
            self.window.hide()
        else:
            self.window.minimize()

    def ensure_tray(self) -> bool:
        if self.tray is None:
            try:
                self.tray = self.gtk.Tray(
                    str(ICON_SVG.parent),
                    "giong-viet",
                    self.show_window,
                    self.toggle_pause,
                    lambda: self.quit(pause=self.busy()),
                )
            except Exception:  # noqa: BLE001
                log.exception("không tạo được biểu tượng khay")
                self.tray_ok = False
                return False
        return True

    def tray_poll(self) -> None:
        while self.bg and not self.quitting:
            try:
                cur = self.server_get("/api/overview").get("current")
                if cur:
                    n = (
                        f"chương {cur['chapter']}/{cur['chapters']}"
                        if cur.get("chapter")
                        else f"{cur['done']}/{cur['chapters']} chương"
                    )
                    self.tray.update(
                        f"{'Tạm dừng' if cur.get('paused') else 'Đang tạo'}: {cur['title']}, {n}",
                        "Tiếp tục" if cur.get("paused") else "Tạm dừng",
                    )
                else:
                    self.tray.update("Không có việc đang chạy", None)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)

    def toggle_pause(self) -> None:
        try:
            paused = self.server_get("/api/queue")["paused"]
            http(
                f"http://127.0.0.1:{self.port}/api/queue/{'resume' if paused else 'pause'}", "POST"
            )
        except Exception:  # noqa: BLE001
            log.exception("không đổi được trạng thái tạm dừng")

    def show_window(self, token: str = "") -> None:
        with self.lock:
            self.bg = False
        if self.window is None:
            return
        if self.tray is not None:
            self.tray.hide()
        self.gtk.present(self.window, token or None)

    def on_raise(self, token: str = "", route: str = "") -> None:
        self.raises += 1
        self.show_window(token)
        if route and self.window is not None and self.url_loaded:
            self.window.evaluate_js(f"location.hash = {json.dumps('#' + route)}")

    def quit(self, pause: bool = False) -> None:
        with self.lock:
            if self.quitting:
                return
            self.quitting = True
        threading.Thread(target=self._quit, args=(pause,), name="quit", daemon=True).start()

    def _quit(self, pause: bool) -> None:
        log.info("thoát (pause=%s)", pause)
        try:
            self.save_geometry()
            if pause:
                try:
                    http(
                        f"http://127.0.0.1:{self.port}/api/queue/pause", "POST"
                    )  # trạng thái tạm dừng được lưu: lần mở sau không tự chạy tiếp
                except Exception:  # noqa: BLE001
                    log.exception("không tạm dừng được hàng đợi")
            if self.window is not None and self.gtk.is_shown(self.window):
                try:
                    self.window.load_html(
                        splash(
                            "Đang lưu việc đang làm dở…",
                            "Vài giây nữa là xong, bạn không cần làm gì.",
                        )
                    )
                except Exception:  # noqa: BLE001
                    pass
            if not self.stop_server():
                log.error("server chưa dừng sau khi chờ")
        finally:
            if self.tray is not None:
                self.tray.hide()
            if self.window is not None:
                self.window.destroy()

    # ───────────── chạy ─────────────
    def run(self) -> int:
        P = self.P
        self.log_file = setup_logging(P["state"])
        key = hashlib.sha1(str(data_dir()).encode()).hexdigest()[:10]
        self.si = SingleInstance(P["runtime"], key)
        mode = self.si.acquire_or_raise(
            os.getenv("XDG_ACTIVATION_TOKEN") or os.getenv("DESKTOP_STARTUP_ID") or "", self.route
        )
        if mode == "raised":
            print(f"{APP_NAME} đang chạy: đã đưa cửa sổ đang có lên trước.")
            return 0
        if mode == "failed":
            print(
                f"{APP_NAME} đang chạy nhưng không phản hồi. Đóng nó (hoặc kill) rồi thử lại.",
                file=sys.stderr,
            )
            return 1
        try:
            return self._run_owner()
        finally:
            self.si.close()

    def _run_owner(self) -> int:
        if not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
            print(
                "Không có màn hình đồ hoạ (DISPLAY / WAYLAND_DISPLAY). Chạy từ xa thì dùng: python -m giongviet",
                file=sys.stderr,
            )
            return 3 if self.selftest else 2
        try:
            import webview

            from giongviet.desktop import gtk as gtk
        except (RuntimeError, ImportError) as ex:
            msg = (
                str(ex)
                if isinstance(ex, RuntimeError)
                else f"Thiếu pywebview ({ex}). Cài: python -m pip install -r requirements-app.txt"
            )
            print(msg, file=sys.stderr)
            log.error(msg)
            if shutil.which("notify-send"):
                os.system(
                    "notify-send -a 'Giọng Việt' 'Không mở được Giọng Việt' 'Thiếu thư viện giao diện, xem README (mục App cửa sổ riêng).'"
                )
            return 4
        self.gtk = gtk
        gtk.set_app_identity(APP_ID, APP_NAME)
        self.tray_ok = gtk.tray_available() and not self.args.no_tray and not self.selftest
        self.si.serve(self.on_raise)
        gtk.handle_signals(lambda sig: (log.info("nhận %s", sig), self.quit(pause=False)))

        self.sock = self.listen_socket()
        self.port = self.sock.getsockname()[1]
        self.prefs.update(port=self.port)

        w, h = int(self.prefs.get("width", 1100)), int(self.prefs.get("height", 780))
        x, y = self.prefs.get("x"), self.prefs.get("y")
        if not (isinstance(x, int) and isinstance(y, int) and gtk.point_visible(x + 40, y + 20)):
            x = y = None
        self.window = webview.create_window(
            APP_NAME,
            html=splash("Đang khởi động…", "Lần đầu có thể mất một lúc."),
            js_api=Api(self),
            width=w,
            height=h,
            x=x,
            y=y,
            min_size=(360, 480),
            hidden=self.selftest,
            maximized=bool(self.prefs.get("maximized")),
            text_select=True,
            background_color="#f7f6f3",
        )
        ev = self.window.events
        ev.closing += self.on_closing
        ev.resized += self.geo_changed
        ev.moved += self.geo_changed
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = DEBUG
        icon = str(ICON_SVG) if ICON_SVG.is_file() and gtk.svg_ok(str(ICON_SVG)) else None
        try:
            webview.start(
                self.boot,
                gui="gtk",
                debug=True,
                private_mode=False,
                storage_path=str(self.P["share"] / "webview"),
                icon=icon,
            )
        finally:
            self.cleanup()
        if self.selftest:
            return self.report_selftest()
        return 0

    def boot(self) -> None:
        """Luồng nền sau khi vòng lặp giao diện chạy: bật server, chờ sẵn sàng, rồi nạp giao diện (hoặc chạy selftest)."""
        t0 = time.time()
        try:
            if not DEBUG:
                logging.getLogger("pywebview").setLevel(logging.WARNING)
            self.gtk.attach(self.window, debug=DEBUG, on_uris=self.on_uris)
            self.gtk.install_corners(self.window, debug=os.getenv("GV_DEBUG_CORNERS") == "1")
            log.info("cửa sổ đã mở (màn chờ), %.1f giây từ lúc chạy", time.time() - self.t_start)
            self.start_server()
            self.wait_ready()
            log.info("server sẵn sàng sau %.1f giây, cổng %s", time.time() - t0, self.port)
            self.window.events.loaded += self.on_loaded
            self.window.load_url(
                f"http://127.0.0.1:{self.port}/" + (f"#{self.route}" if self.route else "")
            )
            self.url_loaded = True
            if self.selftest:
                self.run_selftest()
        except Exception:  # noqa: BLE001
            err = traceback.format_exc()
            log.error("không khởi động được: %s", err)
            try:
                self.window.load_html(
                    splash(
                        "Không khởi động được Giọng Việt.",
                        f"Nhật ký: {self.log_file}",
                        err,
                        spinning=False,
                    )
                )
            except Exception:  # noqa: BLE001
                pass
            if self.selftest:
                self.results.append((False, "khởi động", err.strip().splitlines()[-1]))
                self.finish_selftest()

    def on_loaded(self) -> None:
        if abs(self.zoom - 1.0) > 1e-6:
            self.gtk.set_zoom(self.window, self.zoom)

    def on_uris(self, uris) -> None:
        paths = self.gtk.uris_to_paths(uris)
        if paths:
            with self.lock:
                self.drops = paths

    def cleanup(self) -> None:
        """Sau khi cửa sổ đóng: tắt server (nếu chưa), nhả khoá. Gọi nhiều lần cũng được."""
        self.quitting = True
        self.prefs.save()
        if not self.stop_server():
            log.error("server không dừng được, ép thoát")
        if self.tray is not None:
            self.tray.hide()

    # ───────────── selftest ─────────────
    def check(self, name: str, fn) -> None:
        try:
            fn()
            self.results.append((True, name, ""))
        except Exception as ex:  # noqa: BLE001
            self.results.append((False, name, f"{type(ex).__name__}: {ex}"[:300]))

    def js(self, expr: str, timeout: float = 20) -> Any:
        return self.window.evaluate_js(expr)

    def run_selftest(self) -> None:
        import subprocess

        assert self.window.events.loaded.wait(30), "trang không nạp xong"
        base = f"http://127.0.0.1:{self.port}"

        def engines() -> None:
            s, b = http(base + "/api/engines")
            assert s == 200 and json.loads(b)

        def loopback_only() -> None:
            assert self.sock.getsockname()[0] == "127.0.0.1", self.sock.getsockname()

        def ui_mounted() -> None:
            t = time.time()
            while time.time() - t < 20:
                if self.js(
                    "document.querySelector('#view') && document.querySelector('#view').children.length"
                ):
                    return
                time.sleep(0.2)
            raise AssertionError("giao diện không dựng được (#view rỗng)")

        def in_webview() -> None:
            assert self.js("!!window.pywebview") is True
            t = time.time()
            while time.time() - t < 10 and not self.js(
                "!!(window.pywebview.api && window.pywebview.api.info)"
            ):
                time.sleep(0.2)
            self.js(
                "window.__info = null; window.pywebview.api.info().then(i => { window.__info = i; })"
            )
            t = time.time()
            while time.time() - t < 5 and not self.js("window.__info"):
                time.sleep(0.1)
            got = self.js("window.__info && window.__info.backend")
            assert got == "gtk", got

        def local_storage() -> None:
            self.js("localStorage.setItem('gv:selftest', '1')")
            assert self.js("localStorage.getItem('gv:selftest')") == "1"
            self.js("localStorage.removeItem('gv:selftest')")
            self.js(
                "localStorage.setItem('gv:voice-last', 'vong-1')"
            )  # vòng 2 của selftest kiểm giá trị này còn không (phải là khoá còn dùng, khoá lạ bị cleanupStorage xoá lúc khởi động)

        def persisted() -> None:
            assert self.pref_port_at_start and self.port == self.pref_port_at_start, (
                f"cổng đổi: {self.pref_port_at_start} → {self.port}"
            )
            got = self.js("localStorage.getItem('gv:voice-last')")
            ls = self.P["share"] / "webview" / "localstorage"
            files = {f.name: f.stat().st_size for f in ls.iterdir()} if ls.is_dir() else None
            assert got == "vong-1", (
                f"localStorage mất sau khi mở lại app: {got!r}; thư mục lưu: {files}"
            )

        def single_instance() -> None:
            env = dict(os.environ)
            before = self.raises
            r = subprocess.run(
                [sys.executable, "-m", "giongviet.desktop", "/giong"],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert r.returncode == 0, (r.returncode, r.stderr[-200:])
            assert "đã đưa cửa sổ" in r.stdout, r.stdout
            assert self.raises == before + 1, "bản đang chạy không nhận được yêu cầu đưa cửa sổ lên"
            t = time.time()
            while (
                time.time() - t < 5 and self.js("location.hash") != "#/giong"
            ):  # đối số "/giong" của bản 2 đưa bản 1 tới màn đó
                time.sleep(0.2)
            assert self.js("location.hash") == "#/giong", self.js("location.hash")

        def save_via_server() -> None:
            d = Path(tempfile.mkdtemp(prefix="gv_save_"))
            try:
                out = d / "engines.json"
                tok = secrets.token_urlsafe(8)
                self.save_targets[tok] = out
                r = Api(self).save_url(tok, "/api/engines")
                assert r["ok"] and json.loads(out.read_text()), r
                assert Api(self).save_url(tok, "/api/engines")["ok"] is False  # mã chỉ dùng một lần
                tok = secrets.token_urlsafe(8)
                self.save_targets[tok] = out
                assert Api(self).save_url(tok, "//evil.example/x")["ok"] is False
            finally:
                shutil.rmtree(d, ignore_errors=True)

        def save_blob() -> None:
            d = Path(tempfile.mkdtemp(prefix="gv_save_"))
            try:
                out, tok, payload = d / "blob.bin", secrets.token_urlsafe(8), os.urandom(300_000)
                self.save_targets[tok] = out
                req = urllib.request.Request(f"{base}/_app/save/{tok}", data=payload, method="PUT")
                with urllib.request.urlopen(req, timeout=20) as r:
                    assert json.loads(r.read())["bytes"] == len(payload)
                assert out.read_bytes() == payload
            finally:
                shutil.rmtree(d, ignore_errors=True)

        def dropped() -> None:
            d = Path(tempfile.mkdtemp(prefix="gv_drop_"))
            try:
                f = d / "chuong 1.txt"
                f.write_text("xin chào", encoding="utf-8")
                self.on_uris([f.as_uri(), d.as_uri()])  # thư mục bị bỏ qua
                got = Api(self).dropped_files()
                assert [g["name"] for g in got] == ["chuong 1.txt"], got
                assert http(base + got[0]["url"])[1] == "xin chào".encode()
                assert Api(self).dropped_files() == []  # lấy xong thì hết
            finally:
                shutil.rmtree(d, ignore_errors=True)

        def microphone_allowed() -> None:
            # WebKitGTK từ chối getUserMedia nếu không ai cho phép: app phải cho phép. Máy không có micro → NotFoundError cũng là đạt.
            self.js(
                "window.__mic = null; navigator.mediaDevices.getUserMedia({audio: true}).then(s => { s.getTracks().forEach(t => t.stop()); window.__mic = 'ok'; }).catch(e => { window.__mic = e.name; })"
            )
            t = time.time()
            while time.time() - t < 20 and not self.js("window.__mic"):
                time.sleep(0.2)
            got = self.js("window.__mic")
            assert got in ("ok", "NotFoundError"), f"getUserMedia: {got}"
            self.mic_result = got

        def dialog_when_busy() -> None:
            # giả lập "đang tạo": app phải chặn việc đóng và hỏi trong trang; "Ở lại" thì không có gì xảy ra
            real = self.busy
            self.busy = lambda: True
            try:
                assert self.on_closing() is False
            finally:
                self.busy = real
            t = time.time()
            while time.time() - t < 10 and not self.js("!!document.querySelector('#closeBg')"):
                time.sleep(0.2)
            assert self.js(
                "!!document.querySelector('#closeBg') && !!document.querySelector('#closeQuit')"
            ), "hộp hỏi không hiện"
            assert self.js(
                "document.querySelector('.modal').innerText.includes('Chạy nền tiếp') || document.querySelector('.modal').innerText.includes('Đang tạo')"
            )
            self.js("document.querySelector('.modal .btn.ghost').click()")  # Ở lại
            assert not self.quitting

        def idle_close_allowed() -> None:
            assert self.on_closing() is True  # không có việc gì: cho đóng ngay

        def rounded_corners() -> None:
            g = self.gtk
            assert g.is_square(g.Gdk.WindowState.MAXIMIZED) and g.is_square(g.Gdk.WindowState.TILED)
            assert g.is_square(g.Gdk.WindowState.FULLSCREEN) and not g.is_square(
                g.Gdk.WindowState(0)
            )
            t = time.time()
            while time.time() - t < 10 and not self.js(
                "document.documentElement.classList.contains('app-window')"
            ):
                time.sleep(0.2)
            clip = "getComputedStyle(document.documentElement).clipPath"
            assert self.js("document.documentElement.classList.contains('app-window')"), (
                "trang không có class app-window"
            )
            assert "round" in str(self.js(clip)), self.js(
                clip
            )  # cửa sổ thường: góc dưới bị cắt tròn
            radius = self.js("document.documentElement.style.getPropertyValue('--app-radius')")
            assert radius == f"{g.theme_radius()}px", radius
            self.js(
                g.corners_script(g.theme_radius(), True, False)
            )  # phóng to / ghép màn hình: không bo
            assert self.js(clip) == "none", self.js(clip)
            self.js(g.corners_script(g.theme_radius(), False, False))
            assert "round" in str(self.js(clip))
            html = splash(
                "Đang khởi động…"
            )  # màn chờ cũng bo góc: cùng quy tắc, nhúng từ chung một file
            assert 'class="app-window"' in html and CORNER_CSS.strip() in html

        def zoom_keys() -> None:
            self.js(
                "window.__z = null; window.pywebview.api.zoom('in').then(z => { window.__z = z; })"
            )
            t = time.time()
            while time.time() - t < 5 and not self.js("window.__z"):
                time.sleep(0.1)
            assert abs(self.js("window.__z") - 1.1) < 1e-6
            self.js("window.pywebview.api.zoom('reset')")
            time.sleep(0.3)
            assert self.zoom == 1.0

        if (
            os.getenv("GV_SELFTEST_ROUND") == "2"
        ):  # mở lại app lần nữa với cùng thư mục: cổng và localStorage phải còn
            for name, fn in [
                ("app: mở lại app — server lên lại, /api/engines 200", engines),
                ("app: mở lại app — dùng lại đúng cổng cũ và localStorage còn nguyên", persisted),
            ]:
                self.check(name, fn)
            return self.finish_selftest()
        for name, fn in [
            ("app: server trả /api/engines 200 sau khi chờ sẵn sàng", engines),
            ("app: server chỉ nghe 127.0.0.1", loopback_only),
            ("app: giao diện dựng xong trong cửa sổ (#view có nội dung)", ui_mounted),
            ("app: window.pywebview + js_api (backend gtk) có trong trang", in_webview),
            ("app: localStorage dùng được (lưu bền ở thư mục riêng của app)", local_storage),
            (
                "app: mở lần 2 → bản đang chạy được nhắc đưa cửa sổ lên, bản 2 thoát mã 0, không có server thứ hai",
                single_instance,
            ),
            (
                "app: Tải về — save_url chép từ server, mã dùng một lần, từ chối đường dẫn ngoài",
                save_via_server,
            ),
            ("app: Tải về — PUT /_app/save/<mã> ghi nguyên khối blob 300 KB", save_blob),
            (
                "app: kéo thả — đường dẫn file được giữ, phát lại qua URL một lần, bỏ thư mục",
                dropped,
            ),
            ("app: micro — getUserMedia không bị chặn quyền trong cửa sổ app", microphone_allowed),
            ("app: phóng to / thu nhỏ qua js_api, về mặc định", zoom_keys),
            (
                "app: bo góc dưới — class + clip-path + bán kính theo theme, không bo khi phóng to / ghép màn hình, màn chờ có cùng CSS",
                rounded_corners,
            ),
            (
                "app: đang tạo mà đóng cửa sổ → chặn đóng + hộp hỏi “Chạy nền tiếp / Tạm dừng và thoát / Ở lại”",
                dialog_when_busy,
            ),
            ("app: không có việc gì thì đóng cửa sổ là thoát (không hỏi)", idle_close_allowed),
        ]:
            self.check(name, fn)
        self.finish_selftest()

    def finish_selftest(self) -> None:
        self.selftest_force_close = True
        self.quit(pause=False)

    def report_selftest(self) -> int:
        def server_stopped() -> None:
            assert self.server_thread is None or not self.server_thread.is_alive(), (
                "server còn chạy"
            )
            assert self.uv is not None and self.uv.should_exit

        self.check(
            "app: thoát chủ động — luồng server đã dừng (lifespan tắt hàng đợi)", server_stopped
        )
        ok = True
        for good, name, why in self.results:
            ok &= good
            print(
                ("PASS  " if good else "FAIL  ") + name + ("" if good else f" — {why}"), flush=True
            )
        return 0 if ok else 1


def marked_pids(mark: str) -> list[int]:
    """Tiến trình nào (còn sống) mang GV_SELFTEST_MARK=<mark> trong môi trường lúc khởi động: con cháu của lần selftest."""
    out = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit() and int(p.name) != os.getpid():
            try:
                if f"GV_SELFTEST_MARK={mark}".encode() in (p / "environ").read_bytes().split(b"\0"):
                    out.append(int(p.name))
            except OSError:
                continue
    return out


def comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return "?"


def selftest_supervisor() -> int:
    """`-m giongviet.desktop --selftest`: chạy phần kiểm tra thật trong một tiến trình con (có dữ liệu / cấu hình tạm, cửa sổ ẩn) rồi kiểm tra
    sau khi nó thoát: không còn tiến trình nào sót lại (WebKit* chỉ chết khi tiến trình giao diện thoát nên không kiểm trong chính nó)."""
    import subprocess

    if not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
        print("SKIP  app --selftest: không có màn hình đồ hoạ (DISPLAY / WAYLAND_DISPLAY)")
        return 0
    mark, tmp = uuid.uuid4().hex, Path(tempfile.mkdtemp(prefix="gv_selftest_"))
    env = {
        **os.environ,
        "GV_SELFTEST_MARK": mark,
        "TTS_DATA_DIR": str(tmp / "data"),
        "GV_RUNTIME_DIR": str(tmp / "run"),
        "XDG_CONFIG_HOME": str(tmp / "config"),
        "XDG_STATE_HOME": str(tmp / "state"),
        "XDG_DATA_HOME": str(tmp / "share"),
    }
    try:
        rc = 0
        for rnd in (
            "1",
            "2",
        ):  # vòng 2 mở lại app với cùng thư mục tạm để kiểm cổng nhớ lại + localStorage còn
            try:
                rc |= subprocess.run(
                    [sys.executable, "-m", "giongviet.desktop", "--selftest"],
                    env={**env, "GV_SELFTEST_ROUND": rnd},
                    timeout=300,
                ).returncode
            except subprocess.TimeoutExpired:
                print(f"FAIL  app: selftest vòng {rnd} quá 300 giây (treo)")
                rc = 1
            if rc:
                break
        t = time.time()
        left = marked_pids(mark)
        while left and time.time() - t < 10:
            time.sleep(0.3)
            left = marked_pids(mark)
        if left:
            print(
                f"FAIL  app: sau khi thoát vẫn còn tiến trình sót lại — {[(p, comm(p)) for p in left]}"
            )
            for p in left:
                try:
                    os.kill(p, 9)
                except OSError:
                    pass
            rc = 1
        else:
            print("PASS  app: thoát sạch — không còn tiến trình nào sót lại (server, WebKit, …)")
        return rc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="giong-viet", description=__doc__.split("\n")[0])
    ap.add_argument(
        "route", nargs="?", default="", help="mở thẳng tới màn này, vd. /doc, /sach/them, /giong"
    )
    ap.add_argument(
        "--selftest", action="store_true", help="khởi động server + cửa sổ ẩn, kiểm tra, đóng sạch"
    )
    ap.add_argument(
        "--no-tray",
        action="store_true",
        help="không dùng khay hệ thống (chạy nền = thu nhỏ cửa sổ)",
    )
    ap.add_argument("--debug", action="store_true", help="như GV_DEBUG=1")
    args = ap.parse_args(argv)
    global DEBUG
    if args.debug:
        DEBUG = True
        os.environ["GV_DEBUG"] = "1"
    if args.selftest and not os.getenv("GV_SELFTEST_MARK"):
        return selftest_supervisor()
    return App(args).run()


if __name__ == "__main__":
    sys.exit(main())
