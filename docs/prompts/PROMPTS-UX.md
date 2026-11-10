> Viết trước khi sắp xếp lại thư mục (11/2026): đường dẫn trong file là đường dẫn cũ, xem bảng trong PROMPTS-RESTRUCTURE.md.

# Prompt bundle: làm lại UX/UI "Giọng Việt"

Dán **từng phase** cho agent. Mỗi phase kết thúc bằng **STOP & REPORT**.
Đặt file này ở gốc repo để agent tự đọc.

---

## PROMPT UX-0: Bối cảnh, quy tắc, kiểm kê và bản mẫu (dán đầu tiên)

```
Mục tiêu: làm lại giao diện "Giọng Việt" cho dễ dùng, thân thiện với người không biết kỹ thuật.
Người dùng chính: một người làm audio cho truyện (sách nói) và thỉnh thoảng đọc nhanh một đoạn văn.
Vấn đề hiện tại (phản hồi của người dùng): "tool quá khó dùng".
Cụ thể: quá nhiều tab ngang hàng, nhiều thuật ngữ kỹ thuật, cài đặt lộ hết ra, làm sách nói phải
đi qua nhiều bước rời rạc, và không hiểu tách chương để làm gì.

QUY TẮC CHUNG (mọi phase UX):
1. CHỈ làm lại giao diện. KHÔNG đổi API backend. Nếu thật sự cần một endpoint mới cho UI
   (ví dụ gộp dữ liệu), đề xuất trong report, chờ duyệt.
2. smoke_test.sh phải PASS sau mỗi phase.
3. Không build step, không framework. Được phép tách frontend thành nhiều file tĩnh:
   static/index.html + static/css/*.css + static/js/*.js (ES modules gốc của trình duyệt).
4. Ngôn ngữ trên UI: tiếng Việt đời thường. Cấm các từ sau trên giao diện chính (chỉ được
   xuất hiện trong mục "Nâng cao"): engine, precision, int8, fp32, alpha, slider, cache,
   regex, selector, seed, RTF, embedding, mode, job, queue.
   Bảng đổi tên gợi ý:
     edge-tts → "Giọng online (nhanh, cần mạng)"
     VieNeu   → "Giọng trên máy (tự nhiên hơn)"
     tách chương → "Chia chương"
     làm sạch → "Dọn văn bản"
     từ điển phát âm → "Cách đọc tên riêng"
     trộn giọng → "Pha giọng"
     hàng đợi → "Đang tạo"
     lỗi thời → "Cần tạo lại (bạn đã đổi cài đặt)"
5. Ẩn dần: mặc định chỉ hiện thứ người dùng cần cho 80% trường hợp. Mọi tuỳ chọn kỹ thuật dồn
   vào khối "Nâng cao" đóng sẵn. Không xoá tính năng nào.
6. Mỗi màn hình phải trả lời được 3 câu: tôi đang ở đâu, việc chính ở đây là gì (1 nút chính
   nổi bật duy nhất), bước tiếp theo là gì.
7. Báo lỗi bằng lời thường, kèm cách khắc phục. Ví dụ: không hiện "502 No audio was received"
   mà hiện "Giọng online đang bận, đã thử lại 3 lần. Thử lại sau ít phút hoặc chọn giọng
   trên máy." (Chi tiết kỹ thuật để trong "Xem chi tiết".)
8. Màu sắc và kích thước dùng CSS custom properties (design tokens) trong một file
   static/css/tokens.css, để sau này thay bộ màu dễ dàng. Có sáng/tối theo hệ thống.
9. Cuối mỗi phase, chụp screenshot ở 1280px và 390px gửi kèm report (out/ux/<phase>/).

PHASE UX-0: kiểm kê + kiến trúc thông tin + bản mẫu tĩnh. CHƯA sửa UI thật.
1. Kiểm kê: liệt kê mọi màn hình, nút, tuỳ chọn hiện có trong static/index.html. Phân loại
   từng thứ: [chính] dùng thường xuyên, [phụ] thỉnh thoảng, [nâng cao] hiếm khi dùng hoặc
   kỹ thuật. Ghi vào out/ux/inventory.md.
2. Kiến trúc thông tin đề xuất (có thể điều chỉnh nếu có lý do):
   - Màn hình chính có 3 thẻ lớn: "Đọc văn bản", "Làm sách nói", "Giọng của tôi".
   - "Đọc văn bản" gồm cả hội thoại: có công tắc "Nhiều người đọc". Bật lên thì ô văn bản
     thành ô kịch bản [Tên]: lời, kèm bảng chọn giọng cho từng người.
   - "Làm sách nói" = danh sách truyện + nút "Thêm truyện". Thêm truyện là trình hướng dẫn
     3 bước:
       Bước 1 "Chọn file": kéo thả .txt/.epub/.html/.zip. Giải thích một câu:
         "Tool sẽ tự chia truyện thành từng chương để bạn nghe và tạo từng phần."
       Bước 2 "Kiểm tra": "Tìm thấy N chương" + danh sách rút gọn + cảnh báo bằng lời thường
         (thiếu chương, chương quá dài/ngắn, từ bị che chưa khôi phục). Hai nút
         [Đúng rồi, tiếp tục] và [Có chỗ sai]. [Có chỗ sai] mở các công cụ sửa (mẫu tiêu đề
         chương bằng ví dụ, gộp/tách, dọn văn bản).
       Bước 3 "Chọn giọng và nghe thử": chọn giọng bằng thẻ có nút ▶, nghe thử 1 phút đầu
         chương 1, rồi nút chính [Bắt đầu tạo sách nói]. Có lựa chọn "Tạo thử 5 chương trước"
         (đề xuất mặc định cho truyện > 20 chương).
     Sau khi tạo: trang truyện dạng "bảng điều khiển": tiến độ lớn, thời gian còn lại, nút
     Tạm dừng/Tiếp tục, danh sách chương có ▶, nút "Tải về" (MP3 hoặc 1 file có mục lục),
     tab phụ "Cách đọc tên riêng" và "Cài đặt".
   - "Giọng của tôi" = thư viện (thẻ giọng, yêu thích, lọc) + 2 nút: "Thêm giọng từ file
     ghi âm" và "Pha giọng mới".
   - Thanh trên cùng luôn có: logo/tên, chỉ báo "Đang tạo: Truyện X, chương 12/171, còn
     ~9 giờ" (bấm vào để tới trang truyện), nút Lịch sử, nút Cài đặt chung.
   - Trình phát nhỏ dính ở đáy màn hình, phát mọi thứ (nghe thử, lịch sử, chương), có
     tua và tốc độ phát.
3. Bản mẫu tĩnh: out/ux/prototype.html. Một file, dữ liệu giả, bấm qua được toàn bộ luồng:
   màn chính → làm sách nói (3 bước) → trang truyện → đọc văn bản (bật/tắt nhiều người
   đọc) → giọng của tôi. Không gọi API. Phong cách tối giản, chữ lớn dễ đọc, khoảng trắng
   rộng, 1 màu nhấn.
4. Report gồm:
   - inventory.md;
   - sơ đồ điều hướng (text);
   - bảng "chỗ cũ → chỗ mới" cho từng tính năng, để chứng minh không mất tính năng nào;
   - danh sách điểm chưa chắc cần người dùng quyết định;
   - screenshot các màn của prototype.
STOP & REPORT. Người dùng sẽ bấm thử prototype và góp ý trước khi làm UX-1.
```

