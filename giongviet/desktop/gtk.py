"""Phần riêng của backend GTK (WebKitGTK) cho desktop/app.py: tìm PyGObject của hệ thống, cho phép micro, nhận đường dẫn file kéo thả,
menu chuột phải, phóng to / thu nhỏ, đưa cửa sổ lên trước, biểu tượng khay (AppIndicator), tín hiệu SIGINT / SIGTERM.

Mọi lời gọi GTK phải chạy ở luồng giao diện: dùng on_main() / call_main() khi gọi từ luồng khác.
Vì sao GTK mà không phải Qt: xem mục "App cửa sổ riêng" trong README (đo thật: RAM, kéo thả, micro, cài đặt).
"""

from __future__ import annotations

import importlib
import os
import re
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

INSTALL_HINT = (
    "Thiếu thư viện giao diện GTK / WebKitGTK cho app cửa sổ riêng.\n"
    "  Ubuntu / Debian : sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1\n"
    "  Fedora          : sudo dnf install python3-gobject gtk3 webkit2gtk4.1\n"
    "  Arch            : sudo pacman -S python-gobject gtk3 webkit2gtk-4.1\n"
    "Muốn chạy bằng trình duyệt thay vì cửa sổ riêng: python -m giongviet"
)


def ensure_gi() -> None:
    """PyGObject không cài được bằng pip trong .venv (cần bản dev của girepository) nên dùng bản của hệ thống: nếu .venv không
    có `gi`, thêm thư mục chứa nó ở CUỐI sys.path (gói của .venv luôn được ưu tiên). Chỉ dùng được khi cùng phiên bản Python."""
    try:
        import gi  # noqa: F401

        return
    except ImportError:
        pass
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    cands = [
        "/usr/lib/python3/dist-packages",
        f"/usr/lib/python{v}/site-packages",
        f"/usr/lib64/python{v}/site-packages",
        f"/usr/lib/python{v}/dist-packages",
    ]
    try:  # hỏi python hệ thống nó cài gi ở đâu (mọi bản phân phối)
        out = subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                "import gi,os;print(os.path.dirname(os.path.dirname(gi.__file__)))",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
        if out:
            cands.append(out)
    except OSError, subprocess.SubprocessError:
        pass
    for d in dict.fromkeys(cands):
        if os.path.isdir(os.path.join(d, "gi")):
            sys.path.append(d)
            importlib.invalidate_caches()
            try:
                import gi  # noqa: F401

                return
            except ImportError:
                sys.path.remove(d)
                sys.modules.pop("gi", None)
    raise RuntimeError(INSTALL_HINT)


ensure_gi()
import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, WebKit2  # noqa: E402

APPINDICATOR = None
for _ns in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(_ns, "0.1")
        APPINDICATOR = importlib.import_module("gi.repository." + _ns)
        break
    except ValueError, ImportError:
        continue


# ───────────── luồng giao diện ─────────────
def on_main(fn, *args) -> None:
    GLib.idle_add(lambda: (fn(*args), False)[1])


def call_main(fn: Callable[[], Any], timeout: float = 10) -> Any:
    """Chạy fn ở luồng giao diện và chờ kết quả (gọi từ luồng khác; ở chính luồng giao diện thì gọi thẳng, tránh tự chờ mình)."""
    if threading.current_thread() is threading.main_thread():
        return fn()
    done, box = threading.Event(), {}

    def run() -> bool:
        try:
            box["v"] = fn()
        except BaseException as ex:  # noqa: BLE001
            box["e"] = ex
        done.set()
        return False

    GLib.idle_add(run)
    if not done.wait(timeout):
        raise TimeoutError("luồng giao diện không trả lời")
    if "e" in box:
        raise box["e"]
    return box.get("v")


def set_app_identity(prgname: str, name: str) -> None:
    """Tên chương trình = app_id trên Wayland / WM_CLASS trên X11: khớp giao diện với giong-viet.desktop để có đúng biểu tượng."""
    GLib.set_prgname(prgname)
    GLib.set_application_name(name)
    Gdk.set_program_class(prgname)  # WM_CLASS của X11 = tên này, khớp StartupWMClass trong .desktop


def is_wayland() -> bool:
    d = Gdk.Display.get_default()
    return d is not None and "Wayland" in type(d).__name__


def downloads_dir() -> str:
    return GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or str(Path.home())


