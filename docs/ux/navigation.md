# UX-0 — Kiến trúc thông tin

## 1. Sơ đồ điều hướng

```
Thanh trên cùng (luôn hiện)
├─ "Giọng Việt" (logo)            → Màn chính
├─ [● Đang tạo: Truyện X, chương 12/171, còn ~9 giờ]   (chỉ hiện khi đang tạo; bấm → Trang truyện)
├─ 🕘 Lịch sử                     → ngăn kéo bên phải (không rời trang)
└─ ⚙ Cài đặt                      → hộp thoại "Cài đặt chung" (+ khối Nâng cao)

Trình phát dính đáy (luôn hiện; phát mọi thứ: nghe thử, lịch sử, chương, giọng)

Màn chính  (/)
├─ 📚 Làm sách nói   (thẻ nhấn mạnh)  → /sach
├─ 🗣️ Đọc văn bản                     → /doc
├─ 🎙️ Giọng của tôi                   → /giong
└─ "Đang làm dở": truyện đang tạo (bấm → trang truyện)

/sach  Sách nói của bạn
├─ [＋ Thêm truyện]  → /sach/them  (trình hướng dẫn)
│     Bước 1 Chọn file → Bước 2 Kiểm tra → Bước 3 Chọn giọng và nghe thử → [Bắt đầu tạo sách nói] → trang truyện
│        Bước 2: [Đúng rồi, tiếp tục] / [Có chỗ sai] → mở 3 công cụ sửa:
│            • Chia chương chưa đúng chỗ (chọn mẫu bằng ví dụ)   • Gộp / tách chương   • Dọn văn bản
│            • (Nâng cao) mẫu tiêu đề dạng mã, khung chương HTML
└─ thẻ truyện → /sach/truyen/<id>

/sach/truyen/<id>  Trang truyện = bảng điều khiển
├─ Đầu trang: tiến độ lớn · thời gian còn lại · [Tạm dừng/Tiếp tục] · [Tải về ▾] · [Dừng hẳn]
│            (+ banner vàng "Cần tạo lại N chương" khi đã đổi cài đặt)
├─ Thẻ phụ "Các chương": lọc (Tất cả / Đã xong / Đang chờ / Cần tạo lại), mỗi chương ▶ + ⋯ (Tạo lại, Xem chữ, Tải chương)
├─ Thẻ phụ "Cách đọc tên riêng": danh sách tên + "Tìm tên riêng trong truyện" (nghe thử, thêm nhanh)
└─ Thẻ phụ "Cài đặt": tên, tác giả, giọng kể, giọng cho lời thoại, đọc tên chương
      └─ Nâng cao: khoảng nghỉ, mở lại trình kiểm tra (chia chương / dọn văn bản), dung lượng + giải phóng chỗ,
                   quy tắc dọn riêng, cách đọc tên riêng dùng chung

/doc  Đọc văn bản
├─ Công tắc "Nhiều người đọc": tắt = ô văn bản + giọng + tốc độ; bật = ô kịch bản [Tên]: lời + bảng "Ai đọc giọng nào?"
├─ [Đọc] / [Tạo audio] → kết quả (▶, Tải về, từng dòng ▶ + Đọc lại dòng này)
└─ Nâng cao: cao độ, giọng từ file ghi âm tạm, chuẩn hoá, nghỉ (ms), dự án (mở/lưu)

/giong  Giọng của tôi
├─ [🎙️ Thêm giọng từ file ghi âm]  → hộp thoại (kéo file / ghi âm / đồng ý chủ giọng; giới tính-vùng trong "Thêm thông tin")
├─ [🎚️ Pha giọng mới]             → trang /giong/pha (2 thẻ giọng + thanh pha + tự nghe khi thả tay + [Lưu giọng này]; làm trang chứ không phải hộp thoại vì cần chọn giọng bằng hộp thoại con)
└─ lọc (tìm, Tất cả / Yêu thích / Của tôi / Nam / Nữ) + thẻ giọng: ▶ · ♥ · [Dùng để đọc] · ⋯ (Sửa, Xoá)
```

Quy tắc điều hướng: tối đa **2 cấp** (Màn chính → một mục → trang con); luôn có dấu vết "Trang chính › … ›"; nút Quay lại luôn ở cùng chỗ; việc nền không bao giờ bị che khi đổi trang (chỉ báo trên cùng + trình phát đáy).

