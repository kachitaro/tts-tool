"""Mọi đường dẫn cố định của dự án ở một chỗ."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # gốc repo
WEB = ROOT / "web"                               # giao diện (HTML/CSS/JS, không build)
CONFIG = ROOT / "config"                         # file người dùng sửa được