def point_visible(x: int, y: int) -> bool:
    """Điểm (x, y) có nằm trong một màn hình đang cắm không? (tránh mở cửa sổ ra ngoài vùng nhìn thấy sau khi rút màn hình)."""
    d = Gdk.Display.get_default()
    if d is None:
        return True
    for i in range(d.get_n_monitors()):
        g = d.get_monitor(i).get_geometry()
        if g.x <= x < g.x + g.width and g.y <= y < g.y + g.height:
            return True
    return False


def svg_ok(path: str) -> bool:
    """GdkPixbuf đọc được SVG không (cần librsvg)? pywebview gọi set_icon_from_file không bắt lỗi nên phải thử trước."""
    try:
        GdkPixbuf.Pixbuf.new_from_file_at_size(path, 64, 64)
        return True
    except GLib.Error:
        return False


# ───────────── cửa sổ ─────────────
def view(win: Any) -> Any:
    from webview.platforms.gtk import BrowserView

    return BrowserView.instances[win.uid]


def wait_view(win: Any, timeout: float = 30) -> Any:
    import time

    t = time.time()
    while time.time() - t < timeout:
        try:
            bv = view(win)
            if (
                getattr(bv, "webview", None) is not None
            ):  # BrowserView vào danh sách sớm, webview được gán sau
                return bv
        except KeyError:
            pass
        time.sleep(0.05)
    raise TimeoutError("không tạo được cửa sổ")


_MENU_KEEP = {
    getattr(WebKit2.ContextMenuAction, n)
    for n in ("CUT", "COPY", "PASTE", "DELETE", "SELECT_ALL")
    if hasattr(WebKit2.ContextMenuAction, n)
}


def attach(win, *, debug: bool, on_uris) -> None:
    """Gắn các xử lý mà pywebview/GTK không tự làm:
    - micro: WebKitGTK từ chối getUserMedia nếu không ai trả lời permission-request → cho phép (chỉ âm thanh; trang duy nhất là
      127.0.0.1 của tool, liên kết ngoài pywebview đã mở bằng trình duyệt); mọi quyền khác từ chối;
    - kéo thả: WebKitGTK không đưa File vào DOM khi kéo từ ngoài vào, chỉ có URI → chuyển cho desktop/app.py;
    - menu chuột phải: chỉ còn Cắt / Chép / Dán khi bấm vào ô nhập hoặc chữ đang chọn, trừ khi debug thì giữ nguyên (có Inspect)."""
    bv = wait_view(win)
    wv = bv.webview

    def on_permission(_wv: Any, req: Any) -> bool:
        if isinstance(req, WebKit2.UserMediaPermissionRequest):
            if req.get_property("is-for-video-device"):
                req.deny()
            else:
                req.allow()
            return True
        req.deny()
        return True

    def on_context_menu(_wv: Any, menu: Any, _event: Any, hit: Any) -> bool:
        if debug:
            return False
        if not (hit.context_is_editable() or hit.context_is_selection()):
            return True
        for item in list(menu.get_items()):
            if not item.is_separator() and item.get_stock_action() not in _MENU_KEEP:
                menu.remove(item)
        return False

    def on_drag(_w: Any, _ctx: Any, _x: int, _y: int, data: Any, _info: int, _time: int) -> None:
        uris = data.get_uris() or [
            ln.strip()
            for ln in (data.get_text() or "").splitlines()
            if ln.strip().startswith("file://")
        ]
        if uris:
            on_uris(uris)

    def setup() -> None:
        wv.connect("permission-request", on_permission)
        wv.connect("context-menu", on_context_menu)
        wv.connect("drag-data-received", on_drag)
        if not debug:
            wv.get_settings().set_enable_developer_extras(False)

    call_main(setup)


# ───────────── bo góc cửa sổ ─────────────
_SQUARE_STATES = (
    Gdk.WindowState.MAXIMIZED
    | Gdk.WindowState.FULLSCREEN
    | Gdk.WindowState.TILED
    | Gdk.WindowState.TOP_TILED
    | Gdk.WindowState.RIGHT_TILED
    | Gdk.WindowState.BOTTOM_TILED
    | Gdk.WindowState.LEFT_TILED
)
_THEME_DIRS = ("~/.themes", "~/.local/share/themes", "/usr/share/themes")


