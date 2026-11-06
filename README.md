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
| `VIENEU_PRECISION` | | `int8` chạy nhanh hơn trên CPU có VNNI, chất lượng giảm nhẹ |

## Dữ liệu trong `data/`

`voices/<id>/` (giọng nhân bản và giọng trộn), `favorites.json`, `history/` (50 bản gần nhất), `projects/`, `cache/`.
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

## Sách nói (Phase 6a: nhập, tách chương, làm sạch)

Tab **Sách nói** nhập truyện dài, tách chương, làm sạch văn bản. Mỗi truyện nằm trong `data/books/<id>/` (`book.json`, `source/` giữ file gốc, `chapters/<nnnn>.txt` + `.json`). Tạo audio hàng loạt và xuất file là phần sau; hiện ▶ chỉ nghe thử ~300 ký tự đầu chương.

- **Nhập:** `.txt` (tự dò UTF-8 / UTF-16 / GB18030 / Windows-1258) và `.epub` (đọc bằng thư viện chuẩn `zipfile` + `xml.etree`, không thêm phụ thuộc). Nhiều file `.txt` thì mỗi file một chương, sắp theo số trong tên.
- **Tách chương:** regex mặc định nhận `Chương 12`, `Chương 12:`, `Chương XII`, `第12章`, `Quyển 2 Chương 5` (sửa được). Có màn hình xem trước (số chương, tiêu đề, số ký tự); gộp với chương sau hoặc tách tại dòng chứa một đoạn văn bản. Chỉ khi bấm "Xác nhận" mới ghi `chapters/`.
- **Làm sạch** (bật/tắt từng quy tắc, lưu theo truyện): bỏ ký tự điều khiển, chuẩn hoá ngoặc kép và dấu ba chấm, bỏ dòng URL, dòng "nguồn:" / "truyện được dịch bởi", dòng trùng, gộp dòng bị ngắt giữa câu; dòng chỉ gồm dấu ngăn cảnh (`***`, `* * *`, `---`, `~~~`, `ooo`, `♦`…) thành `[nghỉ 1.5s]` (chỉnh số giây trong cài đặt). Thêm được quy tắc tuỳ chỉnh regex → thay thế.
- **Tiêu đề chương** được đọc ở đầu mỗi chương (tắt được trong cài đặt truyện).
- API: `GET/POST /api/books`, `POST /api/books/import`, `GET/PATCH/DELETE /api/books/{id}`, `POST …/preview`, `POST …/chapters` (xác nhận), `GET …/chapters[/{n}[/sample]]`.

## Kiểm tra nhanh

```bash
scripts/smoke_test.sh            # khởi động server với data tạm, chạy các luồng chính, in PASS/FAIL, tự dọn
SKIP_EDGE=1 scripts/smoke_test.sh   # bỏ các bước cần mạng
```
`scripts/smoke_books.py` (do `smoke_test.sh` gọi) kiểm riêng phần sách nói.

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