---

## PHASE UX-1: Nền móng

```
PHASE UX-1: nền móng frontend, chưa đổi giao diện người dùng thấy.
1. Tách static/index.html thành:
   - css/tokens.css, css/base.css, css/components.css
   - js/api.js (mọi fetch, xử lý lỗi thành thông báo lời thường theo quy tắc 7)
   - js/state.js, js/router.js (điều hướng bằng hash: #/, #/doc, #/sach-noi, #/sach-noi/<id>,
     #/giong; nút Back của trình duyệt hoạt động)
   - js/components/*.js
2. Component dùng chung (mỗi cái một file):
   - VoicePicker (thẻ giọng, ▶, yêu thích, tìm, lọc nam/nữ/vùng, nhóm "Giọng online" và
     "Giọng trên máy", giọng không dùng được thì mờ kèm lý do);
   - MiniPlayer;
   - Toast (thông báo);
   - Dialog;
   - ProgressBar;
   - EmptyState (minh hoạ đơn giản + 1 câu + 1 nút);
   - Advanced (khối "Nâng cao" đóng sẵn, nhớ trạng thái);
   - EmotionBar (dùng lại logic cũ).
3. Giao diện cũ vẫn chạy y như trước, nhưng đã dùng các module mới bên dưới.
4. smoke_test.sh PASS. Report liệt kê file mới và dòng code giảm/tăng.
STOP & REPORT.
```

---

## PHASE UX-2: Màn hình chính, Đọc văn bản, thanh trên, trình phát

```
PHASE UX-2: theo prototype đã duyệt ở UX-0 (và góp ý của người dùng), làm:
- Màn hình chính 3 thẻ. Lần đầu mở có 1 dòng chào ngắn + gợi ý "Bắt đầu bằng đọc thử một
  đoạn văn" (bấm tắt vĩnh viễn được).
- Đọc văn bản:
  * ô văn bản lớn; VoicePicker gọn (giọng đang chọn + nút "Đổi giọng" mở picker đầy đủ);
  * tốc độ dạng 3 nút "Chậm / Bình thường / Nhanh", tinh chỉnh trong Nâng cao;
  * nút chính "Đọc";
  * công tắc "Nhiều người đọc";
  * Nâng cao: cao độ, chuẩn hoá văn bản, nhân bản trực tiếp từ file mẫu, khoảng nghỉ hội thoại.
- Thanh trên + chỉ báo "Đang tạo" (polling nhẹ mỗi 5s, chỉ khi có việc đang chạy).
- MiniPlayer cho mọi audio. Bỏ các thẻ <audio> rải rác.
- Lịch sử: ngăn kéo trượt từ cạnh phải, mở bằng nút trên thanh trên.
Report kèm screenshot 1280/390 và một video GIF ngắn luồng "đọc một đoạn" (Chromium headless).
STOP & REPORT.
```