## 2. Mỗi màn hình trả lời 3 câu

| Màn | Tôi đang ở đâu | Việc chính (1 nút nổi) | Bước tiếp theo |
|---|---|---|---|
| Màn chính | "Chào bạn, hôm nay muốn làm gì?" | thẻ **Làm sách nói** (viền nhấn) | bấm một thẻ |
| Sách nói của bạn | breadcrumb | **＋ Thêm truyện** | mở một truyện |
| Bước 1 | "Bước 1 — chọn file" + thanh bước | **Tiếp tục →** (hiện sau khi có file) | Bước 2 |
| Bước 2 | "Tìm thấy 171 chương" | **Đúng rồi, tiếp tục** | Bước 3 (hoặc "Có chỗ sai" → sửa → quay lại nút chính) |
| Bước 3 | "Chọn giọng và nghe thử" | **Bắt đầu tạo sách nói** (dính đáy) | trang truyện |
| Trang truyện (đang tạo) | tên truyện + tiến độ lớn | **Tạm dừng** | nghe chương đã xong / Tải về |
| Trang truyện (xong) | "Đã xong N chương" | **Tải về** | — |
| Đọc văn bản | "Đọc văn bản" | **Đọc** / **Tạo audio** | nghe, tải về |
| Giọng của tôi | "Giọng của tôi" | **Thêm giọng từ file ghi âm** | ▶ nghe, "Dùng để đọc" |

## 3. Bảng "chỗ cũ → chỗ mới" (không mất tính năng nào)

### Đọc văn bản (tab cũ 1)

| Tính năng cũ | Chỗ mới | Ghi chú |
|---|---|---|
| Ô văn bản + đếm ký tự | `/doc` ô chính | Bộ đếm giữ ở dòng chú thích |
| Ctrl+Enter để đọc | `/doc` dòng chú thích | giữ |
| Thẻ cảm xúc, Ngắt nhẹ, Xuống đoạn, Nghỉ… | `/doc` "Thêm cảm xúc, chỗ nghỉ" (gấp lại) | chỉ hiện thẻ giọng hỗ trợ (như cũ) |
| Engine (Nhanh / Chất lượng cao) | Nút đôi "Giọng online / Giọng trên máy" | |
| Giọng đọc (danh sách) | Danh sách giọng + ▶ nghe thử tại chỗ | thêm nghe thử |
| Gợi ý "tải model lần đầu" | Dòng gợi ý dưới danh sách giọng | |
| Tốc độ 1x/2x/3x | Chậm / Vừa / Nhanh (ánh xạ 0.8×–1.3× → API giữ `speed` %) | cần xác nhận mức (xem mục 4) |
| Cao độ | `/doc` → Nâng cao | |
| Chuẩn hoá văn bản | `/doc` → Nâng cao "Tự đọc số, ngày tháng…" | |
| Nhân bản giọng từ file mẫu (tạm) | `/doc` → Nâng cao "Dùng giọng từ file ghi âm (chỉ lần này)" | lưu lâu dài → Giọng của tôi |
| Nút "Đọc văn bản" + lỗi | nút **Đọc** + lỗi lời thường (toast, "Xem chi tiết") | |
| Lịch sử (phát, Tải WAV/MP3, Dùng lại, Xoá, Xoá tất cả) | Ngăn kéo 🕘 Lịch sử (gộp cả hội thoại) | một danh sách thay vì hai |

### Hội thoại (tab cũ 4) → "Nhiều người đọc"

| Tính năng cũ | Chỗ mới |
|---|---|
| Ô kịch bản `[Tên]: lời` | `/doc` khi bật "Nhiều người đọc" |
| Diễn viên (chọn giọng từng tên) | "Ai đọc giọng nào?" (▶ nghe thử mỗi người) |
| Tốc độ | dùng chung điều khiển tốc độ của `/doc` |
| Nghỉ giữa dòng / giữa đoạn (ms) | `/doc` → Nâng cao |
| Chuẩn hoá | `/doc` → Nâng cao |
| Tạo audio + tiến độ + kết quả (Tải WAV/MP3) | nút **Tạo audio** + kết quả |
| ▶ nghe dòng, 🔄 sinh lại dòng | ▶ + "Đọc lại dòng này" |
| Dự án (lưu / mở / xoá) | `/doc` → Nâng cao "Dự án" |
| Lịch sử hội thoại | Ngăn kéo Lịch sử (chung) |
| Cảnh báo giọng không hỗ trợ thẻ cảm xúc | dòng cảnh báo vàng dưới ô kịch bản |

