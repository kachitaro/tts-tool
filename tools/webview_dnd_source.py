"""Cửa sổ GTK đóng vai "file manager" cho tools/webview_probe.py: bấm giữ rồi kéo ra ngoài sẽ mang theo một file (text/uri-list).
Nhận một hay nhiều đường dẫn file. Chạy bằng /usr/bin/python3 (cần python3-gi). In "ready" khi cửa sổ đã hiện ở (50,30) cỡ 120×60."""

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

paths = [Path(a).resolve() for a in sys.argv[1:]]
win = Gtk.Window(title="file manager giả")
win.set_default_size(120, 60)
win.move(50, 30)
box = Gtk.EventBox()
box.add(Gtk.Label(label=", ".join(p.name for p in paths)))
win.add(box)
box.drag_source_set(
    Gdk.ModifierType.BUTTON1_MASK, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY
)
box.connect(
    "drag-data-get", lambda w, ctx, data, info, t: data.set_uris([p.as_uri() for p in paths])
)
box.connect("drag-begin", lambda *a: print("drag-begin", file=sys.stderr, flush=True))
box.connect("drag-end", lambda *a: print("drag-end", file=sys.stderr, flush=True))
win.connect("destroy", Gtk.main_quit)
win.show_all()
from gi.repository import GLib  # noqa: E402

GLib.timeout_add(600, lambda: (print("ready", flush=True), False)[1])
Gtk.main()
