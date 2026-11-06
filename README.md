# Giọng Việt — Text to Speech

Web tool chuyển văn bản thành giọng nói tiếng Việt: đọc văn bản, thư viện giọng (nhân bản, yêu thích),
trộn hai giọng thành giọng mới, và hội thoại nhiều người. Chạy trên máy bạn, giao diện một trang HTML thuần.

## Tính năng theo engine

| | **Nhanh** (edge-tts) | **Chất lượng cao** (VieNeu-TTS) |
|---|---|---|
| Chạy ở đâu | Server Microsoft, cần internet | Trên máy bạn (CPU, ONNX), offline |
| Giọng | Hoài My, Nam Minh + giọng đa ngôn ngữ | 25 giọng dựng sẵn (nam/nữ, Bắc/Trung/Nam) |
| Tốc độ 1x / 2x / 3x | Có | Có |
| Cao độ | Có | Không |
| Nhân bản giọng (audio mẫu 3–10 giây) | Không | Có |
| Trộn hai giọng | Không | Có |
| Thẻ cảm xúc `[cười]` `[thở dài]` `[hắng giọng]` | Không (thẻ bị bỏ khi tạo audio) | Có (mode `v3turbo`, mặc định) |
| Chuẩn hoá văn bản (số, ngày, đơn vị…) | Microsoft tự làm | Có (sea-g2p + `text_normalize.py`) |
| Thư viện giọng, hội thoại, lịch sử | Có | Có |
| Đầu ra | MP3 | WAV 48 kHz |

Hội thoại ghép được giọng của cả hai engine; đầu ra luôn là WAV 48 kHz mono (thêm MP3 nếu có `ffmpeg`).

## Cài đặt

Đã chạy thử với Python 3.14 trên Linux. Cần Python 3.10 trở lên; nên dùng venv (xem "Lỗi thường gặp" nếu `pip` báo `externally-managed-environment`).

