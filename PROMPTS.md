# Prompt bundle: bảng chọn thẻ kiểu ElevenLabs + hiệu ứng âm thanh

Dán **từng phase** cho coding agent theo thứ tự. Mỗi phase kết thúc bằng **STOP & REPORT**:
agent dừng lại, bạn đọc báo cáo rồi mới dán phase tiếp theo.

> **Đường tắt:** nếu đã có file `0001-feat-tag-picker-like-ElevenLabs-sound-effect-tags.patch`, chạy
> `git am <file>` rồi chỉ dán PROMPT 0 + PHASE T-4 (rà soát và kiểm thử trên máy thật).

---

## PROMPT 0: Bối cảnh (dán đầu tiên, kèm Phase T-1)

```
Bạn đang làm việc trên repo "tts-tool" (Giọng Việt). Đây là tool text-to-speech tiếng Việt:
- server.py: FastAPI. Engine nằm trong engines/ (edge.py: online, MP3; vieneu.py: offline,
  ONNX/CPU, WAV). Thêm engine mới: một file + một dòng trong registry.py.
- dialogue.py: pipeline chung "cắt văn bản theo thẻ → đọc từng đoạn → ghép". make_plan() trả
  [("text", ...), ("pause", giây)], render_plan() ghép audio 48 kHz mono, plan_key() làm khoá cache.
- text_normalize.py: PAUSE_RE, has_pause(), split_pauses() cho thẻ [nghỉ Ns].
- narrate.py: sách nói. units() đổi văn bản thành các Unit "text" / "silence";
  render_unit() dựng từng Unit. bookq.py gọi hai hàm này.
- static/: HTML + CSS + ES module thuần, không có build. Màu chỉ lấy từ css/tokens.css.
  Helper: dom.js (h), api.js (getJSON, sendForm, api), ui.js (modal, toast, confirmBox,
  showError), player.js (play). Màn "Đọc văn bản" là static/js/views/read.js.
- Chạy: `.venv/bin/python server.py`, mở http://localhost:8000. Python 3.14, luôn dùng
  `.venv/bin/python -m pip`.

Mục tiêu: chèn thẻ giống ElevenLabs v3. Model của ta (edge, VieNeu) KHÔNG tự tạo được tiếng
mưa, tiếng gõ cửa… nên thẻ hiệu ứng âm thanh phải chạy bằng cách ghép file âm thanh vào đúng
chỗ, đi qua đúng pipeline đang dùng cho thẻ [nghỉ Ns].

Quy tắc chung (áp dụng cho MỌI phase):
1. Đọc code hiện có trước khi sửa: dialogue.make_plan / render_plan / plan_key,
   narrate.units / render_unit, text_normalize.split_pauses, server.py đoạn `pausey`.
   Không đoán chữ ký hàm.
2. Không phá hành vi hiện có: thẻ [nghỉ Ns], thẻ cảm xúc [cười] [thở dài] [hắng giọng],
   cache dòng hội thoại, cache sách nói. Văn bản không có thẻ mới phải cho ra đúng khoá cache cũ.
3. Không thêm dependency mới. numpy, scipy (đi kèm librosa), soundfile, soxr đã có.
4. Chữ trên giao diện là tiếng Việt, lời thường. Lỗi phải nói cách khắc phục.
5. Kiểm tra bằng curl và bằng script Python có engine giả (không cần mạng, không cần VieNeu)
   trước khi báo cáo.
6. Chạy `ruff check` cho các file đã sửa. Không thêm lỗi mới so với trước.
7. Kết thúc phase: DỪNG lại và báo cáo theo mẫu:
   - Đã làm gì (danh sách file thay đổi)
   - Cách test, kèm lệnh và kết quả thực tế
   - Những gì CHƯA chắc chắn hoặc phải giả định
   - Đề xuất điều chỉnh cho phase sau (nếu có)
   Không tự động làm sang phase tiếp theo.
```

---

## PHASE T-1: Thư viện hiệu ứng âm thanh (sfx.py)

