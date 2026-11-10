# Prompt bundle: sắp xếp lại cấu trúc thư mục tts-tool

Đi kèm 2 file: `restructure.py` (script di chuyển, chạy một lần) và `pyproject.toml` (mẫu). Đặt cả hai ở
**ngoài** repo, ví dụ `~/Desktop/Work/restructure/`. Script đã chạy thử trên bản repomix ngày 10/11. Kết quả
smoke test trước và sau khi chuyển giống hệt nhau (cùng 32 PASS; các FAIL đều do máy thử không có VieNeu,
httpx và mạng). `ruff` không có lỗi mới. 6 test JS PASS.

---

## Cấu trúc mới

```
tts-tool/
├── README.md
├── pyproject.toml          ← gộp requirements.txt, requirements-app.txt, requirements-dev.txt, ruff.toml
├── .gitignore
│
├── giongviet/              ← toàn bộ backend Python (một package)
│   ├── __main__.py         python -m giongviet  = chạy server (thay cho python server.py)
│   ├── paths.py            ROOT, WEB, CONFIG: mọi đường dẫn cố định ở một chỗ
│   ├── server.py           API FastAPI
│   ├── library.py          thư viện giọng, thư mục data/, decode_audio
│   ├── settings.py
│   ├── history.py
│   ├── engines/            base, registry, edge, vieneu (giữ nguyên)
│   ├── speech/             văn bản → audio, dùng chung cho mọi màn
│   │   ├── text_normalize.py
│   │   ├── lexicon.py
│   │   ├── sfx.py
│   │   └── dialogue.py
│   ├── books/              sách nói
│   │   ├── store.py        ← books.py
│   │   ├── jobs.py         ← bookq.py (hàng đợi)
│   │   ├── narrate.py
│   │   ├── cast.py
│   │   ├── voice_age.py
│   │   ├── html_import.py
│   │   └── exporter.py
│   └── desktop/            app cửa sổ riêng
│       ├── __main__.py     python -m giongviet.desktop
│       ├── app.py          ← app.py
│       ├── gtk.py          ← app_gtk.py
│       └── giong-viet.svg  ← desktop/giong-viet.svg (app.py dùng lúc chạy)
│
├── web/                    ← static/ (index.html, css/, js/, js/views/)
├── config/                 file người dùng sửa được
│   ├── name_stopwords.txt
│   ├── speech_verbs.txt
│   └── masked_words.txt    ← scripts/masked_words.txt
├── tests/
│   ├── js/                 (giữ nguyên)
│   ├── smoke/              ← scripts/smoke_test.sh, smoke_books.py, smoke_queue.py, smoke_ui.py
│   └── fixtures/           chapter_sample.html, vi-du-chuong-1.txt (← scripts/)
├── tools/                  ← phần còn lại của scripts/: đo đạc, thí nghiệm, CLI phụ
│                             bench_vieneu, measure_pauses, perf_books, lexicon_probe, normalize_probe,
│                             mix_experiment, webview_probe, webview_dnd_source, clean_html
├── packaging/linux/        ← scripts/install_desktop.sh, uninstall_desktop.sh
└── docs/
    ├── img/  ux/           (giữ nguyên)
    └── prompts/            ← PROMPTS.md, PROMPTS-UX.md (+ PROMPTS-TAGS.md, file này)
```

**Vì sao chia như vậy**
- Gốc repo từ 28 file còn 3 file và 9 thư mục. Mỗi thư mục trả lời đúng một câu hỏi: code
  chạy app, giao diện, cấu hình người dùng sửa, test, công cụ dev, cài đặt, tài liệu.
- `scripts/` trước đây trộn 4 loại: test, công cụ đo, script cài đặt và dữ liệu (`masked_words.txt`,
  `vi-du-chuong-1.txt`). Giờ mỗi loại nằm một chỗ.
- `speech/` và `books/` đi theo luồng phụ thuộc thật:
  `books` → `speech` → `engines` → `library`; không có chiều ngược lại.