### Thư viện giọng (tab cũ 2) + Tạo giọng mới (tab cũ 3) → "Giọng của tôi"

| Tính năng cũ | Chỗ mới |
|---|---|
| Tìm, lọc giới tính / vùng / phạm vi | Ô tìm + chip: Tất cả / Yêu thích / Của tôi / Nam / Nữ (vùng miền: chip thứ hai "Giọng Bắc/Trung/Nam" ở UX-1) |
| Thẻ giọng (♥, ▶, thẻ, mô tả, cảnh báo không dùng được) | giữ, rút gọn dòng thông tin |
| "Dùng giọng này" | "Dùng để đọc" (chuyển sang `/doc` kèm giọng đã chọn) |
| ✎ Sửa, 🗑 Xoá | menu ⋯ trên giọng của tôi |
| + Thêm giọng (file / kéo thả / ghi âm / đồng ý chủ giọng / giới tính / vùng / thẻ / mô tả) | Nút "Thêm giọng từ file ghi âm" → hộp thoại 3 trường chính; giới tính, vùng, thẻ, mô tả trong "Thêm thông tin" |
| Chọn Engine khi thêm giọng | tự chọn theo giọng trên máy (chỉ giọng trên máy hỗ trợ nhân bản); hiện trong "Thêm thông tin" nếu sau này có nhiều hơn một |
| Pha giọng: A, B, tìm, ▶, thanh pha, câu thử, tự nghe, Lưu | Nút "Pha giọng mới" → trang `/giong/pha` (2 thẻ giọng, mỗi thẻ "Đổi giọng" mở bộ chọn, thanh "Giống A … Giống B", nghe thử, tự nghe khi thả, đặt tên) |
| Lưu giọng pha: tên, giới tính, vùng, thẻ, mô tả | ô tên + "Thêm thông tin" |

### Sách nói (tab cũ 5)

