#!/usr/bin/env bash
# Gỡ những gì scripts/install_desktop.sh đã cài. Không đụng tới thư mục tool và thư mục dữ liệu data/ (truyện, giọng, lịch sử).
#   --purge   xoá luôn trạng thái của app: cỡ / vị trí cửa sổ (~/.config/giong-viet), nhật ký (~/.local/state/giong-viet),
#             bộ nhớ riêng của cửa sổ app gồm localStorage (~/.local/share/giong-viet)
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
files=("$HOME/.local/bin/giong-viet" "$DATA_HOME/applications/giong-viet.desktop" "$DATA_HOME/icons/hicolor/scalable/apps/giong-viet.svg")
for f in "${files[@]}"; do
  if [ -e "$f" ]; then rm -f "$f" && echo "Đã xoá $f"; else echo "Không có $f (bỏ qua)"; fi
done
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true

if [ "${1:-}" = "--purge" ]; then
  for d in "${XDG_CONFIG_HOME:-$HOME/.config}/giong-viet" "${XDG_STATE_HOME:-$HOME/.local/state}/giong-viet" "$DATA_HOME/giong-viet"; do
    if [ -d "$d" ]; then rm -rf "$d" && echo "Đã xoá $d"; fi
  done
fi
echo "Xong. Dữ liệu của bạn (data/) vẫn còn nguyên."