- `data/` vẫn ở gốc repo, không di chuyển, nên dữ liệu hiện có (giọng, truyện, cache) dùng tiếp được.
- Lệnh mới: `python -m giongviet` (server) và `python -m giongviet.desktop` (app).
  Cài một lần bằng `pip install -e .` thay cho 3 file requirements. Các file trong `tools/` và
  `tests/smoke/` không còn phải chèn `sys.path.insert` nữa.

**Giữ tên biến cũ:** import được viết lại dạng `from giongviet.books import store as books`,
`from giongviet.books import jobs as bookq`, nên các chỗ gọi `books.x()` và `bookq.Q` không đổi gì.

**Bẫy script đã xử lý (agent cần biết khi rà soát)**
1. `engines/registry.py` nạp engine bằng chuỗi `"engines.edge:EdgeEngine"`, nên phải đổi thành
   `"giongviet.engines.edge:..."`. Nếu quên, mọi engine bị bỏ qua mà không báo lỗi.
2. `app.py` gọi `sys.modules.get("bookq")`, nên phải đổi thành `"giongviet.books.jobs"`. Nếu quên,
   `busy()` luôn trả False và hộp hỏi "đang tạo, có thoát không?" không bao giờ hiện.
3. `app.py` có sẵn hàm `paths()`, nên không được `import paths`. Script dùng
   `from giongviet.paths import ROOT, WEB`.
4. Python nhúng trong heredoc của `smoke_test.sh` (`import library`, `import history`,
   `import dialogue`) cũng phải sửa import.
5. Các lệnh tự gọi lại chính nó: `app.py --selftest`, mở cửa sổ thứ 2 bằng `/giong`, và
   `smoke_queue.py` gọi `server.py`. Tất cả đổi sang `-m giongviet...`.
6. `install_desktop.sh` và `uninstall_desktop.sh` tìm gốc repo bằng `/..`, nay phải là `/../..`.
   Lệnh `giong-viet` đã cài cũng phải cài lại.

---

## PROMPT 0: Bối cảnh (dán đầu tiên, kèm Phase R-1)

```
Bạn đang làm việc trên repo "tts-tool" (Giọng Việt). Ta sắp xếp lại cấu trúc thư mục theo
docs/prompts/PROMPTS-RESTRUCTURE.md (file này; trước khi chuyển nó nằm ở <đường dẫn bạn để file>).
Đọc kỹ phần "Cấu trúc mới" và "Bẫy" trước khi làm.

Quy tắc chung:
1. Chỉ DI CHUYỂN và SỬA ĐƯỜNG DẪN/IMPORT. Không đổi logic, không đổi API, không đổi tên hàm,
   không "tiện tay" sửa lỗi lint cũ. Hành vi phải giống hệt trước.
2. Dùng `git mv` để giữ lịch sử từng file.
3. Không đụng vào data/ (dữ liệu người dùng).
4. Python 3.14, venv ở .venv/, luôn dùng `.venv/bin/python -m pip`.
5. Kết thúc phase: DỪNG lại và báo cáo theo mẫu:
   - Đã làm gì (danh sách file thay đổi)
   - Cách test, kèm lệnh và kết quả thực tế
   - Những gì CHƯA chắc chắn hoặc phải giả định
   - Đề xuất điều chỉnh cho phase sau (nếu có)
   Không tự động làm sang phase tiếp theo.
```

---

## PHASE R-1: Chuyển thư mục