---

## PHASE UX-3: Làm sách nói (trình hướng dẫn + trang truyện)

```
PHASE UX-3: Làm sách nói theo prototype.
- Trình hướng dẫn 3 bước như UX-0. Mỗi bước có thanh bước (1 Chọn file · 2 Kiểm tra ·
  3 Chọn giọng). Quay lại bước trước không mất dữ liệu.
- [Có chỗ sai] mở công cụ sửa bằng lời thường:
  * "Tiêu đề chương trong truyện viết thế nào?" (dán 1 dòng ví dụ → tool tự suy ra mẫu;
    ô mẫu dạng regex chỉ ở trong Nâng cao);
  * gộp/tách bằng nút trên từng chương;
  * Dọn văn bản: danh sách quy tắc bằng lời thường, mỗi quy tắc có "Xem những dòng bị đổi".
- Cảnh báo ở bước 2 kèm hành động: "Còn 3 từ bị che chưa đoán được" → [Điền ngay].
- Trang truyện (bảng điều khiển):
  * khối tiến độ lớn (vòng hoặc thanh), "còn khoảng X giờ", nút Tạm dừng/Tiếp tục;
  * danh sách chương (lọc: tất cả / đã xong / đang chờ / cần tạo lại);
  * nút "Tải về" mở dialog chọn "Từng chương (MP3)" hoặc "Một file nghe trên điện thoại
    (có mục lục)";
  * tab "Cách đọc tên riêng": danh sách gợi ý dạng thẻ, ▶ nghe thử, nút "Đọc sai? Sửa"
    mở ô "đọc thành…" + "ngắt nghỉ trước/sau";
  * tab "Cài đặt": giọng, tốc độ, nghỉ giữa đoạn/sau tiêu đề; Nâng cao cho phần còn lại.
  * khi đổi cài đặt làm chương cần tạo lại: banner "12 chương cần tạo lại vì bạn đã đổi
    giọng" + [Tạo lại].
- Dung lượng: hiện trong Cài đặt của truyện bằng lời thường ("Truyện này đang chiếm 4,2 GB")
  + nút dọn.
Report kèm screenshot + GIF luồng "thêm truyện từ 3 file html → tạo thử 5 chương".
STOP & REPORT.
```

---

## PHASE UX-4: Giọng của tôi

```
PHASE UX-4: Giọng của tôi.
- Lưới thẻ giọng (dùng lại VoicePicker ở chế độ quản lý), nhóm: Yêu thích / Giọng của tôi
  (clone, pha) / Giọng có sẵn.
- "Thêm giọng từ file ghi âm": dialog 2 bước (chọn file hoặc ghi âm → đặt tên + xác nhận
  quyền sử dụng giọng). Hiện hướng dẫn ngắn: "3–10 giây, một người nói, không nhạc nền".
- "Pha giọng mới": chọn 2 giọng bằng thẻ, thanh kéo hai đầu ghi tên giọng, tự nghe thử khi
  thả tay, nút "Lưu giọng này".
- Thẻ giọng: ▶, ★, menu ⋯ (Đổi tên, Dùng để đọc, Xoá).
Report kèm screenshot.
STOP & REPORT.
```

---

## PHASE UX-5: Hoàn thiện

```
PHASE UX-5: hoàn thiện.
1. Rà toàn bộ chữ trên UI theo quy tắc 4. Liệt kê các chữ đã đổi trong report.
2. Trạng thái rỗng cho mọi danh sách (chưa có truyện, chưa có giọng, lịch sử trống).
3. Trạng thái đang tải dạng skeleton thay cho chữ "Đang tải…".
4. Bàn phím:
   - Ctrl+Enter: đọc;
   - Space: phát/dừng mini player khi không gõ chữ;
   - Esc: đóng dialog;
   - "?": mở bảng phím tắt.
5. Truy cập:
   - focus nhìn thấy được;
   - mọi nút icon có aria-label;
   - tương phản chữ đạt WCAG AA;
   - không chỉ dùng màu để báo trạng thái.
6. Responsive 390/768/1280 không tràn ngang.
7. Trang "Cài đặt chung": giọng mặc định, chạy chống ngủ máy, thông báo khi xong. Nâng cao:
   chế độ chạy, kích thước đoạn, dung lượng cache.
8. smoke_test.sh PASS. Thêm vào smoke test một bước headless:
   - mở từng route;
   - không có lỗi JS;
   - không có chữ nào trong danh sách cấm (quy tắc 4) xuất hiện ngoài khối Nâng cao.
STOP & REPORT (báo cáo cuối).
```
