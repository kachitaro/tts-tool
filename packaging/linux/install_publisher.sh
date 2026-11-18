#!/usr/bin/env bash
# Cài laptop đăng bài (giongviet.publisher) thành dịch vụ systemd của người dùng, chạy 24/24 (không cần root, trừ bước linger):
#   ~/.config/systemd/user/giong-viet-publisher.service
#   ~/.config/giong-viet-publisher/env          HOST, PORT, PUBLISHER_TOKEN (tự sinh lần đầu, chmod 600)
#   ~/.local/share/giong-viet-publisher/         posts.json, media/, secrets.json (token bot, webhook; bạn tự điền)
# Chạy lại để cập nhật đường dẫn; token và dữ liệu cũ được giữ. Gỡ: packaging/linux/uninstall_publisher.sh.
# Đổi địa chỉ nghe lần đầu:  HOST=100.x.y.z packaging/linux/install_publisher.sh   (mặc định 0.0.0.0, luôn kèm token)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$REPO/.venv/bin/python"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
ENV_DIR="$CONF/giong-viet-publisher"
UNIT_DIR="$CONF/systemd/user"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/giong-viet-publisher"

die() { echo "Lỗi: $*" >&2; exit 1; }

[ -x "$PY" ] || die "chưa có $PY. Tạo trước: cd '$REPO' && python3 -m venv .venv && .venv/bin/python -m pip install -e ."
"$PY" -c "import giongviet.publisher.app" 2>/dev/null || die "chưa cài được gói (thử: $PY -m pip install -e '$REPO')."
command -v systemctl >/dev/null || die "máy này không có systemd."

mkdir -p "$ENV_DIR" "$UNIT_DIR" "$DATA"
chmod 700 "$ENV_DIR" "$DATA"

if [ ! -f "$ENV_DIR/env" ]; then
  umask 077
  cat > "$ENV_DIR/env" <<ENV
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8800}
PUBLISHER_TOKEN=$("$PY" -c "import secrets; print(secrets.token_urlsafe(32))")
PUBLISHER_DATA=$DATA
ENV
  echo "• Đã tạo $ENV_DIR/env (token mới)."
fi
chmod 600 "$ENV_DIR/env"
[ -f "$DATA/secrets.json" ] || { (umask 077; echo '{}' > "$DATA/secrets.json"); echo "• Đã tạo $DATA/secrets.json rỗng: điền token bot / webhook vào đó (xem README)."; }

cat > "$UNIT_DIR/giong-viet-publisher.service" <<UNIT
[Unit]
Description=Giọng Việt — laptop đăng bài
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$REPO
EnvironmentFile=$ENV_DIR/env
ExecStart=$PY -m giongviet.publisher
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now giong-viet-publisher.service

echo "Đã chạy dịch vụ. Xem log: journalctl --user -u giong-viet-publisher -f"
echo "Token (dán vào Cài đặt chung → Laptop đăng bài trên máy tạo giọng):"
echo "  $(sed -n 's/^PUBLISHER_TOKEN=//p' "$ENV_DIR/env")"
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  echo "Lưu ý: để dịch vụ chạy khi chưa đăng nhập / sau khi khởi động lại, chạy một lần:  sudo loginctl enable-linger $USER"
fi
echo "Lưu ý: gập nắp laptop sẽ làm máy ngủ và lỡ giờ đăng; đặt HandleLidSwitch=ignore trong /etc/systemd/logind.conf (README, mục Đăng bài từ xa)."
