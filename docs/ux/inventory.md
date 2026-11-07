# Kiểm kê giao diện hiện tại (`static/index.html`, 1.898 dòng, 1 file)

Phân loại: **[chính]** dùng thường xuyên · **[phụ]** thỉnh thoảng · **[nâng cao]** hiếm khi dùng hoặc kỹ thuật.
Cột "Vấn đề" ghi lý do người không rành kỹ thuật bị vướng (dùng để quyết định đặt lại chỗ ở UX-1).

Hiện có **5 tab ngang hàng**, 4 hộp thoại (Nhập truyện, Xem chương, Thêm/Sửa giọng, Lưu giọng pha) và khoảng **150 điều khiển**.
Tab "Sách nói" một mình có 9 thẻ xếp dọc (Cài đặt, Từ điển, Gợi ý tên, Làm sạch, Tách chương, Danh sách chương…) và ~70 điều khiển.

---

## Thanh trên cùng

| Thứ | Loại | Vấn đề |
|---|---|---|
| Tên "Giọng Việt" + dòng phụ | [phụ] | — |
| Nhãn "VieNeu · int8" (độ chính xác model) | [nâng cao] | Thuật ngữ kỹ thuật, nằm ở chỗ ai cũng thấy |
| 5 tab: Đọc văn bản · Thư viện giọng · Tạo giọng mới · Hội thoại · Sách nói | [chính] | Ngang hàng nhau dù việc chính chỉ có 2 (đọc nhanh, làm sách nói); "Tạo giọng mới" thực chất là pha giọng, "Hội thoại" thực chất là đọc nhiều người |
| (không có) chỉ báo việc đang chạy nền | — | Làm sách nói chạy hàng giờ mà rời tab Sách nói là không biết nó có đang chạy không |
| (không có) trình phát chung | — | Mỗi tab có `<audio>` riêng; nghe chương xong chuyển tab là mất |

## Tab 1 — Đọc văn bản

| Thứ | Loại | Vấn đề |
|---|---|---|
| Ô nhập văn bản + bộ đếm ký tự | [chính] | — |
| Gợi ý "Ctrl + Enter để đọc" | [phụ] | — |
| Hàng nút chèn: thẻ cảm xúc (`[cười]`, `[thở dài]`…), "Ngắt nhẹ", "Xuống đoạn", "Nghỉ… (giây)" | [phụ] | Hàng nút dài, tên thẻ trong ngoặc vuông khó hiểu; chỉ hiện với giọng hỗ trợ |
| **Engine** (2 nút: Nhanh / Chất lượng cao) | [chính] | Từ "Engine"; mô tả "edge-tts · cần mạng" |
| Giọng đọc (danh sách thả, có ♥ 🎙️ 🎚️) + gợi ý "Lần đầu sẽ tải model…" | [chính] | Danh sách thả dài, không nghe thử được tại chỗ |
| Tốc độ 1x / 2x / 3x | [chính] | — |
| Cao độ (−50…50 Hz) | [nâng cao] | Chỉ có với giọng online |
| Chuẩn hoá văn bản (số, ngày, đơn vị…) | [nâng cao] | Mặc định bật, ít khi cần tắt |
| Nhân bản giọng từ file mẫu 3–8 giây (kéo thả) + chú thích | [phụ] | Trùng chức năng với "Thêm giọng" ở thư viện, giải thích khó |
| Nút "Đọc văn bản" + dòng báo lỗi | [chính] | Lỗi hiện nguyên văn kỹ thuật |
| Trình phát kết quả (trong lịch sử) | [chính] | — |
| **Lịch sử** (50 bản): kiểu (đọc / hội thoại), giờ, tên giọng (kèm "đã xoá"), văn bản, trình phát, Tải WAV/MP3, "Dùng lại", "Xoá", "Xoá tất cả" | [phụ] | Dài, nằm dưới ô nhập; chung với tab Hội thoại bằng 2 danh sách riêng |

## Tab 2 — Thư viện giọng

