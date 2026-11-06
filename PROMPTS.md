# Prompt bundle: nâng cấp "Giọng Việt" lên kiểu ElevenLabs

Dán **từng phase** cho coding agent theo thứ tự.
Mỗi phase kết thúc bằng một **STOP & REPORT**: agent dừng lại, bạn đọc báo cáo,
rồi mới dán phase tiếp theo.

---

## PROMPT 0: Bối cảnh (dán đầu tiên, kèm Phase 1)

```
Bạn đang làm việc trên repo "tts-tool". Đây là web tool text-to-speech tiếng Việt, gồm:
- server.py: FastAPI; 2 engine là edge-tts (online, MP3) và VieNeu-TTS (offline, ONNX/CPU, WAV 48 kHz)
- static/index.html: UI viết bằng vanilla JS, không có build step
- Chạy bằng `python server.py`, mở http://localhost:8000
- Môi trường: Linux, Python 3.14, venv ở .venv/ (luôn dùng `.venv/bin/python -m pip`)

Mục tiêu dài hạn: có các tính năng giống ElevenLabs
(thư viện giọng, trộn giọng, hội thoại nhiều người, nút chèn cảm xúc).
Ta sẽ làm theo từng phase.

Quy tắc chung (áp dụng cho MỌI phase):
1. KHÔNG đoán API của thư viện. Trước khi gọi vieneu, v_tts hay edge_tts, hãy đọc source
   trong .venv/lib/python3.14/site-packages/<pkg>/ để xác nhận chữ ký hàm và kiểu trả về.
2. Không phá API hiện có: GET /api/engines, GET /api/voices/{engine}, POST /api/tts
   phải giữ nguyên hành vi.
3. Giữ UI là một file HTML với vanilla JS, không thêm framework hay bundler.
   Chữ hiển thị trên UI viết bằng tiếng Việt.
4. Model nặng phải lazy-load và có threading.Lock như VieNeuEngine hiện tại.
   Engine nào chưa cài thì UI hiển thị "chưa cài" thay vì crash.
5. Mỗi phase phải kiểm tra bằng curl (và mở UI nếu có thể) trước khi báo cáo.
6. Kết thúc phase: DỪNG lại và báo cáo theo mẫu:
   - Đã làm gì (danh sách file thay đổi)
   - Cách test, kèm lệnh curl và kết quả thực tế
   - Những gì CHƯA chắc chắn hoặc phải giả định
   - Đề xuất điều chỉnh cho phase sau (nếu có)
   Không tự động làm sang phase tiếp theo.
```

---

## PHASE 1: Tách engine thành plugin

```
PHASE 1: Refactor engine thành kiến trúc plugin, để dễ thêm engine mới.

Việc cần làm:
1. Tạo package engines/ gồm:
   - base.py: abstract class Engine với các thành phần:
     id, label, description,
     installed() -> bool,
     voices() -> list[{id, label, gender?, region?}],
     synthesize(text, voice, speed, **opts) -> (bytes, mime),
     capabilities() -> {"clone": bool, "pitch": bool, "emotion_tags": list[str], "mix": bool}
   - edge.py: chuyển logic edge-tts từ server.py sang đây (bản async)
   - vieneu.py: chuyển VieNeuEngine sang đây
   - registry.py: dict các engine, tự bỏ qua engine chưa cài
2. server.py chỉ còn routing, gọi engine qua registry.
3. GET /api/engines trả thêm capabilities của từng engine.
4. UI đọc capabilities để tự ẩn/hiện các phần: cao độ, nhân bản, thẻ cảm xúc.
   Không hard-code theo tên engine nữa.

Tiêu chí xong:
- Mọi chức năng cũ chạy y như trước.
- Thêm một engine mới chỉ cần thêm 1 file và 1 dòng trong registry.

STOP & REPORT.
```

---

## PHASE 2: Thư viện giọng (Voice Library)

```
PHASE 2: Thư viện giọng, giống Voice Library của ElevenLabs.

Lưu trữ:
- Thư mục data/voices/<voice_id>/ chứa: ref.wav (audio mẫu đã chuẩn hoá) và meta.json
- meta.json gồm: id (slug), name, engine, tags[], gender, region ("bac"|"trung"|"nam"|""),
  description, created_at, source ("clone"|"mix"|"preset_alias"),
  consent (bool, bắt buộc true)
- data/ thêm vào .gitignore

API:
- GET    /api/library                 → danh sách giọng (lọc theo ?engine=&tag=&gender=)
- POST   /api/library                 → form: name, engine, tags, gender, region, description,
                                        ref_audio (file), consent=true
                                        → tiền xử lý (denoise/trim nếu engine hỗ trợ) rồi lưu
- PATCH  /api/library/{id}            → sửa metadata
- DELETE /api/library/{id}
- GET    /api/library/{id}/preview    → sinh và cache 1 câu mẫu cố định
                                        ("Xin chào, đây là giọng đọc thử.") trong data/voices/<id>/preview.wav
- Giọng trong thư viện xuất hiện trong /api/voices/{engine} với id dạng "lib:<voice_id>".
  synthesize() phải nhận ra id này và dùng ref.wav.
- Với VieNeu: kiểm tra xem add_voice/save_voices có dùng lại được để khỏi encode lại
  mỗi lần không. Nếu dùng được thì cache; nếu không thì giải thích lý do trong report.

UI:
- Thêm tab "Thư viện giọng" bên cạnh tab "Đọc văn bản".
- Lưới card: tên, tags, nút ▶ nghe thử, nút "Dùng giọng này", nút sửa, nút xoá.
  Có ô tìm kiếm và bộ lọc giới tính / vùng miền.
- Form "Thêm giọng": upload hoặc kéo thả audio 3–10 giây, hiện thời lượng,
  báo lỗi nếu ngắn hơn 3 giây hoặc dài hơn 30 giây.
  Bắt buộc tick checkbox: "Tôi là chủ giọng nói này hoặc đã được người đó đồng ý".
- Ghi âm trực tiếp bằng micro (MediaRecorder) nếu làm được. Nếu engine không đọc được
  webm/ogg thì server phải convert sang wav: thử soundfile/librosa trước,
  ffmpeg chỉ là fallback tuỳ chọn.

STOP & REPORT.
```