```bash
cd tts-tool
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

Chỉ cần edge-tts: xoá dòng `vieneu` trong `requirements.txt` trước khi cài; nút "Chất lượng cao" sẽ hiện "chưa cài".
`ffmpeg` là tuỳ chọn: có thì hội thoại xuất thêm MP3 và đọc được thêm định dạng audio mẫu (webm/m4a).

## Chạy

```bash
python server.py        # mở http://localhost:8000
```

Lần đầu dùng VieNeu, model (~1 GB) được tải từ Hugging Face một lần.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `PORT` | `8000` | Cổng chạy |
| `TTS_DATA_DIR` | `./data` | Nơi lưu thư viện giọng, lịch sử, dự án, cache |
| `TTS_MAX_CHARS` | `20000` | Độ dài tối đa của văn bản / kịch bản |
| `TTS_CACHE_MB` | `1024` | Giới hạn `data/cache/`; vượt thì xoá dòng ít dùng nhất (khi khởi động và sau mỗi hội thoại). Dòng của job đang sống không bị xoá; nếu chỉ riêng chúng đã vượt giới hạn thì server log cảnh báo |
| `VIENEU_MODE` | `v3turbo` | `v3nano` cho máy yếu (nhanh hơn, chất lượng thấp hơn, không có thẻ cảm xúc) |
| `VIENEU_PRECISION` | tự chọn | `fp32` hoặc `int8`. Không đặt thì tự chọn: `int8` nếu `/proc/cpuinfo` có `avx_vnni` hoặc `avx512_vnni`, không thì `fp32` (int8 không có VNNI sẽ méo tiếng). Đang dùng precision nào hiện ở header UI ("VieNeu · int8") và trong `GET /api/engines` (`precision`). Nằm trong khoá cache (`v3turbo-int8`), nên audio fp32 và int8 không dùng chung cache; đổi precision làm chương sách nói đã tạo thành "lỗi thời". Giọng nhân bản và giọng trộn (`emb.<mode>.npz`) **không** phụ thuộc precision, không cần tạo lại khi đổi (xem `scripts/bench_vieneu.py`) |
| `BOOK_SEGMENT_CHARS` | `800` | Kích thước đoạn của hàng đợi sách nói (đơn vị lưu, tạm dừng, tiếp tục). Nhỏ hơn thì tạm dừng nhanh hơn nhưng nhiều mối nối hơn |

## Dữ liệu trong `data/`

`voices/<id>/` (giọng nhân bản và giọng trộn), `favorites.json`, `history/` (50 bản gần nhất), `projects/`, `cache/`, `lexicon.json` (từ điển toàn cục), `books/<id>/` (`book.json`, `source/`, `chapters/`, `audio/<nnnn>.flac`, `export/`), `queue.json` (hàng đợi bền), `bench.json` (số đo của `scripts/bench_vieneu.py`).
File cấu hình sửa được, nằm trong repo: `config/name_stopwords.txt` (từ dừng của gợi ý tên riêng), `config/speech_verbs.txt` (động từ nói nhận ra phần dẫn viết hoa sau gạch thoại).
Thư mục này không nằm trong git. Không chạy hai server cùng lúc trên một `data/` (khoá ghi chỉ có trong một tiến trình).

## Sự đồng ý của chủ giọng khi nhân bản

Thêm giọng vào thư viện bắt buộc tick xác nhận bạn là chủ giọng nói hoặc đã được người đó đồng ý
(API: `consent=true`). Chỉ giọng có xác nhận này mới trộn được; giọng trộn từ giọng trộn được kiểm tra theo chuỗi giọng nguồn.
Đừng nhân bản giọng người khác khi chưa được phép.

## API

Mọi lỗi trả `{"error": "..."}` kèm mã HTTP tương ứng.

| | |
|---|---|
| `GET /api/engines` | Engine, trạng thái và `capabilities` (`clone`, `pitch`, `emotion_tags`, `mix`, `normalize`) |
| `GET /api/voices[?engine=]`, `GET /api/voices/{engine}` | Giọng (preset + thư viện) kèm `source` (`preset`/`clone`/`mix`), `favorite`, `usable` |
| `POST /api/tts` | `text`, `engine`, `voice`, `speed` (−50…200 %), `pitch`, `normalize`, `ref_audio`, `save_as` + `consent` |
| `GET/POST /api/library`, `PATCH/DELETE /api/library/{id}`, `GET /api/library/{id}/preview` | Thư viện giọng; giọng `lib:<id>` dùng được ở trường `voice` |
| `POST /api/favorites` | `engine`, `voice`, `favorite` |
| `POST /api/mix`, `POST /api/mix/save` | `voice_a`, `voice_b`, `slider` 0…1 (1 = giọng A), `text`; lưu thêm `name`, `tags`, `gender`, `region`, `description` |
| `POST /api/dialogue/parse`, `POST /api/dialogue` | Kịch bản `[Tên]: lời`; tạo job (`script`, `cast`, `speed`, `gap_ms`, `paragraph_gap_ms`, `normalize`) |
| `GET /api/dialogue/{job}`, `…/audio[?fmt=mp3]`, `…/line/{i}/audio`, `POST …/line/{i}` | Tiến độ (polling), audio tổng, audio từng dòng, sinh lại một dòng (`{"seed": n}` tuỳ chọn) |
| `GET/POST /api/projects`, `GET/DELETE /api/projects/{id}` | Dự án hội thoại |
| `GET /api/history[?kind=tts\|dialogue]`, `GET …/{id}/audio`, `DELETE /api/history[/{id}]` | Lịch sử |

Ví dụ:

```bash
curl -X POST http://localhost:8000/api/tts \
  -F text="Xin chào" -F engine=edge -F voice=vi-VN-HoaiMyNeural -F speed=0 -o out.mp3