| Thứ | Loại | Vấn đề |
|---|---|---|
| Ô tìm (tên, thẻ, mô tả) | [chính] | — |
| Lọc giới tính / vùng miền / "Tất cả · Yêu thích · Giọng của tôi · Giọng dựng sẵn" | [phụ] | 4 ô lọc cùng lúc, nhiều hơn cần thiết |
| Nút "+ Thêm giọng" | [chính] | Mở hộp thoại 9 trường |
| Thẻ giọng: tên, ♥ yêu thích, giới tính · vùng · engine, thẻ, mô tả, nhãn "Trộn" / ⚠ không dùng được | [chính] | Hiện tên engine |
| Nút trên thẻ: ▶ Nghe thử · "Dùng giọng này" · ✎ Sửa · 🗑 Xoá | [chính]/[phụ] | "Dùng giọng này" chuyển tab, người dùng mất ngữ cảnh |
| **Hộp thoại Thêm/Sửa giọng**: tên, Engine, file mẫu (kéo thả), ● Ghi âm, thông tin thời lượng, giới tính, vùng miền, thẻ, mô tả, tick đồng ý chủ giọng | [phụ] | Engine; "giới tính/vùng/thẻ/mô tả" bắt buộc phải nhìn dù không cần |

## Tab 3 — Tạo giọng mới (pha giọng)

| Thứ | Loại | Vấn đề |
|---|---|---|
| Giọng A / Giọng B: ô tìm + danh sách thả + ▶ | [chính] | — |
| Thanh trượt pha (nhãn 2 đầu = tên 2 giọng) + dòng phần trăm | [chính] | Từ "thanh trượt" trong tick bên dưới |
| Câu thử | [phụ] | — |
| "Nghe thử" + tick "Tự nghe thử khi thả thanh trượt" | [chính] | — |
| "Lưu vào thư viện" → hộp thoại tên, giới tính, vùng, thẻ, mô tả | [chính] | — |
| Trình phát kết quả | [chính] | — |

## Tab 4 — Hội thoại

| Thứ | Loại | Vấn đề |
|---|---|---|
| Ô kịch bản `[Tên]: lời` + đếm dòng + chú thích "Dòng trống = nghỉ dài hơn" | [chính] | Người không biết cú pháp `[Tên]:` |
| Hàng nút chèn (thẻ cảm xúc, Ngắt nhẹ, Xuống đoạn, Nghỉ…) | [phụ] | Như tab Đọc |
| Cảnh báo "giọng X không hỗ trợ thẻ…" / lỗi cú pháp | [phụ] | Câu chữ kỹ thuật |
| **Diễn viên**: mỗi tên một danh sách chọn giọng (tự gợi ý) | [chính] | — |
| Tốc độ 1x/2x/3x | [chính] | Lặp lại tab Đọc |
| Nghỉ giữa dòng (ms) / Nghỉ giữa đoạn (ms) | [nâng cao] | Đơn vị mili-giây |
| Chuẩn hoá văn bản (chỉ giọng VieNeu) | [nâng cao] | Tên engine |
| "Tạo audio" + thanh tiến độ "n/N dòng" | [chính] | — |
| Kết quả: trình phát, Tải WAV / MP3 | [chính] | — |
| Danh sách dòng: số, người nói, ✓ / "✓ cache" / ⚠, ▶ nghe dòng, 🔄 sinh lại dòng | [phụ] | "cache" |
| **Dự án**: danh sách thả, Mở, Xoá, tên, "Lưu dự án" | [phụ] | — |
| Lịch sử hội thoại + "Xoá tất cả" | [phụ] | Danh sách thứ hai ngoài Lịch sử của tab Đọc |

## Tab 5 — Sách nói

### 5a. Danh sách truyện

| Thứ | Loại |
|---|---|
| Thẻ truyện: tên, tác giả, "N chương · N ký tự · đã dùng X MB", nhãn "Nháp", Mở, 🗑 | [chính] |
| "+ Nhập truyện" | [chính] |

### 5b. Hộp thoại Nhập truyện

| Thứ | Loại | Vấn đề |
|---|---|---|
| Chọn file (.txt .epub .html .htm .zip, nhiều file) | [chính] | Nhãn dài 3 dòng, không kéo thả |
| "Tự dò encoding UTF-8 / UTF-16…" | [nâng cao] | Thuật ngữ; người dùng không cần biết |
| Tên truyện, Tác giả | [chính]/[phụ] | — |