```
PHASE T-1: tạo module sfx.py, chưa nối vào pipeline.

1. Âm có sẵn: sinh bằng numpy/scipy, KHÔNG tải file từ mạng. Sinh một lần, cache ở
   data/sfx/builtin/<id>-v<VERSION>.wav. Hằng VERSION: đổi công thức thì tăng để bỏ cache cũ.
   Seed cố định theo id, để lần nào sinh ra cũng giống nhau.
   Danh sách (id, thẻ, mô tả, bí danh tiếng Anh của ElevenLabs):
   - mua        [tiếng mưa]      Mưa rơi đều            rain falling, rain
   - sam        [tiếng sấm]      Sấm rền                thunder
   - gio        [tiếng gió]      Gió thổi               wind
   - tim-dap    [tim đập]        Tim đập thình thịch    heartbeat
   - go-cua     [gõ cửa]         Cốc cốc cốc            knocking on door
   - chuong     [chuông ngân]    Một tiếng chuông       bell ringing
   - chieng     [tiếng chiêng]   Chiêng / cồng          gong
   - dien-thoai [điện thoại reo] Hai hồi chuông         phone ringing
   - trong-don  [trống dồn]      Trống dồn rồi chũm chọe drum roll
   - ban-phim   [gõ phím]        Gõ bàn phím            keyboard typing
   - vo-tay     [vỗ tay]         Tràng vỗ tay           applause
   - buoc-chan  [bước chân]      Bốn bước chân          footsteps
   - kiem       [tiếng kiếm]     Kiếm chạm nhau: keng   sword clash
   - no-may     [nổ máy]         Đề máy rồi nổ máy      engine starting
   Mỗi âm dài 1–5 giây. Gợi ý cách tổng hợp: noise qua bộ lọc (mưa, gió, vỗ tay), cộng các
   partial sin tắt dần (chuông, chiêng, kiếm), xung lặp lại (gõ cửa, tim, bước chân, trống).
2. Chuẩn hoá mọi âm (có sẵn và của người dùng): mono float32 48 kHz, cắt lặng hai đầu
   (librosa.effects.trim top_db≈45), tối đa 15 giây (cắt có fade), RMS phần có tiếng ≈ 0.08
   (nhỏ hơn giọng đọc, dialogue.TARGET_RMS = 0.12), peak ≤ 0.9, fade in 4 ms, fade out 30 ms.
3. Âm của người dùng: add(name, bytes, reserved) và delete(id).
   - Lưu ở data/sfx/user/<id>.wav, danh sách ở data/sfx/user.json (ghi qua file .tmp rồi
     replace, có threading.Lock).
   - id = "u-<slug>-<6 hex ngẫu nhiên>", để xoá rồi thêm lại cùng tên không dính cache cũ.
   - Kiểm tra tên: 1–30 ký tự; không có [ ] : hay xuống dòng; không bắt đầu bằng "nghỉ";
     không trùng thẻ hoặc bí danh đã có, kể cả thẻ cảm xúc của mọi engine (truyền qua reserved).
   - Giải mã bằng library.decode_audio (có fallback ffmpeg).
4. Tra cứu:
   - catalog() → [{id, tag, label, description, aliases, source: "builtin"|"user", seconds?}]
   - split(text) → [("text", ...), ("sfx", id), ...]
   - has_sfx(text), find(tag), path_of(id), key(id) (phần khoá cache), audio(id)
     (đã kèm 0.1 s lặng hai đầu).
   - So khớp thẻ: không phân biệt hoa thường, khoảng trắng trong thẻ co giãn,
     NFC unicode, thẻ dài khớp trước.
   - Regex dựng từ catalog và cache lại; dựng lại sau mỗi lần add/delete.
   - path_of chỉ nhận id có sẵn hoặc khớp ^u-[a-z0-9-]+$ (chặn path traversal).

Test: script sinh đủ 14 âm (không NaN, độ dài hợp lý, in thời gian sinh); kiểm tra
split("Trời tối. [Tiếng  sấm] Hắn [rain falling][nghỉ 1s] đi [witch voice]") tách đúng, và
[witch voice] vẫn là chữ. Báo cáo kèm ảnh spectrogram 14 âm nếu có matplotlib.
STOP & REPORT.
```

