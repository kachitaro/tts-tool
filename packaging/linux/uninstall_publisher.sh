#!/usr/bin/env bash
# Gỡ dịch vụ laptop đăng bài. Mặc định giữ token và dữ liệu; thêm --purge để xoá luôn (lịch, file đang chờ, secrets.json).
set -euo pipefail

CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/giong-viet-publisher"

systemctl --user disable --now giong-viet-publisher.service 2>/dev/null || true
rm -f "$CONF/systemd/user/giong-viet-publisher.service"
systemctl --user daemon-reload

if [ "${1:-}" = "--purge" ]; then
  rm -rf "$CONF/giong-viet-publisher" "$DATA"
  echo "Đã gỡ dịch vụ và xoá token, dữ liệu."
else
  echo "Đã gỡ dịch vụ. Token ($CONF/giong-viet-publisher) và dữ liệu ($DATA) được giữ; thêm --purge để xoá."
fi