```
PHASE R-1: chuyển thư mục.

1. Ghi lại kết quả trước khi chuyển:
   - `git status` phải sạch (còn thay đổi chưa commit thì dừng lại và hỏi tôi).
   - Tạo nhánh mới: restructure.
   - Chạy `SKIP_QUEUE=1 scripts/smoke_test.sh > /tmp/before.out`.
   - Chạy `ruff check --output-format concise . > /tmp/ruff_before.txt`.
   - Chạy `for t in tests/js/*.test.mjs; do node $t; done`.
2. Chạy `python3 <đường dẫn>/restructure.py` ở gốc repo. pyproject.toml mẫu phải nằm cạnh script.
   Script dùng `git mv` + assert, nên lệch chỗ nào là dừng ngay.
   - Nếu dừng ở assert (repo đã khác bản thử, ví dụ có file mới): đọc lỗi, sửa script cho khớp
     repo thật, chạy lại trên một bản `git stash`/`git checkout .` sạch. Ghi rõ đã sửa gì.
   - Nếu repo có file mới mà bảng chưa có: xếp theo đúng tinh thần bảng và báo lại.
3. Cài lại: `.venv/bin/python -m pip install -e ".[vieneu,app,dev]"`.
4. Kiểm tra:
   - Import từng module trong giongviet/ (TTS_DATA_DIR trỏ vào thư mục tạm).
   - `.venv/bin/python -m giongviet`: các URL /, /js/app.js, /css/tokens.css, /api/engines,
     /api/sfx đều trả 200, và cả hai engine đều có trong /api/engines.
   - `SKIP_QUEUE=1 tests/smoke/smoke_test.sh > /tmp/after.out`, rồi so từng dòng PASS/FAIL với
     before (bỏ phần sau dấu " — " và những chỗ chỉ khác tên đường dẫn). Phải giống hệt.
   - ruff: không có mã lỗi mới so với /tmp/ruff_before.txt (lỗi I001 / F401 giảm đi là bình thường).
   - Test JS: PASS như trước.
   - `.venv/bin/python -m giongviet.desktop --selftest` PASS (nếu máy có GTK).
   - grep toàn repo, trừ docs/prompts/ và .git/: không còn `server.py` chạy trực tiếp, `app.py`,
     `scripts/`, `static/`, `requirements`, `import bookq`, `import books`.
5. Commit: "refactor: sắp xếp lại cấu trúc thư mục (chỉ di chuyển, không đổi hành vi)".
STOP & REPORT. Báo cáo kèm `git show --stat` và bảng diff kết quả smoke trước/sau.
```

---

## PHASE R-2: Tài liệu và cài đặt

```
PHASE R-2: tài liệu và cài đặt.

1. README:
   - Viết lại phần cài đặt: một lệnh `pip install -e ".[vieneu,app,dev]"`, giải thích 3 nhóm
     tuỳ chọn. Bỏ mọi chỗ nói requirements*.txt và ruff.toml.
   - Thêm mục "Cấu trúc thư mục": cây thư mục ngắn, mỗi dòng một câu nói thư mục đó chứa gì.
   - Rà lại mọi đường dẫn đã bị thay tự động, xem câu văn còn đọc xuôi không.
2. Chạy lại packaging/linux/install_desktop.sh. Kiểm tra lệnh `giong-viet` và mục trong menu
   ứng dụng còn chạy, `giong-viet /doc` mở thẳng màn Đọc văn bản.
3. Trong docs/prompts/*.md: chỉ thêm một dòng ở đầu mỗi file: "Viết trước khi sắp xếp lại thư
   mục (11/2026): đường dẫn trong file là đường dẫn cũ, xem bảng trong PROMPTS-RESTRUCTURE.md."
   Không sửa nội dung bên trong.
STOP & REPORT.
```

---

## PHASE R-3 (tuỳ chọn): Tách server.py

```
PHASE R-3: tách giongviet/server.py (~1.650 dòng) thành các router, không đổi route.

1. Tạo giongviet/api/ gồm voices.py, read.py, dialogue.py, books.py, sfx.py, history.py,
   settings.py, mỗi file một APIRouter. server.py chỉ còn: tạo app, middleware, xử lý lỗi,
   mount web/, include_router.
2. Đường dẫn, method, status code, JSON trả về phải giữ y nguyên.
   - Trước khi tách: in danh sách `app.routes` (path + methods), lưu lại.
   - Sau khi tách: in lại và so. Phải khớp từng dòng.
3. Smoke test giống hệt kết quả sau R-1.
STOP & REPORT (báo cáo cuối).
```