### 5c. Trang truyện (9 thẻ dọc, theo thứ tự hiện tại)

| # | Thẻ / điều khiển | Loại | Vấn đề |
|---|---|---|---|
| 1 | **Cài đặt**: tên, tác giả, giọng kể, tốc độ | [chính]/[phụ] | — |
| | Chuẩn hoá văn bản (chỉ giọng VieNeu) | [nâng cao] | — |
| | Đọc tiêu đề chương ở đầu mỗi chương | [phụ] | — |
| | Nghỉ giữa các đoạn văn (giây), Nghỉ sau tiêu đề (giây) + chú thích "lỗi thời" | [nâng cao] | "lỗi thời" |
| | Lời thoại đọc bằng giọng thứ hai + chọn giọng | [phụ] | — |
| | Lưu cài đặt | [chính] | Phải nhớ bấm lưu |
| 2 | **Từ điển phát âm**: của truyện / toàn cục; mỗi mục: cụm, đọc thành, nghỉ trước, nghỉ sau, nguyên từ, hoa/thường, ✕ | [phụ] | Nhiều cột; "toàn cục" |
| | + Thêm mục (×2), Lưu từ điển | [phụ] | — |
| 3 | **Gợi ý tên riêng**: ngưỡng "xuất hiện tối thiểu N lần", Quét truyện; mỗi gợi ý: số lần, chương, câu ví dụ, ▶ Nghe thử, + Thêm vào từ điển (tiếng đơn thụt dưới cụm cha) | [phụ] | Tách rời khỏi từ điển cùng nghĩa |
| 4 | **Làm sạch văn bản**: 11 quy tắc bật/tắt (ký tự điều khiển, ngoặc kép, ba chấm, dòng URL, dòng nguồn, ngăn cảnh, dòng trùng, gộp dòng ngắt, khôi phục từ bị che, ghép số, bỏ dòng trống) | [nâng cao] | 11 công tắc thuật ngữ, phần lớn nên tự bật |
| | Khoảng nghỉ ở dấu ngăn cảnh (giây) | [nâng cao] | — |
| | Quy tắc tuỳ chỉnh (regex → thay thế), thêm/xoá | [nâng cao] | regex |
| | Ngoại lệ đã giữ (✕ bỏ) | [nâng cao] | — |
| 5 | **Tách chương**: cách tách (regex / mỗi file một chương), khung chương HTML (selector), regex tiêu đề + "Mặc định" | [nâng cao] | regex, selector; **không giải thích tách chương để làm gì** |
| | "Xem trước chương", "Bỏ gộp/tách thủ công" | [chính] | Nằm sau 4 thẻ khác |
| | Kết quả xem trước: thống kê, cảnh báo (thiếu/trùng chương…), từ bị che chưa biết (ô "từ đúng là…" + Lưu), ghi chú lỗi chính tả | [chính] | — |
| | Mỗi quy tắc: số dòng bị ảnh hưởng + "Xem" (50 dòng; "Giữ dòng này") | [nâng cao] | — |
| | Mỗi chương: tên, số ký tự, thời gian ước tính, đoạn đầu, "Gộp với chương sau", "Tách…" | [phụ] | — |
| | "Xác nhận tách chương" | [chính] | Nằm sau cuối thẻ thứ 5 |
| 6 | **Danh sách chương** (chỉ hiện sau khi xác nhận): tiêu đề "Danh sách chương (N)" | [chính] | Phải cuộn qua 5 thẻ mới tới |
| | Tóm tắt "Hàng đợi: đang chạy · x/N chương xong · Ước tính…", thanh tiến độ, dòng "Đang tạo chương n — đoạn a/b", ghi chú (tạm dừng vì lỗi) | [chính] | "Hàng đợi", "đoạn" |
| | **Chạy tất cả**, Chạy thử 5 chương đầu, Chạy khoảng (từ…đến…) | [chính]/[phụ] | 3 nút gần nhau, không rõ nên bấm nút nào |
| | Tạo lại chương lỗi thời | [phụ] | "lỗi thời" |
| | Tạm dừng / Tiếp tục, Huỷ hàng đợi | [chính] | — |
| | Giữ máy không ngủ khi đang tạo (+ trạng thái) | [phụ] | — |
| | Đọc thử: thanh tiến độ + chữ | [chính] | — |
| | Xuất: chọn MP3 64/80/96 kbps, Xuất MP3 (zip), Xuất .m4b, danh sách file đã xuất | [chính] | kbps, m4b |
| | Dung lượng đã dùng + "Xoá nguồn FLAC của chương đã xuất" | [phụ] | FLAC |
| | Mỗi chương: tên, ký tự, thời gian, trạng thái (chưa tạo / đang chờ / đang tạo đoạn a/b / đã xong / đã xuất / lỗi / lỗi thời), nút ▶ (300 ký tự), Đọc thử 1 phút, …giữa chương, Nghe, Tạo, Tạo lại, Xem | [chính] | 5–6 nút mỗi dòng chương |