---

## PHASE 3: Engine V-TTS + trộn giọng (Voice Mixing)

```
PHASE 3: Thêm engine V-TTS và tính năng trộn giọng.

1. Engine engines/vtts.py dùng V-TTS (https://github.com/tronghieuit/valtec-tts):
   - Đọc README và source của package để xác định: tên package pip, class multi-speaker,
     class ZeroShotTTS, cách liệt kê speaker, cách lấy speaker embedding, sample rate.
   - Nếu package không cài được bằng pip trên Python 3.14 thì DỪNG và báo cáo,
     kèm phương án thay thế. Không tự cài bừa.
   - capabilities: clone=true, mix=true.
   - Giọng trong thư viện có engine="vtts" chạy qua engine này.

2. Trộn giọng (mix):
   - API: POST /api/mix  → form: engine, voice_a, voice_b, alpha (0..1), text
                         → trả audio preview
   - API: POST /api/mix/save → lưu kết quả trộn vào thư viện, source="mix".
     Lưu embedding đã trộn dạng .npy cùng alpha, voice_a, voice_b trong meta.
   - Cách trộn: spk = alpha*emb_a + (1-alpha)*emb_b, sau đó normalize nếu model yêu cầu
     (kiểm tra trong source).
   - Kiểm tra xem VieNeu có cho truyền speaker embedding trực tiếp không:
     infer(voice=dict) nhận gì? Xem _resolve_ref trong vieneu/v3turbo.py.
     Nếu có thì bật mix cho VieNeu luôn. Nếu không thì ghi rõ trong report.

3. UI: thêm tab "Tạo giọng mới" gồm:
   - Chọn engine, chọn giọng A và giọng B (gồm cả preset lẫn giọng trong thư viện)
   - Thanh trượt A ↔ B, nút "Nghe thử", nút "Lưu vào thư viện" (nhập tên, tags)

STOP & REPORT.
```

---

## PHASE 4: Hội thoại nhiều người (Studio)

```
PHASE 4: Chế độ "Hội thoại", giống Studio/Projects của ElevenLabs.

Định dạng kịch bản:
    [Lan]: Chào anh, hôm nay anh khoẻ không?
    [Minh]: Anh khoẻ, cảm ơn em [cười].
    (dòng trống = nghỉ dài hơn)
- Dòng không có [Tên]: thì thuộc về người nói ở dòng trước.

Backend:
- POST /api/dialogue/parse  → trả danh sách speaker và các dòng đã tách
- POST /api/dialogue        → JSON: {script, cast: {"Lan": {engine, voice}, ...},
                               speed, gap_ms (mặc định 350), paragraph_gap_ms (mặc định 800)}
  - Sinh audio từng dòng, resample tất cả về cùng một sample rate
    (edge-tts trả MP3 thì phải decode), chèn khoảng lặng, ghép lại.
  - Xuất WAV. Nếu máy có ffmpeg thì xuất thêm MP3.
  - Cache audio từng dòng theo hash(engine, voice, text, speed) trong data/cache/,
    để sửa 1 dòng thì không phải sinh lại cả bài.
- Văn bản dài: tiến độ trả qua Server-Sent Events (GET /api/dialogue/{job_id}/events),
  hoặc polling nếu SSE phức tạp. Ghi rõ đã chọn cách nào.

UI: tab "Hội thoại" gồm:
- Bên trái là ô soạn kịch bản. Bên phải là bảng "Diễn viên", tự hiện ra theo tên đã parse,
  mỗi tên có dropdown chọn giọng (preset hoặc thư viện).
- Nút "Tạo audio" kèm thanh tiến độ. Kết quả gồm audio tổng và danh sách từng dòng,
  mỗi dòng có nút ▶ và nút 🔄 sinh lại riêng dòng đó.
- Lưu và mở project dạng JSON (kịch bản + cast) vào data/projects/.

STOP & REPORT.
```

---

## PHASE 5: Cảm xúc, hoàn thiện, tài liệu

```
PHASE 5: Hoàn thiện.

1. Thanh công cụ trên ô văn bản, hiện theo capabilities.emotion_tags của engine đang chọn:
   các nút chèn [cười], [thở dài], [hắng giọng] tại vị trí con trỏ.
   Thêm nút chèn quãng nghỉ (cắt câu hoặc thêm dấu "…").
2. Chuẩn hoá văn bản trước khi gửi engine (tuỳ chọn bật/tắt):
   số → chữ, ngày tháng, đơn vị (km, kg, %), viết tắt phổ biến (TP.HCM, v.v.).
   Kiểm tra xem VieNeu và V-TTS đã tự chuẩn hoá chưa, để không làm 2 lần.
3. Lịch sử: lưu 50 bản gần nhất trong data/history/ (audio + meta).
   UI có nút "tải lại" và "xoá tất cả".
4. README.md: cập nhật cài đặt từng engine, bảng tính năng theo engine,
   ghi chú về giấy phép (VieNeu là Apache 2.0; V-TTS phải kiểm tra license
   trong repo và ghi đúng) và về sự đồng ý của chủ giọng khi nhân bản.
5. Chạy lại toàn bộ luồng chính, báo cáo các lỗi còn tồn đọng.

STOP & REPORT (báo cáo cuối).
```