def theme_radius(default: int = 15) -> int:
    """Bán kính góc `decoration` của GTK theme đang dùng. GTK3 không có API đọc border-radius, nên đọc thẳng CSS của theme
    (theme Yaru nén CSS trong gtk.gresource): lấy giá trị đầu của `decoration { border-radius: A B C D }` (= góc trên trái).
    Không đọc được thì dùng `default` = 15, số đo trên Yaru (CSS của theme ghi 15px; đo trên ảnh chụp góc trên trái cửa sổ ra 15–17)."""
    try:
        env = os.getenv("GV_CORNER_RADIUS")
        if env:
            return max(0, min(40, int(env)))
        name = Gtk.Settings.get_default().props.gtk_theme_name
        for d in _THEME_DIRS:
            f = Path(d).expanduser() / name / "gtk-3.0" / "gtk.css"
            if not f.is_file():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            imp = re.match(r'\s*@import url\("resource://(/[^"]+)"\)', text)
            if imp and (f.parent / "gtk.gresource").is_file():
                res = Gio.Resource.load(str(f.parent / "gtk.gresource"))
                text = bytes(
                    res.lookup_data(imp.group(1), Gio.ResourceLookupFlags.NONE).get_data()
                ).decode()
            m = re.search(r"(?m)^decoration\s*\{[^}]*?border-radius:\s*([\d.]+)px", text)
            if m:
                return round(float(m.group(1)))
    except Exception:  # noqa: BLE001
        pass
    return default


def is_square(state: Any) -> bool:
    """Trạng thái cửa sổ không bo góc: phóng to, toàn màn hình, ghép nửa màn hình / ghép cạnh."""
    return bool(state & _SQUARE_STATES)


def corners_script(radius: int, square: bool, debug: bool) -> str:
    return (
        "(()=>{const r=document.documentElement;r.classList.add('app-window');"
        f"r.classList.toggle('app-square',{str(square).lower()});r.classList.toggle('app-debug',{str(debug).lower()});"
        f"r.style.setProperty('--app-radius','{radius}px');}})()"
    )


def install_corners(win: Any, *, debug: bool) -> None:
    """Bo 2 góc dưới cho khớp 2 góc trên (xem web/css/app-window.css). Phần GTK ở đây:
    - decoration bo cả 4 góc (bóng đổ và viền theo đúng hình), về 0 khi phóng to / ghép màn hình (GTK tự thêm class .maximized, .tiled…);
    - nền cửa sổ, ScrolledWindow và WebKitWebView trong suốt để vùng trang cắt đi lộ ra đúng hình bo;
    - mỗi lần trạng thái cửa sổ đổi: bật / tắt class app-square trên trang hiện tại và trên các trang nạp sau (UserScript)."""
    bv = wait_view(win)
    wv, w = bv.webview, win.native
    radius = theme_radius()

    def setup() -> None:
        w.get_style_context().add_class(
            "gv-main"
        )  # chỉ cửa sổ chính; hộp "Lưu thành…" (cửa sổ khác) giữ nguyên giao diện
        sq = ".maximized, .fullscreen, .tiled, .tiled-top, .tiled-right, .tiled-bottom, .tiled-left"
        css = (
            f"window.gv-main decoration {{ border-radius: {radius}px; }}\n"
            + ",".join(f"window.gv-main{c} decoration" for c in sq.replace(" ", "").split(","))
            + " { border-radius: 0; }\n"
            "window.gv-main, window.gv-main scrolledwindow, window.gv-main scrolledwindow * "
            "{ background-color: transparent; background-image: none; }\n"
        )
        if debug:
            css += "window.gv-main decoration { box-shadow: 0 0 0 2px #f00; }\n"
        p = Gtk.CssProvider()
        p.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), p, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        wv.set_background_color(Gdk.RGBA(0, 0, 0, 0))

        def push(state: Any) -> None:
            script = corners_script(radius, is_square(state), debug)
            bv.manager.remove_all_scripts()
            bv.manager.add_script(
                WebKit2.UserScript.new(
                    script,
                    WebKit2.UserContentInjectedFrames.TOP_FRAME,
                    WebKit2.UserScriptInjectionTime.START,
                    None,
                    None,
                )
            )
            wv.run_javascript(script, None, None, None)

        w.connect("window-state-event", lambda _w, ev: push(ev.new_window_state))
        wv.connect(
            "load-changed",
            lambda _wv, ev: (
                ev == WebKit2.LoadEvent.COMMITTED
                and push(w.get_window().get_state() if w.get_window() else 0)
            ),
        )
        push(w.get_window().get_state() if w.get_window() else 0)

    call_main(setup)