```

Header `X-TTS-Warning` (nếu có) chỉ chứa được latin-1 nên giá trị được mã hoá phần trăm UTF-8; client phải `decodeURIComponent` / `urllib.parse.unquote` để đọc.
Khi edge-tts từ chối tổ hợp tốc độ + cao độ, server đọc lại không có cao độ và gửi cảnh báo qua header này.

## Trộn giọng

Tab **Tạo giọng mới** trộn hai giọng (preset hoặc thư viện) bằng speaker embedding 192 chiều của VieNeu:
`emb = slerp(â, b̂, α) · (α·|a| + (1−α)·|b|)` (nội suy hướng bằng slerp, nội suy độ dài tuyến tính).
`codes` lấy theo giọng có trọng số lớn hơn; hoà thì lấy giọng có norm lớn hơn. Thanh trượt 0…1 được đổi sang `α` bằng bảng đo
`SLIDER_KNOTS` / `ALPHA_KNOTS` trong `engines/vieneu.py`; `meta.json` lưu cả `slider` lẫn `alpha`.

Giới hạn: chỉ VieNeu hỗ trợ trộn giọng. Giọng trộn lưu embedding theo `VIENEU_MODE` lúc tạo (không có `ref.wav`);
đổi mode thì giọng đó vẫn hiện nhưng bị làm mờ ("tạo ở mode x", `usable:false`). Bản đồ slider→α đo trên 2 cặp giọng nên
từng cặp có thể lệch khoảng ±0.2 so với tuyến tính lý tưởng. Thí nghiệm gốc: `scripts/mix_experiment.py` → `out/mix/`.

## Hội thoại

```
[Lan]: Chào anh, hôm nay anh khoẻ không?
[Minh]: Anh khoẻ, cảm ơn em [cười].

