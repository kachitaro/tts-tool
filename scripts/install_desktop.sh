#!/usr/bin/env bash
# Cài "Giọng Việt" vào máy cho người dùng hiện tại (không cần root):
#   ~/.local/bin/giong-viet                                 lệnh chạy app (trỏ vào .venv của thư mục này)
#   ~/.local/share/applications/giong-viet.desktop          mục trong menu ứng dụng
#   ~/.local/share/icons/hicolor/scalable/apps/giong-viet.svg   biểu tượng
# Gỡ: scripts/uninstall_desktop.sh. Chạy lại để cập nhật (ví dụ sau khi chuyển thư mục tool).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
BIN_DIR="${HOME}/.local/bin"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"

die() { echo "Lỗi: $*" >&2; exit 1; }

[ -x "$PY" ] || die "chưa có $PY. Tạo trước: cd '$REPO' && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"

if ! "$PY" -c "import webview" 2>/dev/null; then
  echo "• Cài pywebview vào .venv (pip, không cần root)…"
  "$PY" -m pip install -q -r "$REPO/requirements-app.txt"
fi

# GTK / WebKitGTK là gói của hệ thống (pip không cài được PyGObject): app_gtk.py báo cách cài nếu thiếu
if ! out="$(cd "$REPO" && "$PY" -c "import app_gtk" 2>&1)"; then
  echo "$out" | sed -n '/^Thiếu thư viện/,$p' >&2
  die "thiếu gói hệ thống cho cửa sổ app (xem lệnh ở trên), rồi chạy lại script này."
fi

mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"

cat > "$BIN_DIR/giong-viet" <<LAUNCHER
#!/bin/sh
# Giọng Việt — tạo bởi scripts/install_desktop.sh (gỡ: scripts/uninstall_desktop.sh)
exec "$PY" "$REPO/app.py" "\$@"
LAUNCHER
chmod +x "$BIN_DIR/giong-viet"

cp "$REPO/desktop/giong-viet.svg" "$ICON_DIR/giong-viet.svg"

cat > "$APPS_DIR/giong-viet.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=Giọng Việt
GenericName=Chuyển văn bản thành giọng nói
Comment=Đọc văn bản và làm sách nói bằng giọng tiếng Việt, chạy ngay trên máy bạn
Exec=$BIN_DIR/giong-viet
Icon=giong-viet
Terminal=false
Categories=AudioVideo;Audio;
Keywords=giọng nói;tiếng Việt;sách nói;đọc;tts;audiobook;
StartupNotify=true
StartupWMClass=giong-viet
Actions=read;books;voices;

[Desktop Action read]
Name=Đọc văn bản
Exec=$BIN_DIR/giong-viet /doc

[Desktop Action books]
Name=Làm sách nói
Exec=$BIN_DIR/giong-viet /sach

[Desktop Action voices]
Name=Giọng đọc
Exec=$BIN_DIR/giong-viet /giong
DESKTOP

command -v desktop-file-validate >/dev/null && desktop-file-validate "$APPS_DIR/giong-viet.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true

echo "Đã cài:"
echo "  $BIN_DIR/giong-viet"
echo "  $APPS_DIR/giong-viet.desktop"
echo "  $ICON_DIR/giong-viet.svg"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Lưu ý: $BIN_DIR chưa nằm trong PATH nên gõ 'giong-viet' ở terminal chưa chạy được (mở từ menu ứng dụng thì vẫn được).";; esac
echo "Mở: tìm \"Giọng Việt\" trong menu ứng dụng, hoặc gõ: giong-viet"