| Tính năng cũ | Chỗ mới |
|---|---|
| Danh sách truyện, Mở, 🗑 xoá, nhãn Nháp, dung lượng | `/sach` thẻ truyện (tiến độ + trạng thái); xoá trong Cài đặt truyện → Nâng cao |
| Nhập truyện (file, tên, tác giả, tự dò encoding) | Trình hướng dẫn bước 1 (kéo thả; tên truyện; tác giả trong trang Cài đặt); encoding tự động, không hiện |
| Cài đặt: tên, tác giả, giọng kể, tốc độ | Trang truyện → thẻ "Cài đặt" + bước 3 |
| Đọc tiêu đề chương | Bước 3 "Nâng cao" + Cài đặt truyện |
| Nghỉ giữa đoạn / sau tiêu đề | Cài đặt truyện → Nâng cao (hiện trong bước 3 "Nâng cao" dạng chọn sẵn) |
| Lời thoại giọng thứ hai | Công tắc "Lời thoại đọc bằng giọng khác" ở bước 3 và Cài đặt |
| Chuẩn hoá văn bản | Cài đặt truyện → Nâng cao |
| Từ điển phát âm (của truyện) | Thẻ phụ "Cách đọc tên riêng" |
| Từ điển toàn cục | Cài đặt truyện → Nâng cao "Cách đọc tên riêng dùng chung" |
| Gợi ý tên riêng (ngưỡng, quét, ▶, thêm, thụt dòng) | "Tìm tên riêng trong truyện" (ngưỡng ẩn thành mặc định 3 lần; chỉnh trong Nâng cao) |
| Làm sạch: 11 quy tắc, số dòng, "Xem", "Giữ dòng này", ngoại lệ | Bước 2 → Có chỗ sai → "Dọn văn bản" (5 lựa chọn bằng lời thường; số chỗ + "xem"); quy tắc còn lại tự bật, mở trong Nâng cao |
| Khoảng nghỉ ngăn cảnh | Dọn văn bản → Nâng cao |
| Quy tắc tuỳ chỉnh (regex) | Cài đặt truyện → Nâng cao "Quy tắc dọn riêng" |
| Tách chương: cách tách, regex, selector, "Mặc định" | Bước 2 → "Chia chương chưa đúng chỗ" (chọn bằng ví dụ); regex/selector trong Nâng cao |
| Xem trước chương, thống kê, cảnh báo thiếu/trùng, từ bị che + "từ đúng là…" | **Bước 2 "Kiểm tra"** (tự chạy khi vào bước, không phải bấm nút) |
| Gộp với chương sau, Tách…, Bỏ gộp/tách thủ công | Bước 2 → "Gộp hoặc tách chương" |
| Xác nhận tách chương | nút **Đúng rồi, tiếp tục** |
| Danh sách chương + trạng thái | Trang truyện → "Các chương" |
| Tóm tắt hàng đợi, thanh tiến độ, "Đang tạo chương n đoạn a/b", ghi chú tạm dừng | Đầu trang truyện (số lớn + thanh + thời gian còn lại) và chỉ báo trên cùng |
| Chạy tất cả / Chạy thử 5 chương đầu | Bước 3: nút **Bắt đầu tạo sách nói** + ô "Tạo thử 5 chương trước"; trang truyện: "Tạo trước" từng chương, tiếp tục sau khi nghe thử |
| Chạy khoảng (từ…đến…) | Tải về → "Chỉ một số chương…" (cho xuất) và "Tạo trước" từng chương (cho tạo); khoảng tạo hàng loạt: menu ⋯ ở đầu danh sách chương (UX-1) |
| Tạo lại chương lỗi thời | Banner "Cần tạo lại N chương" + nút "Tạo lại các chương này" |
| Tạm dừng / Tiếp tục | Nút lớn đầu trang truyện |
| Huỷ hàng đợi | "Dừng hẳn" (có xác nhận) |
| Giữ máy không ngủ | Cài đặt chung (công tắc) |
| Đọc thử 1 phút (đầu / giữa chương) + thanh tiến độ | Bước 3 "Nghe thử 1 phút đầu chương 1"; từng chương: ▶ ở trang truyện (đầu chương); "giữa chương" thành menu ⋯ → "Nghe thử đoạn giữa" (UX-1) |
| ▶ nghe 300 ký tự đầu chương | ▶ mỗi chương (trình phát đáy) |
| Nghe (bản đã tạo) | ▶ chương đã xong |
| Tạo / Tạo lại từng chương | "Tạo trước" / menu ⋯ → "Tạo lại chương này" |
| Xem (văn bản chương đã dọn) | menu ⋯ → "Xem chữ của chương" |
| Xuất MP3 (zip) 64/80/96, Xuất .m4b, danh sách file đã xuất | Nút **Tải về ▾** (Từng chương MP3 / Một file có mục lục / Chỉ một số chương); chất lượng MP3 và file đã xuất trong Cài đặt truyện → Nâng cao |
| Dung lượng + Xoá nguồn FLAC | Cài đặt truyện → Nâng cao "Dung lượng" + "Giải phóng chỗ trống" (có xác nhận) |
| Xem chương (hộp thoại) | menu ⋯ |
| Thông báo trình duyệt khi xong | Cài đặt chung (công tắc), xin quyền khi bấm tạo |

### Chung

| Tính năng cũ | Chỗ mới |
|---|---|
| Nhãn "VieNeu · int8" | Cài đặt chung → Nâng cao |
| Chọn mức "chính xác" (biến môi trường) | Cài đặt chung: "Giọng trên máy ưu tiên: Tự chọn / Nhanh hơn / Tự nhiên nhất" (ánh xạ lên biến hiện có, UX-1 chỉ đọc trạng thái) |
| Nhớ engine/giọng đã chọn | giữ (`localStorage`) |
| `confirm()` của trình duyệt | hộp xác nhận cùng phong cách, câu chữ nói rõ hậu quả |
| (mới) Chỉ báo việc đang tạo trên mọi trang | thanh trên cùng |
| (mới) Trình phát chung, tua, tốc độ phát | đáy màn hình |

## 4. Điểm chưa chắc, cần bạn quyết định

