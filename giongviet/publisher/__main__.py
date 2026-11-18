"""Chạy trên laptop:  PUBLISHER_TOKEN=... HOST=0.0.0.0 python -m giongviet.publisher"""

import os
import sys

import uvicorn

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    if host not in LOOPBACK and not os.getenv("PUBLISHER_TOKEN"):
        sys.exit("Từ chối khởi động: HOST ngoài loopback thì bắt buộc đặt PUBLISHER_TOKEN.")
    from giongviet.publisher.app import (
        app,  # import sau kiểm tra: app tạo thư mục dữ liệu khi import
    )

    uvicorn.run(app, host=host, port=int(os.getenv("PORT", "8800")))


if __name__ == "__main__":
    main()