---

## PHASE T-2: Nối vào pipeline và API

```
PHASE T-2: thẻ hiệu ứng chạy được ở Đọc văn bản, Nhiều người đọc và Làm sách nói.

1. text_normalize:
   - has_pause() trả True khi có thẻ nghỉ HOẶC thẻ hiệu ứng (để server.py đi đường `pausey`).
   - split_pauses() tách tiếp từng đoạn chữ bằng sfx.split → có thêm phần tử ("sfx", id).
   - Import sfx bên trong hàm để tránh import vòng.
2. dialogue:
   - make_plan giữ nguyên phần tử "sfx".
   - plan_key mã hoá "sfx" thành "[sfx <sfx.key(id)>]".
   - render_plan chèn sfx.audio(id) (chạy qua anyio.to_thread).
   - Phần trừ SEGMENT_PAD_S của thẻ nghỉ chỉ tính đoạn "text" kề bên, giữ nguyên.
3. narrate:
   - units() sinh Unit("sfx", text=id).
   - render_unit() dựng sfx.audio.
   - Kiểm tra bookq.py không có chỗ nào giả định Unit chỉ là "text" hoặc "silence".
4. server.py:
   - GET    /api/sfx               → sfx.catalog()
   - GET    /api/sfx/{id}/audio    → FileResponse wav (404 khi không có)
   - POST   /api/sfx  (form: name, file) → 400 kèm lời dễ hiểu khi tên trùng hoặc file hỏng.
     reserved = mọi emotion_tags của các engine. Dùng read_upload sẵn có.
   - DELETE /api/sfx/{id}
5. Thẻ engine không hiểu (vd [witch voice]) vẫn đi đường cũ. Không âm thầm xoá.

Test bằng engine giả (class có id, local, name, capabilities(), cache_tag(),
synthesize() trả wav sin 0.5 s):
- dialogue.render_text với "Trời tối sầm. [tiếng sấm] Có tiếng [knocking on door] ngoài cửa."
- narrate.units / narrate.render với "[rain falling]"
- dialogue.parse_script có thẻ hiệu ứng
- curl đủ 4 endpoint, gồm cả: tên trùng [tiếng mưa], tên trùng [cười], id có "../"
- Văn bản KHÔNG có thẻ mới: plan_key và line_key giống hệt trước khi sửa (so bằng git stash).
STOP & REPORT.
```

---

## PHASE T-3: Bảng chọn thẻ (giao diện)