1. **"Làm sách nói" có là thẻ chính?** Tôi đặt viền nhấn vì đó là việc chính của bạn; "Đọc văn bản" là việc phụ. Nếu hay đọc nhanh hơn thì đổi thứ tự thẻ.
2. **Tốc độ đọc:** 3 mức Chậm / Vừa / Nhanh. API hiện nhận phần trăm (0, 100, 200 ứng với 1×, 2×, 3×). Tôi muốn ánh xạ Chậm = −20%, Vừa = 0, Nhanh = +30%. Mức này có đủ không, hay bạn cần chọn chính xác?
3. **Trình hướng dẫn thêm truyện bắt buộc đi hết 3 bước?** Bước 2 có thể bỏ qua nếu tool thấy mọi thứ ổn (không cảnh báo). Mặc định đề xuất: **luôn hiện** bước 2 vì đây chính là chỗ giải thích "chia chương để làm gì".
4. **Gộp "tạo thử 5 chương" vào bước 3 mặc định bật cho truyện > 20 chương**: đồng ý? Sau 5 chương, tool dừng và hỏi "Ưng chưa? Tạo tiếp phần còn lại" hay tự chạy tiếp?
5. **Giọng online và giọng trên máy trong cùng một danh sách** (nhãn bên cạnh) hay luôn tách hai nhóm như bản mẫu ở trang đọc? Bản mẫu: tách bằng 2 nút ở trang Đọc, nhưng hiện chung ở Giọng của tôi và bước 3.
6. **Chọn giọng cho nhân vật phụ (nhiều người đọc):** bản mẫu cho chọn thủ công từng tên. Có muốn thêm "Tự chọn giọng khác nhau cho mỗi người" không?
7. **Giữ lại "đọc thử giữa chương"?** Nó giúp nghe đoạn thoại/tên riêng, nhưng thêm một nút. Đề xuất đưa vào menu ⋯ của chương.
8. **Chạy khoảng chương (từ…đến…) để tạo:** bản mẫu chưa có chỗ nổi bật (chỉ "Tạo trước" từng chương). Nếu bạn hay tạo theo khoảng, đề xuất menu ⋯ ở đầu danh sách chương.
9. **Một Lịch sử chung** cho đọc văn bản và hội thoại (thay hai danh sách): chấp nhận được không? Lịch sử không chứa sách nói (sách nói có trang riêng).
10. **Vùng miền, thẻ, mô tả của giọng:** bản mẫu bỏ các ô này khỏi luồng chính (chỉ trong "Thêm thông tin"). Bạn có dùng lọc vùng miền không?
11. **Tên "Giọng của tôi"** gồm cả giọng dựng sẵn của tool (Hải Đăng…). Có thấy lạ không? Phương án khác: "Các giọng".
12. **Thuật ngữ còn lại ở Cài đặt chung → Nâng cao** (VieNeu, int8, cache…) được phép theo quy tắc; xác nhận chỉ để trong đó.
13. **Backend:** UX-0 không cần endpoint mới. Cho UX-1 tôi **đề xuất** (chờ duyệt): một `GET /api/overview` gộp trạng thái hàng đợi + danh sách truyện + giọng để vẽ màn chính bằng 1 request (hiện cần 3–4 request; không bắt buộc).
14. **Mọi nút "xoá/tạo lại/giải phóng"** dùng hộp xác nhận nói rõ hậu quả. Có muốn thêm hoàn tác (vài giây) thay xác nhận cho xoá giọng/lịch sử không? (cần thêm API khôi phục, nên chưa đề xuất).

## 5. Cách làm ở UX-1 (đề xuất, chưa làm)

- Tách `static/index.html` + `static/css/{tokens,base,components}.css` + `static/js/*.js` (ES modules: `api.js`, `router.js`, `player.js`, `views/{home,books,wizard,book,read,voices}.js`, `errors.js`).
- `tokens.css` là nguồn duy nhất của màu, cỡ chữ, khoảng cách (đã có khối tokens trong prototype, sáng/tối theo hệ thống).
- `errors.js` ánh xạ lỗi từ API sang lời thường + "Xem chi tiết".
- Giữ nguyên mọi endpoint; `smoke_test.sh` thêm 1 bước tải `/`, `/css/tokens.css`, `/js/app.js` và kiểm chuỗi cấm ngoài "Nâng cao" bằng trình duyệt headless.
