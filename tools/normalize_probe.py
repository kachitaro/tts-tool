"""Xem VieNeu (sea-g2p) tự chuẩn hoá được những gì, để chỉ viết quy tắc cho phần còn thiếu.

Chạy: .venv/bin/python tools/normalize_probe.py
Mỗi câu mẫu đi qua đúng đường chuẩn hoá mà VieNeu dùng khi đọc
(vieneu_utils.phonemize_text.normalize_to_chunks_v3_with_gaps) và in ra văn bản sau chuẩn hoá.
Dùng với `--rules` để chạy thêm text_normalize.py trước rồi so sánh.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = [
    # ngày giờ
    "Hôm nay là 12/3/2025.", "Họp lúc 10h30 sáng mai.", "Từ 8:00 đến 17:30 hằng ngày.", "Sinh ngày 05-11-1990.",
    "Năm 2024 là năm nhuận.", "Tháng 3/2025 có nhiều mưa.",
    # số, tiền, phần trăm, đơn vị
    "Tỷ lệ đạt 25% so với năm trước.", "Quãng đường dài 3,5 km.", "Giá là 1.000.000đ một tháng.",
    "Anh ấy nặng 72 kg và cao 1m75.", "Nhiệt độ 35°C ngoài trời.", "Tốc độ 120 km/h trên cao tốc.",
    "Máy tính có 16GB RAM.", "Dung lượng 512 MB còn trống.", "Số điện thoại 0912 345 678.", "Giá 100$ một chiếc.",
    "Chương 3 có 15 mục.", "Điểm trung bình là 8,75.",
    # viết tắt
    "Ông ấy sống ở TP.HCM.", "Rau, thịt, cá, v.v.", "Họp tại UBND tỉnh.", "Dịch COVID-19 bùng phát.",
    "Công ty TNHH Thiên Long.", "Ông Nguyễn Văn A là GS.TS.", "Xem thêm tại www.example.com.",
    # ca khó hơn: khoảng, phân số, ký hiệu, tiền viết tắt, đơn vị lạ
    "Có từ 10-15 người tham dự.", "Tăng 10-15% mỗi năm.", "Diện tích 50m2 và 2km².", "Giá chỉ 50k một cốc.",
    "Lương 15tr một tháng.", "Cần 1/2 cốc đường.", "Ngày 30/4 và 2/9 là ngày lễ.", "Thứ 2 đến thứ 6.",
    "Mạng 4G và 5G đã phủ sóng.", "Giá 1.5 triệu đồng.", "Số 1.234,56 là số thực.", "Họp lúc 9 giờ 15 phút.",
    "Phòng 301 tầng 3 toà A1.", "Nhiệt độ từ -5 đến 10 độ C.", "Anh ấy là CEO của công ty ABC.",
    "GDP tăng 6,5% trong quý 1/2025.", "Mua 2 tặng 1, giảm giá 30%!", "Đường Nguyễn Huệ, Q.1, TP. Hồ Chí Minh.",
    "Ngày 1/1/2025 - 31/12/2025.", "Phiên bản v2.0.1 vừa ra mắt.", "Gọi 113 hoặc 114 khi khẩn cấp.",
    "Chuyển 100 USD sang VND.", "Giá $100 một chiếc.", "Giá 50€ một vé.", "Vay 2,5 tỷ VNĐ.", "Đạt 3 x 4 bằng 12.",
    "Nhóm A & B cùng tham gia.", "Theo dõi #hashtag mới.", "Gọi +84 912 345 678.", "Hạng 1/3 toàn quốc.",
    "Cân nặng 2,5kg và 500g.", "Đường dài 100m, rộng 5 m.", "Giá 2.500.000 VND.",
    "Liên hệ qua email abc@gmail.com nhé.", "Tổng cộng 5 người (xem hình 2).", "Trụ sở ở Q.1, P.Bến Nghé.",
    "NASA phóng tên lửa ra vũ trụ.", "Học AI và IT ở trường ĐH Bách Khoa.",
]


def main() -> None:
    from vieneu_utils.phonemize_text import normalize_to_chunks_v3_with_gaps

    use_rules = "--rules" in sys.argv
    if use_rules:
        from giongviet.speech import text_normalize
    for s in SAMPLES:
        src = text_normalize.normalize(s) if use_rules else s
        chunks, _ = normalize_to_chunks_v3_with_gaps(src)
        print(f"{s}\n   → {' | '.join(chunks)}\n")


if __name__ == "__main__":
    main()