```
PHASE T-3: thay khối "Thêm cảm xúc, chỗ nghỉ" trong read.js bằng bảng chọn thẻ kiểu ElevenLabs.

1. Module mới static/js/tagpicker.js, export tagPicker({ textarea, emotionTags, multi }) → Node.
2. Nút "[ ] Chèn thẻ" đặt ngay dưới ô văn bản, cạnh bộ đếm ký tự. Bấm thì mở bảng nổi
   (role="dialog", aria-expanded trên nút). Nếu không đủ chỗ phía dưới (chừa thanh phát)
   thì mở lên trên, giống menu.js.
3. Trong bảng nổi:
   - Ô tìm, tự focus khi mở. Tìm không cần dấu: bỏ dấu cả hai phía, đ→d. Khớp cả thẻ, mô tả
     và bí danh tiếng Anh.
   - Danh sách cuộn (max-height ~300px), chia nhóm:
     * Cảm xúc: emotionTags() của giọng đang chọn (ở chế độ Nhiều người đọc thì gộp các
       engine). Nhóm rỗng thì ghi: Giọng đang chọn không có thẻ cảm xúc…
     * Chỗ nghỉ: Ngắt nhẹ, [nghỉ 0.5s], [nghỉ 1s], [nghỉ 2s], Xuống đoạn.
     * Hiệu ứng âm thanh: các âm có sẵn.
     * Âm của bạn: âm người dùng thêm, và chip viền đứt "＋ Thêm từ file".
   - Chip hiện thẻ có ngoặc vuông, bo góc nhỏ (6px), không phải dạng viên thuốc.
   - Thanh dưới cùng: rê chuột hoặc focus vào thẻ thì hiện "[thẻ] — mô tả". Thẻ hiệu ứng có
     thêm "▶ Nghe thử" (player.play với /api/sfx/<id>/audio); âm của bạn có thêm "Xoá"
     (confirmBox).
4. Chèn: vào vị trí con trỏ, thay vùng đang chọn. Tự thêm khoảng trắng nếu thẻ dính vào chữ.
   Bắn sự kiện "input". Đóng bảng, trả focus về ô văn bản.
5. Bàn phím:
   - Enter trong ô tìm: chèn thẻ đầu tiên.
   - ↓ từ ô tìm vào chip; mũi tên đi giữa các chip; ↑ ở chip đầu thì về ô tìm.
   - Esc: đóng bảng, trả focus về nút; stopPropagation để không đụng phím tắt toàn cục.
   - Bấm ra ngoài thì đóng (trừ khi bấm trong .modal).
6. "＋ Thêm từ file": modal gồm tên thẻ (maxLength 30), file (accept audio/*),
   nút Huỷ / Thêm.
   - Lỗi từ server hiện ngay trong modal.
   - Thành công: tải lại catalog, toast "Đã thêm [tên]…".
7. Catalog tải lười một lần khi mở bảng lần đầu, cache trong module.
8. CSS thêm vào cuối components.css, chỉ dùng biến trong tokens.css.
   Phải đẹp ở cả chế độ sáng và tối.

Report kèm screenshot (sáng + tối):
- bảng đang mở
- tìm "rain" ra [tiếng mưa]
- modal thêm âm
- văn bản sau khi chèn
Kiểm tra không có lỗi JS trong console.
STOP & REPORT.
```

---

## PHASE T-4: Rà soát và kiểm thử trên máy thật

```
PHASE T-4: rà soát và chạy thật với edge-tts và VieNeu.

1. Đọc văn bản:
   "Đêm khuya, trời tối sầm. [tiếng sấm] Có tiếng [gõ cửa] ngoài hiên. [nghỉ 1s] Hắn đứng dậy."
   Làm với cả "Nhanh" (edge) và "Chất lượng cao" (VieNeu). Nghe xem hiệu ứng có đúng chỗ
   không, có nhỏ hơn giọng đọc không, có bị dính vào chữ không. Đo bằng scripts/measure_pauses.py
   nếu dùng được.
2. Nhiều người đọc: một dòng chỉ có "[vỗ tay]" và một dòng chữ có thẻ hiệu ứng ở giữa.
   Tạo lại một dòng, kiểm tra cache.
3. Làm sách nói: tạo thử 1 chương có dòng "[tiếng chiêng]" đứng riêng.
   Kiểm tra cache đoạn (bookq.py: khoá cấu hình). Nếu xoá rồi thêm lại âm của bạn cùng tên
   mà chương cũ vẫn dùng âm cũ, đề xuất cách sửa (đưa sfx.key vào khoá) nhưng CHƯA làm.
4. Thêm vào smoke test (scripts/smoke_test.sh hoặc file smoke riêng): sinh đủ âm có sẵn,
   gọi 4 endpoint /api/sfx, render_text với engine giả.
5. README: thêm đoạn "Thẻ và hiệu ứng âm thanh" (cách dùng, danh sách âm, API, nơi lưu dữ
   liệu).
6. Liệt kê âm có sẵn nào nghe kém nhất kèm đề xuất cách tổng hợp lại (tăng VERSION).
STOP & REPORT (báo cáo cuối).
```