def uris_to_paths(uris) -> list[Path]:
    out = []
    for u in uris:
        p = urlparse(u)
        if p.scheme == "file":
            out.append(Path(unquote(p.path)))
    return out


def set_zoom(win, z: float) -> None:
    on_main(lambda: view(win).webview.set_zoom_level(z))


def geometry(win) -> dict:
    def get() -> Any:
        w = win.native
        x, y = w.get_position()
        width, height = w.get_size()
        return {"x": x, "y": y, "width": width, "height": height, "maximized": w.is_maximized()}

    return call_main(get)


def is_shown(win) -> bool:
    """Cửa sổ đang hiện trên màn hình (không ẩn, không thu nhỏ)?"""

    def get() -> Any:
        w = win.native
        gw = w.get_window()
        return bool(
            w.get_visible() and gw is not None and not (gw.get_state() & Gdk.WindowState.ICONIFIED)
        )

    try:
        return call_main(get)
    except Exception:  # noqa: BLE001
        return False


def present(win, startup_id: str | None = None) -> None:
    def go() -> None:
        w = win.native
        if startup_id:
            try:
                w.set_startup_id(startup_id)
            except Exception:  # noqa: BLE001
                pass
        w.show()
        w.deiconify()
        w.present()

    on_main(go)


def handle_signals(callback) -> None:
    for s in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(
            GLib.PRIORITY_DEFAULT, s, lambda sig=s: (callback(signal.Signals(sig).name), True)[1]
        )


# ───────────── khay hệ thống ─────────────
def tray_available() -> bool:
    """Có AppIndicator và có chương trình hiển thị khay (StatusNotifierWatcher) trên D-Bus không?
    GNOME mặc định không có khay trừ khi bật tiện ích AppIndicator (Ubuntu bật sẵn)."""
    if APPINDICATOR is None:
        return False
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        r = conn.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        return bool(r.unpack()[0])
    except GLib.Error:
        return False


class Tray:
    """Biểu tượng khay: [trạng thái] · Mở · Tạm dừng / Tiếp tục · Thoát. Gọi mọi hàm từ luồng bất kỳ."""

    def __init__(
        self,
        icon_dir: str,
        icon_name: str,
        on_open: Callable[[], Any],
        on_toggle: Callable[[], Any],
        on_quit: Callable[[], Any],
    ) -> None:
        self._cb = (on_open, on_toggle, on_quit)
        self._icon = (icon_dir, icon_name)
        self._ind = None
        self._items: dict = {}

    def _build(self) -> None:
        ind = APPINDICATOR.Indicator.new_with_path(
            "giong-viet",
            self._icon[1],
            APPINDICATOR.IndicatorCategory.APPLICATION_STATUS,
            self._icon[0],
        )
        ind.set_title("Giọng Việt")
        menu = Gtk.Menu()

        def item(label: str, cb: Callable[[], Any] | None = None, sensitive: bool = True) -> Any:
            it = Gtk.MenuItem(label=label)
            it.set_sensitive(sensitive)
            if cb:
                it.connect("activate", lambda _w: threading.Thread(target=cb, daemon=True).start())
            menu.append(it)
            return it

        self._items["status"] = item("Giọng Việt", sensitive=False)
        menu.append(Gtk.SeparatorMenuItem())
        self._items["open"] = item("Mở Giọng Việt", self._cb[0])
        self._items["toggle"] = item("Tạm dừng", self._cb[1], sensitive=False)
        menu.append(Gtk.SeparatorMenuItem())
        self._items["quit"] = item("Thoát", self._cb[2])
        menu.show_all()
        ind.set_menu(menu)
        ind.set_secondary_activate_target(self._items["open"])
        self._ind = ind

    def show(self) -> None:
        def go() -> None:
            if self._ind is None:
                self._build()
            self._ind.set_status(APPINDICATOR.IndicatorStatus.ACTIVE)

        on_main(go)

    def hide(self) -> None:
        on_main(lambda: self._ind and self._ind.set_status(APPINDICATOR.IndicatorStatus.PASSIVE))

    def update(self, status: str, toggle_label: str | None) -> None:
        def go() -> None:
            if self._ind is None:
                return
            self._items["status"].set_label(status)
            self._items["toggle"].set_sensitive(toggle_label is not None)
            if toggle_label:
                self._items["toggle"].set_label(toggle_label)

        on_main(go)