## Hộp thoại phụ

| Thứ | Loại |
|---|---|
| Xem chương (văn bản đã dọn) | [phụ] |
| Lưu giọng pha (tên, giới tính, vùng, thẻ, mô tả) | [chính] |
| Xác nhận bằng `confirm()` của trình duyệt (xoá, tạo lại, huỷ, xoá FLAC) | [phụ] — giao diện hệ thống, không đồng bộ phong cách |

## Hành vi ngầm (không có nút)

| Hành vi | Loại |
|---|---|
| Nhớ engine / giọng đã chọn (`localStorage`) | [chính] |
| Thông báo trình duyệt khi tạo xong (xin quyền khi bấm Chạy) | [phụ] |
| Tự cuộn tab đang chọn vào giữa trên điện thoại | [phụ] |
| Báo lỗi: văn bản lỗi gốc từ server (vd. "502 No audio was received", "Hãy tách chương trước.") hiện trong dòng đỏ | [chính] — cần viết lại bằng lời thường |

## Thuật ngữ đang hiện trên giao diện chính và cách đổi

| Hiện nay | Đổi thành |
|---|---|
| Engine / edge-tts / VieNeu | Giọng online (nhanh, cần mạng) / Giọng trên máy (tự nhiên hơn) |
| Tách chương / Regex tiêu đề / Khung chương HTML (selector) | Chia chương / "Mẫu tiêu đề chương" (chỉ ví dụ) / ẩn trong Nâng cao |
| Làm sạch văn bản + 11 quy tắc | Dọn văn bản (vài lựa chọn bằng lời thường, phần còn lại tự bật) |
| Từ điển phát âm / Gợi ý tên riêng | Cách đọc tên riêng |
| Trộn giọng / Tạo giọng mới | Pha giọng |
| Hàng đợi / Huỷ hàng đợi | Đang tạo / Dừng việc đang tạo |
| Lỗi thời | Cần tạo lại (bạn đã đổi cài đặt) |
| cache, "✓ cache" | (bỏ) / "có sẵn" |
| kbps, m4b, FLAC, zip | "Tải từng chương (MP3)", "Tải một file có mục lục", "Giải phóng chỗ trống" |
| "VieNeu · int8" | chuyển vào Cài đặt chung → Nâng cao |

## Số liệu tóm tắt

| | [chính] | [phụ] | [nâng cao] |
|---|---|---|---|
| Đọc văn bản | 6 | 5 | 3 |
| Thư viện giọng | 5 | 4 | 1 |
| Pha giọng | 5 | 1 | 0 |
| Hội thoại | 6 | 5 | 3 |
| Sách nói | ~14 | ~14 | ~25 |

**Nhận xét:** tính năng "nâng cao" tập trung ở Sách nói, nhưng chính ở đó chúng nằm cùng cấp với việc chính (cuộn qua Làm sạch, Tách chương mới thấy nút Tạo). Việc chính của một lượt làm sách nói chỉ có 4 bước: chọn file → kiểm tra số chương → chọn giọng → bấm tạo; phần còn lại là sửa khi có chỗ sai.