[Lan]: Vậy thì tốt quá.
```

- Chỉ nhận `[Tên]: lời` (tên so khớp sau strip + chuẩn hoá Unicode NFC, phân biệt hoa thường). Dòng không có thẻ thuộc người nói trước; dòng trống nghỉ dài hơn (`paragraph_gap_ms`).
- Thẻ cảm xúc được chuyển cho engine hỗ trợ; engine không hỗ trợ (edge) thì thẻ bị bỏ, UI hiện ⚠ ở dòng đó.
- **Thẻ nghỉ có độ dài** `[nghỉ 0.5s]`, `[nghỉ 2s]`, `[nghỉ 1,5s]` (0.1–5 giây, dùng được với mọi engine, trong tab Đọc và trong từng dòng hội thoại): server tách văn bản tại thẻ, sinh từng đoạn bằng engine đang chọn, rồi chèn đúng khoảng lặng và ghép bằng cùng pipeline của hội thoại (decode, resample 48 kHz, cắt lặng, chuẩn hoá âm lượng, cache từng đoạn). Văn bản có thẻ nghỉ trả WAV 48 kHz (kèm MP3 trong lịch sử nếu có `ffmpeg`), kể cả với edge; văn bản không có thẻ nghỉ giữ đường cũ. Thẻ ngoài 0.1–5 giây bị từ chối (400).
- Thanh nút trên ô văn bản/kịch bản: "Nghỉ…" (nhập số giây rồi chèn thẻ nghỉ), "Ngắt nhẹ" (chèn `, `, gần như không thêm khoảng lặng) và "Xuống đoạn" (tab Đọc: xuống dòng, VieNeu tách thành đoạn mới nên nghỉ ≥ 0,7 s; tab Hội thoại: dòng trống, nghỉ `paragraph_gap_ms`).
- Mỗi dòng được cắt lặng hai đầu và chuẩn hoá về cùng mức âm lượng (RMS 0.12, đỉnh ≤ 0.95); MP3 của edge được decode và resample lên 48 kHz.
- Dòng VieNeu chạy tuần tự, dòng edge chạy song song tối đa 4 (edge-tts lỗi "No audio received" được thử lại).
- Cache từng dòng trong `data/cache/<hash>.wav`; khoá gồm engine, giọng, lời, tốc độ, mode, và (giọng mix) variant + alpha. Sửa một dòng thì chỉ dòng đó được sinh lại.
- Sinh lại một dòng bỏ qua cache và tạo take mới (VieNeu tái lập được bằng `seed`); take mới thay take cũ trong cache.
- Giới hạn: 300 dòng và `TTS_MAX_CHARS` ký tự mỗi kịch bản. Job nằm trong bộ nhớ và bị dọn sau 1 giờ.

## Chuẩn hoá văn bản

VieNeu (sea-g2p) đã tự đọc đúng ngày giờ, %, số thập phân, tiền VNĐ/€, đơn vị (km, kg, MB, °C…), số điện thoại, viết tắt (TP.HCM, UBND, v.v.).
`text_normalize.py` chỉ bù các trường hợp sea-g2p đọc sai (tìm bằng `scripts/normalize_probe.py`): `50k` → "năm mươi nghìn",
`1.5 triệu` → "một phẩy năm triệu", `TP. Hồ Chí Minh` (dư dấu chấm), `km²`/`m³` → "mét vuông"/"mét khối", `$100`/`100$`/`USD` → "đô la".
Bật/tắt bằng ô "Chuẩn hoá văn bản" (mặc định bật; chỉ áp dụng cho VieNeu).

## Sách nói (nhập, tách chương, làm sạch, từ điển, giọng lời thoại)

Tab **Sách nói** nhập truyện dài, tách chương, làm sạch văn bản. Mỗi truyện nằm trong `data/books/<id>/` (`book.json`, `source/` giữ file gốc, `chapters/<nnnn>.txt` + `.json`). Sau khi tách chương: nghe thử (▶, "Đọc thử 1 phút"), tạo audio hàng loạt bằng hàng đợi nền và xuất MP3 / m4b (xem "Tạo audio hàng loạt" bên dưới).

- **Nhập:** `.txt` (tự dò UTF-8 / UTF-16 / GB18030 / Windows-1258) và `.epub` (đọc bằng thư viện chuẩn `zipfile` + `xml.etree`, không thêm phụ thuộc). Nhiều file `.txt` thì mỗi file một chương, sắp theo số trong tên.
- **Tách chương:** regex mặc định nhận `Chương 12`, `Chương 12:`, `Chương XII`, `第12章`, `Quyển 2 Chương 5` (sửa được). Có màn hình xem trước (số chương, tiêu đề, số ký tự); gộp với chương sau hoặc tách tại dòng chứa một đoạn văn bản. Chỉ khi bấm "Xác nhận" mới ghi `chapters/`.
- **Làm sạch** (bật/tắt từng quy tắc, lưu theo truyện): bỏ ký tự điều khiển, chuẩn hoá ngoặc kép và dấu ba chấm, bỏ dòng URL, dòng "nguồn:" / "truyện được dịch bởi", dòng trùng, gộp dòng bị ngắt giữa câu; dòng chỉ gồm dấu ngăn cảnh (`***`, `* * *`, `---`, `~~~`, `ooo`, `♦`…) thành `[nghỉ 1.5s]` (chỉnh số giây trong cài đặt). Thêm được quy tắc tuỳ chỉnh regex → thay thế.
- **Tiêu đề chương** được đọc ở đầu mỗi chương (tắt được trong cài đặt truyện).
- **Tác động từng quy tắc:** màn xem trước hiện số dòng bị ảnh hưởng của mỗi quy tắc; nút "Xem" liệt kê tối đa 50 dòng (bị xoá: nội dung gốc + chương; bị gộp: 2 dòng trước và 1 dòng sau). "Giữ dòng này" thêm `{rule, line}` vào `exceptions` của truyện, quy tắc đó không áp dụng cho dòng ấy nữa (xem trước tính lại ngay, lưu khi bấm "Xác nhận" hoặc "Lưu cài đặt"). Ngoại lệ khớp theo nội dung dòng (đã `strip`), không theo vị trí.
- **Từ điển phát âm** (`lexicon.py`; toàn cục `data/lexicon.json` + riêng từng truyện, truyện ưu tiên): mỗi mục `{match, replace, pause_before, pause_after, whole_word, case_sensitive}`. "Đọc thành" thay chữ; "nghỉ trước/sau" chèn `[nghỉ Ns]` quanh cụm. Áp dụng một lượt, TRƯỚC chuẩn hoá. Gạch nối (`Đấu-Khí`) không có tác dụng với VieNeu (sea-g2p đổi gạch nối thành khoảng trắng, audio giống hệt); xem `scripts/lexicon_probe.py`.
- **Gợi ý tên riêng:** cụm viết hoa 2–4 tiếng KHÔNG đứng đầu câu (sau `. ! ? : …`, dấu ngoặc kép, gạch thoại, đầu dòng), lặp ≥ N lần. Từ dừng (Anh, Hắn, Nhưng…) nằm trong `config/name_stopwords.txt`, sửa được, không cần khởi động lại. Có câu ví dụ, "Nghe thử" và "Thêm vào từ điển". Tiếng đơn (vd. `Viêm`) chỉ được gợi ý nếu là thành phần của một cụm đã gợi ý (`Tiêu Viêm`) và đứng riêng, không ở đầu câu, ≥ 5 lần; hiện thụt vào dưới cụm cha.
- **Giọng thứ hai cho lời thoại** (`narrate.py`, tuỳ chọn trong cài đặt truyện): nhận (a) đoạn trong ngoặc kép `“…”` / `"…"` và (b) dòng bắt đầu bằng gạch thoại `–`, `—` hoặc `- `. Với (b), phần dẫn (`– Đi đâu? – hắn hỏi.`) về giọng kể; phần dẫn được nhận ra nhờ chữ thường sau gạch, hoặc nếu viết hoa thì phải ngắn (≤ 60 ký tự) và có một động từ nói trong 4 tiếng đầu (`config/speech_verbs.txt`: hỏi, nói, đáp, quát, cười, thì thầm…), nên `– Đi đâu? – Hắn hỏi.` tách đúng nhưng `– Em yêu anh. – Anh cười với em.` bị coi là phần dẫn (có động từ "cười") dù là câu thoại. Ngoặc kép bao một thuật ngữ ngắn không dấu câu (`"Đấu Khí"`) vẫn do giọng kể đọc.
- **Đọc thử 1 phút:** nút ở mỗi chương (đầu chương hoặc giữa chương), ~900 ký tự, dùng giọng + từ điển + giọng lời thoại hiện tại. Chạy qua hàng đợi với ưu tiên cao nhất (chen vào giữa hai mảnh của chương đang tạo), có thanh tiến độ. ▶ (~300 ký tự) vẫn chạy ngay.

### Tạo audio hàng loạt (hàng đợi nền)

Nút **Chạy tất cả**, **Chạy thử 5 chương đầu**, **Chạy khoảng** và **Tạo**/**Tạo lại** từng chương xếp chương vào hàng đợi (`data/queue.json`). Một worker nền chạy lần lượt từng chương:

- **Đơn vị:** chương → đoạn ≤ `BOOK_SEGMENT_CHARS` (800 ký tự) → mảnh ≤ 256 ký tự mỗi lần gọi model (VieNeu tự chia chunk ở 256). Đoạn chỉ cắt ở ranh giới đoạn văn (xuống dòng); một đoạn văn dài hơn giới hạn mới bị cắt, ở ranh giới câu.
- **Khoảng nghỉ:** giữa hai đoạn văn `paragraph_pause_s` (mặc định 0,6 giây) và sau tiêu đề chương `title_pause_s` (1,2 giây), chỉnh trong cài đặt truyện (0 = không nghỉ). Áp dụng cả ở mối nối giữa hai đoạn cắt, không áp dụng giữa hai mảnh của một đoạn văn dài bị cắt. Dòng dấu ngăn cảnh (`[nghỉ 1.5s]`) thay khoảng nghỉ đoạn văn chứ không cộng thêm. `scripts/measure_pauses.py` đo khoảng lặng thật ở từng chỗ. Mỗi đoạn dựng xong được ghi ngay vào `audio/<nnnn>.parts/`; chương xong thì ghép thành `audio/<nnnn>.flac` (lossless 48 kHz mono, nguồn cho MP3/m4b) và xoá `.parts`. Đổi giọng / tốc độ / từ điển / chuẩn hoá / đọc tiêu đề / các mức nghỉ / precision thì đoạn cũ không còn khớp (hash) và chương đã xong bị đánh dấu "cài đặt đã đổi, nên tạo lại".
- **Bền:** tắt server hoặc server chết (kể cả `kill -9`), khởi động lại sẽ tự chạy tiếp; chỉ đoạn đang chạy dở được dựng lại. **Tạm dừng** và **Huỷ** chỉ có hiệu lực ở ranh giới đoạn (đoạn đang chạy được dựng xong, không cắt giữa chừng). Ctrl+C chờ nốt mảnh đang chạy (vài giây) rồi dừng sạch.
- **Ưu tiên:** "Đọc thử" > request tương tác (▶, tab Đọc…) > chương trong hàng đợi. Khoá model dùng chung: việc tương tác chờ tối đa một mảnh (~10 giây), không phải chờ cả đoạn. Mở / nghe / xem một chương đang chờ thì chương đó lên đầu hàng.
- **Ước tính:** "Ước tính: X giờ cho N chương còn lại" dùng tốc độ đo thực tế của các đoạn vừa chạy; chưa có thì dùng số đo của `scripts/bench_vieneu.py` (precision đang dùng); chưa có cả hai thì báo chưa đo.
- **Chống ngủ máy (Linux):** khi worker đang chạy, giữ `systemd-inhibit --what=sleep:idle` bằng một tiến trình con tự thoát khi server chết. Không có `systemd-inhibit` thì bỏ qua (ghi log). Có ô tick để tắt.
- **Thông báo khi xong:** Notification API của trình duyệt (xin quyền khi bấm Chạy; tab phải còn mở) và `notify-send` nếu máy có.
- **3 chương lỗi liên tiếp** thì hàng đợi tự tạm dừng (kèm thông báo) để không chạy hết cả truyện trong lỗi.
- **Dung lượng:** mỗi truyện hiện dung lượng đã dùng (danh sách và bảng chương: audio gốc, file xuất, nguồn + văn bản). FLAC gốc khoảng 33 KB/giây audio (~120 MB/giờ). Nút **Xoá nguồn FLAC của chương đã xuất** (có xác nhận) xoá FLAC của các chương đã xuất MP3 hoặc m4b ít nhất một lần; chương chuyển sang "đã xuất": không nghe lại / xuất lại được cho tới khi **Tạo lại**. File zip / m4b đã xuất không bị xoá.
- **Xuất:** MP3 từng chương (mono 64 / 80 / 96 kbps, ID3: tên chương, số thứ tự, album, tác giả) đóng zip, hoặc một file `.m4b` (AAC 64 kbps) có đánh dấu chương. Chỉ xuất chương đã xong. File nằm trong `data/books/<id>/export/`.
- API: `GET /api/queue[?book=]`, `POST /api/books/{id}/queue/run` (`chapters`, `limit`, `regenerate`, `stale_only`), `POST /api/books/{id}/queue/focus`, `POST /api/queue/{pause,resume,cancel,settings}`, `POST /api/books/{id}/chapters/{n}/trial` + `GET /api/trials/{id}[/audio]`, `GET …/chapters/{n}/audio.mp3`, `POST /api/books/{id}/export` + `GET /api/exports/{id}` + `GET /api/books/{id}/export/{file}`, `GET /api/books/{id}/disk`, `POST /api/books/{id}/audio/purge-exported`.
- API: `GET/POST /api/books`, `POST /api/books/import`, `GET/PATCH/DELETE /api/books/{id}`, `POST …/preview`, `POST …/chapters` (xác nhận), `GET …/chapters[/{n}[/sample?use_lexicon=]]`, `POST …/speak`, `POST …/lexicon/apply`, `GET …/suggest`, `GET/PUT /api/lexicon`. `preview`/`chapters` nhận thêm `exceptions`; `PATCH` nhận `exceptions`, `lexicon`, `dialogue_voice`.

## Kiểm tra nhanh

```bash
scripts/smoke_test.sh            # khởi động server với data tạm, chạy các luồng chính, in PASS/FAIL, tự dọn
SKIP_EDGE=1 scripts/smoke_test.sh   # bỏ các bước cần mạng
```
`scripts/smoke_books.py` (do `smoke_test.sh` gọi) kiểm riêng phần sách nói; `scripts/smoke_queue.py` (cũng do `smoke_test.sh` gọi, `SKIP_QUEUE=1` để bỏ, ~3 phút) tự chạy server riêng để `kill -9` / SIGINT giữa chừng, khởi động lại và xuất MP3 + m4b. `scripts/bench_vieneu.py` đo tốc độ fp32 và int8. `scripts/measure_pauses.py` đo khoảng lặng xuống đoạn / sau tiêu đề trong audio chương thật (chạy VieNeu ~45 giây; cũng nằm trong bước hàng đợi của `smoke_test.sh`). `scripts/perf_books.py` đo hiệu năng với truyện giả 20 MB / 1.500 chương.

## Thêm engine mới

Tạo `engines/<ten>.py` chứa lớp kế thừa `engines.base.Engine`, rồi thêm một dòng `"engines.<ten>:<Lop>"` vào `PLUGINS` trong `engines/registry.py`.
Engine chưa cài vẫn hiện trên UI với nhãn "chưa cài"; plugin lỗi khi import bị bỏ qua.

## Lỗi thường gặp

- **`pip install` báo `externally-managed-environment`** (Debian/Ubuntu, Python do hệ điều hành quản lý): dùng venv như ở mục Cài đặt
  (`python3 -m venv .venv && source .venv/bin/activate`), đừng dùng `--break-system-packages`. Thiếu module venv: `sudo apt install python3-venv`.
- **VieNeu báo `External data path escapes model directory`:** cache Hugging Face lưu file model bằng symlink mà onnxruntime từ chối.
  Server tự thay symlink bằng bản sao thật rồi nạp lại (tốn thêm khoảng 1 GB ổ đĩa).
- **edge-tts báo `No audio was received`:** dịch vụ Microsoft thỉnh thoảng từ chối một câu hoặc một tổ hợp tham số rồi lại nhận ở lần sau.
  Server tự thử lại tối đa 2 lần; tổ hợp tốc độ + cao độ bị từ chối thì đọc lại không cao độ. Vẫn lỗi: kiểm tra mạng hoặc thử câu ngắn hơn.
- **Giọng trộn bị mờ "tạo ở mode …":** đặt lại `VIENEU_MODE` như lúc tạo giọng đó.

## Giấy phép

- **VieNeu-TTS:** Apache 2.0.
- **edge-tts** (thư viện LGPLv3) gọi API đọc văn bản của Microsoft Edge, là **API không chính thức**: có thể ngừng hoạt động hoặc đổi điều khoản bất cứ lúc nào; dùng cho mục đích cá nhân, không nên phụ thuộc vào nó cho sản phẩm thương mại.
