#!/usr/bin/env bash
# Smoke test các luồng chính. Khởi động server với TTS_DATA_DIR tạm, chạy chuỗi curl, in PASS/FAIL, tự dọn.
#   scripts/smoke_test.sh            # tất cả
#   SKIP_EDGE=1 scripts/smoke_test.sh  # bỏ các bước cần mạng (edge-tts)
#   SKIP_QUEUE=1 scripts/smoke_test.sh # bỏ bước hàng đợi sách nói (~3 phút, tự chạy server riêng ở cổng 8766)
# Thoát với mã 0 nếu mọi bước PASS, 1 nếu có FAIL. Dùng .venv/bin/python nếu có.
set -u
cd "$(dirname "$0")/.."
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
PORT=${PORT:-8765}
B="http://127.0.0.1:$PORT"
DATA=$(mktemp -d)
WORK=$(mktemp -d)
SERVER_PID=""
PASS=0; FAIL=0

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null && wait "$SERVER_PID" 2>/dev/null
  rm -rf "$DATA" "$WORK"
}
trap cleanup EXIT

ok()   { echo "PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "FAIL  $1${2:+ — $2}"; FAIL=$((FAIL+1)); }
# check <tên> <lệnh trả 0 nếu đạt>
check() { local name=$1; shift; if "$@" >"$WORK/out" 2>&1; then ok "$name"; else bad "$name" "$(head -c 200 "$WORK/out" | tr '\n' ' ')"; fi; }
json()  { $PY -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
status() { curl -s -o "$WORK/body" -w '%{http_code}' "$@"; }
expect_status() { local want=$1; shift; local got; got=$(status "$@"); [ "$got" = "$want" ] || { echo "want $want got $got: $(head -c 150 "$WORK/body")"; return 1; }; }
wav_ok() { $PY - "$1" <<'E'
import sys, soundfile as sf
w, sr = sf.read(sys.argv[1]); assert len(w) > sr * 0.2, "audio quá ngắn"; print(sr)
E
}
wait_job() {  # wait_job <job_id> → in trạng thái cuối
  local s
  for _ in $(seq 1 120); do
    s=$(curl -s "$B/api/dialogue/$1" | json "d['status']")
    [ "$s" != running ] && break; sleep 1
  done
  echo "$s"
}

echo "== khởi động server (TTS_DATA_DIR=$DATA, cổng $PORT)"
TTS_DATA_DIR="$DATA" PORT=$PORT $PY server.py >"$WORK/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 60); do curl -s -o /dev/null "$B/api/engines" && break; sleep 0.5; done
check "server lên" curl -sf "$B/api/engines"

echo "== cơ bản"
check "GET /api/engines có capabilities" bash -c "curl -s $B/api/engines | $PY -c \"import sys,json; d=json.load(sys.stdin); assert d['vieneu']['capabilities']['mix'] and not d['edge']['capabilities']['normalize']\""
check "GET / (index.html)" expect_status 200 "$B/"
check "voices/zzz → 404" expect_status 404 "$B/api/voices/zzz"
check "tts văn bản trống → 400" expect_status 400 -X POST "$B/api/tts" -F text=" "
check "tts quá dài → 400" bash -c "TTS_X=\$($PY -c \"print('a'*20001)\"); [ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/tts -F text=\"\$TTS_X\")\" = 400 ]"

echo "== TTS"
if [ -z "${SKIP_EDGE:-}" ]; then
  # edge-tts là dịch vụ online, thỉnh thoảng lỗi tạm thời: thử tối đa 3 lần
  edge_tts() { for _ in 1 2 3; do [ "$(status -X POST "$B/api/tts" -F text="Xin chào" -F engine=edge -F voice=vi-VN-HoaiMyNeural -o "$WORK/e.mp3")" = 200 ] && return 0; sleep 1; done; echo "edge-tts lỗi: $(head -c 150 "$WORK/body")"; return 1; }
  check "tts edge (mp3)" edge_tts
  check "mp3 hợp lệ" bash -c "file -b $WORK/e.mp3 | grep -qi 'mpeg\\|mp3\\|ID3'"
fi
check "tts vieneu (wav 48 kHz)" bash -c "[ \"\$(curl -s -o $WORK/v.wav -w '%{http_code}' -X POST $B/api/tts -F text='Xin chào các bạn, đây là bản thử.' -F engine=vieneu -F voice='Trúc Ly')\" = 200 ] && [ \"\$($PY -c \"import soundfile as sf; print(sf.info('$WORK/v.wav').samplerate)\")\" = 48000 ]"
check "tts vieneu có chuẩn hoá + thẻ cảm xúc" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/tts -F text='Giá 50k, \$100 ở TP. Hồ Chí Minh [cười].' -F engine=vieneu -F voice='Trúc Ly' -F normalize=true)\" = 200 ]"

echo "== thẻ nghỉ [nghỉ 2s]"
# Đo khoảng lặng dài nhất ở giữa audio (bỏ 0,15 s hai đầu) phải nằm trong 2 s ± 0,1 s; đầu ra là WAV 48 kHz
pause_gap() {
  curl -s -o "$WORK/p.wav" -D "$WORK/p.h" -X POST "$B/api/tts" -F text="Xin chào các bạn. [nghỉ 2s] Hẹn gặp lại nhé." -F engine="$1" -F voice="$2" || return 1
  head -1 "$WORK/p.h" | grep -q ' 200' || { echo "HTTP: $(head -1 "$WORK/p.h")"; return 1; }
  grep -qi 'content-type: audio/wav' "$WORK/p.h" || { echo "không phải WAV"; return 1; }
  $PY - "$WORK/p.wav" <<'PYEOF'
import sys, numpy as np, soundfile as sf
w, sr = sf.read(sys.argv[1]); assert sr == 48000, sr
win = int(0.01 * sr); n = len(w) // win
env = np.abs(w[:n * win]).reshape(n, win).mean(1); quiet = env < 10 ** (-40 / 20)
quiet[:15] = False; quiet[-15:] = False
best = run = 0
for q in quiet:
    run = run + 1 if q else 0; best = max(best, run)
gap = best * 0.01
assert 1.9 <= gap <= 2.1, f"khoảng lặng {gap:.2f}s ngoài 2s ± 0.1"
print(f"{gap:.2f}s")
PYEOF
}
retry3() { for _ in 1 2 3; do "$@" && return 0; sleep 1; done; return 1; }   # edge-tts thỉnh thoảng lỗi tạm thời; VieNeu lấy mẫu ngẫu nhiên nên đuôi lặng lệch vài chục ms mỗi lần
check "thẻ nghỉ 2s với vieneu: khoảng lặng 2 ± 0.1 s" retry3 pause_gap vieneu "Trúc Ly"
[ -z "${SKIP_EDGE:-}" ] && check "thẻ nghỉ 2s với edge: khoảng lặng 2 ± 0.1 s" retry3 pause_gap edge vi-VN-HoaiMyNeural
check "thẻ nghỉ ngoài 0.1–5 s → 400" expect_status 400 -X POST "$B/api/tts" -F text="a [nghỉ 7s] b" -F engine=vieneu -F voice="Trúc Ly"
command -v ffmpeg >/dev/null && check "bản có thẻ nghỉ có MP3 trong lịch sử" bash -c "I=\$(curl -s '$B/api/history?kind=tts' | $PY -c \"import sys,json; print(json.load(sys.stdin)[0]['id'])\"); [ \"\$(curl -s -o /dev/null -w '%{http_code}' '$B/api/history/'\$I'/audio?fmt=mp3')\" = 200 ]"

echo "== tab Đọc: giọng mẫu (ref_audio) + [nghỉ 1s] — cache theo file mẫu"
curl -s -o "$WORK/refA.wav" -X POST "$B/api/tts" -F text="Hôm nay trời đẹp lắm, tôi muốn đi dạo cùng bạn bè quanh hồ." -F engine=vieneu -F voice="Trúc Ly"
curl -s -o "$WORK/refB.wav" -X POST "$B/api/tts" -F text="Hôm nay trời đẹp lắm, tôi muốn đi dạo cùng bạn bè quanh hồ." -F engine=vieneu -F voice="Adam bựa"
ref_pause() {  # ref_pause <file mẫu> <file ra>
  [ "$(curl -s -o "$2" -w '%{http_code}' -X POST "$B/api/tts" -F text="Xin chào bạn. [nghỉ 1s] Hẹn gặp lại nhé." -F engine=vieneu -F ref_audio=@"$1")" = 200 ]
}
cache_n() { ls "$DATA"/cache/*.wav 2>/dev/null | wc -l; }
ref_cache_behaviour() {
  local c0 c1 c2 c3
  c0=$(cache_n)
  ref_pause "$WORK/refA.wav" "$WORK/o1.wav" || { echo "lần 1 lỗi"; return 1; }
  c1=$(cache_n); [ $((c1 - c0)) -eq 2 ] || { echo "lần 1 phải tạo 2 đoạn cache mới, thực tế $((c1 - c0))"; return 1; }
  ref_pause "$WORK/refA.wav" "$WORK/o2.wav" || { echo "lần 2 lỗi"; return 1; }
  c2=$(cache_n); [ "$c2" -eq "$c1" ] || { echo "lần 2 (cùng file mẫu) phải dùng cache, nhưng cache tăng $((c2 - c1))"; return 1; }
  cmp -s "$WORK/o1.wav" "$WORK/o2.wav" || { echo "lần 2 phải cho đúng audio của lần 1"; return 1; }
  ref_pause "$WORK/refB.wav" "$WORK/o3.wav" || { echo "lần 3 lỗi"; return 1; }
  c3=$(cache_n); [ $((c3 - c2)) -eq 2 ] || { echo "đổi file mẫu phải sinh lại 2 đoạn, thực tế $((c3 - c2))"; return 1; }
  ! cmp -s "$WORK/o1.wav" "$WORK/o3.wav" || { echo "đổi file mẫu mà audio không đổi"; return 1; }
}
check "ref_audio + [nghỉ 1s]: cùng file mẫu dùng cache, đổi file mẫu thì sinh lại" ref_cache_behaviour

echo "== lịch sử"
check "lịch sử có bản tts" bash -c "curl -s '$B/api/history?kind=tts' | $PY -c \"import sys,json; assert len(json.load(sys.stdin)) >= 1\""
HID=$(curl -s "$B/api/history" | json "d[0]['id']" 2>/dev/null)
check "tải audio lịch sử" expect_status 200 "$B/api/history/$HID/audio"
check "xoá một bản lịch sử" expect_status 200 -X DELETE "$B/api/history/$HID"
check "xoá bản không tồn tại → 404" expect_status 404 -X DELETE "$B/api/history/$HID"

echo "== thư viện giọng"
# audio mẫu 3–30 giây: sinh bằng chính VieNeu
curl -s -o "$WORK/sample.wav" -X POST "$B/api/tts" -F text="Hôm nay trời đẹp lắm, tôi muốn đi dạo cùng bạn bè quanh hồ vào buổi chiều." -F engine=vieneu -F voice="Trúc Ly"
check "thêm giọng không consent → 400" expect_status 400 -X POST "$B/api/library" -F name=A -F engine=vieneu -F ref_audio=@"$WORK/sample.wav"
check "thêm giọng audio quá ngắn → 400" bash -c "$PY -c \"import soundfile as sf,numpy as np; sf.write('$WORK/short.wav', np.zeros(24000)+0.1, 24000)\"; [ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/library -F name=S -F engine=vieneu -F consent=true -F ref_audio=@$WORK/short.wav)\" = 400 ]"
check "thêm giọng (clone)" bash -c "[ \"\$(curl -s -o $WORK/lib.json -w '%{http_code}' -X POST $B/api/library -F name='Giọng thử' -F engine=vieneu -F gender=nữ -F region=bac -F tags='thử,smoke' -F consent=true -F ref_audio=@$WORK/sample.wav)\" = 200 ]"
LIB=$(json "d['voice']" <"$WORK/lib.json" 2>/dev/null)
check "giọng lib: xuất hiện trong /api/voices/vieneu" bash -c "curl -s $B/api/voices/vieneu | grep -q '$LIB'"
check "tts bằng giọng lib:" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/tts -F text='Xin chào.' -F engine=vieneu -F voice='$LIB')\" = 200 ]"
check "preview giọng lib (cache)" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' $B/api/library/${LIB#lib:}/preview)\" = 200 ] && [ \"\$(curl -s -o /dev/null -w '%{http_code}' $B/api/library/${LIB#lib:}/preview)\" = 200 ]"
VD="$DATA/voices/${LIB#lib:}"
check "preview giọng lib đặt tên theo cache_tag (preview.<tag>.wav), không có preview.wav trần" bash -c "ls $VD | grep -qE '^preview\.v3turbo(-int8)?\.wav\$' && ! [ -e $VD/preview.wav ]"
check "preview của tag khác (precision / mode cũ) bị thay bằng bản đúng tag, chỉ còn một file preview" bash -c "rm -f $VD/preview.*; echo x >$VD/preview.v3turbo-fake.wav; [ \"\$(curl -s -o /dev/null -w '%{http_code}' $B/api/library/${LIB#lib:}/preview)\" = 200 ] && [ \"\$(ls $VD | grep -c '^preview\.')\" = 1 ] && ! [ -e $VD/preview.v3turbo-fake.wav ] && ls $VD | grep -qE '^preview\.v3turbo(-int8)?\.wav\$'"
check "xoá preview.wav cũ không có tag (library.drop_untagged_previews), giữ preview.mp3 / bản đã có tag" env TTS_DATA_DIR="$WORK/prev" $PY - <<'PYEOF2'
import library
d = library.VOICES / "abc"
d.mkdir(parents=True)
(d / "preview.wav").write_bytes(b"old")
assert library.drop_untagged_previews() == 1 and not (d / "preview.wav").exists()
(d / "preview.mp3").write_bytes(b"x"); (d / "preview.v3turbo.wav").write_bytes(b"x")
assert library.drop_untagged_previews() == 0 and (d / "preview.mp3").exists() and (d / "preview.v3turbo.wav").exists()
PYEOF2
check "sửa metadata + yêu thích" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X PATCH $B/api/library/${LIB#lib:} -F name='Giọng đổi tên' -F favorite=true)\" = 200 ]"

echo "== trộn giọng"
check "mix preview (slider 0.5)" bash -c "[ \"\$(curl -s -o $WORK/m.wav -w '%{http_code}' -X POST $B/api/mix -F voice_a='Adam bựa' -F voice_b='Trúc Ly' -F slider=0.5)\" = 200 ]"
check "mix cùng một giọng → 400" expect_status 400 -X POST "$B/api/mix" -F voice_a="Adam bựa" -F voice_b="Adam bựa"
check "mix lưu vào thư viện" bash -c "[ \"\$(curl -s -o $WORK/mix.json -w '%{http_code}' -X POST $B/api/mix/save -F voice_a='Adam bựa' -F voice_b=$LIB -F slider=0.3 -F name='Mix thử')\" = 200 ]"
MIX=$(json "d['voice']" <"$WORK/mix.json" 2>/dev/null)
check "giọng mix không có ref.wav, có emb.npz" bash -c "d=\"$DATA/voices/${MIX#lib:}\"; [ ! -e \$d/ref.wav ] && ls \$d | grep -q 'emb\\..*\\.npz'"
check "tts bằng giọng mix" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/tts -F text='Giọng trộn.' -F engine=vieneu -F voice='$MIX')\" = 200 ]"

echo "== hội thoại"
cat >"$WORK/dlg.json" <<E
{"script":"[Lan]: Xin chào anh.\n[Minh]: Chào em [cười].\n\n[Lan]: Tạm biệt nhé.",
 "cast":{"Lan":{"engine":"vieneu","voice":"Trúc Ly"},"Minh":{"engine":"vieneu","voice":"Adam bựa"}},"gap_ms":300,"paragraph_gap_ms":700}
E
check "parse kịch bản" bash -c "curl -s -X POST $B/api/dialogue/parse -H 'Content-Type: application/json' -d @$WORK/dlg.json | $PY -c \"import sys,json; d=json.load(sys.stdin); assert d['speakers']==['Lan','Minh'] and len(d['lines'])==3 and d['lines'][2]['pause']=='paragraph'\""
check "thiếu giọng → 400 kèm missing" bash -c "[ \"\$(curl -s -o $WORK/b -w '%{http_code}' -X POST $B/api/dialogue -H 'Content-Type: application/json' -d '{\"script\":\"[A]: x\",\"cast\":{}}')\" = 400 ] && grep -q missing $WORK/b"
JOB=$(curl -s -X POST "$B/api/dialogue" -H 'Content-Type: application/json' -d @"$WORK/dlg.json" | json "d['job_id']" 2>/dev/null)
check "tạo job hội thoại 3 dòng" test -n "$JOB"
JS=$(wait_job "$JOB")
check "job → done" test "$JS" = done
check "audio tổng WAV 48 kHz mono" bash -c "curl -s -o $WORK/d.wav $B/api/dialogue/$JOB/audio && [ \"\$($PY -c \"import soundfile as sf; i=sf.info('$WORK/d.wav'); print(i.samplerate, i.channels)\")\" = '48000 1' ]"
check "dùng lại cache (job 2: dòng cached)" bash -c "J2=\$(curl -s -X POST $B/api/dialogue -H 'Content-Type: application/json' -d @$WORK/dlg.json | $PY -c \"import sys,json; print(json.load(sys.stdin)['job_id'])\"); for _ in \$(seq 1 60); do s=\$(curl -s $B/api/dialogue/\$J2 | $PY -c \"import sys,json; d=json.load(sys.stdin); print(d['status'], all(l['cached'] for l in d['lines']))\"); case \"\$s\" in running*) sleep 1;; *) break;; esac; done; [ \"\$s\" = 'done True' ]"
check "sinh lại dòng 2 (seed)" bash -c "curl -s -X POST $B/api/dialogue/$JOB/line/1 -H 'Content-Type: application/json' -d '{\"seed\":7}' | $PY -c \"import sys,json; d=json.load(sys.stdin); assert d['status']=='done' and d['lines'][1]['seed']==7\""
check "lịch sử có bản hội thoại" bash -c "curl -s '$B/api/history?kind=dialogue' | $PY -c \"import sys,json; assert len(json.load(sys.stdin))>=1\""
if [ -z "${SKIP_EDGE:-}" ]; then
  cat >"$WORK/dlg2.json" <<E
{"script":"[Lan]: Xin chào [cười].\n[Minh]: Chào em.","cast":{"Lan":{"engine":"edge","voice":"vi-VN-HoaiMyNeural"},"Minh":{"engine":"vieneu","voice":"Adam bựa"}}}
E
  JOB2=$(curl -s -X POST "$B/api/dialogue" -H 'Content-Type: application/json' -d @"$WORK/dlg2.json" | json "d['job_id']" 2>/dev/null)
  check "hội thoại đa engine (edge + vieneu, MP3→WAV 48 kHz)" test "$(wait_job "$JOB2")" = done
  dlg_secs() {  # dlg_secs "<lời của Lan (edge)>" → "<trạng thái> <số giây của dòng>"
    local j
    j=$(curl -s -X POST "$B/api/dialogue" -H 'Content-Type: application/json' -d "$($PY -c 'import json,sys; print(json.dumps({"script": "[Lan]: " + sys.argv[1], "cast": {"Lan": {"engine": "edge", "voice": "vi-VN-HoaiMyNeural"}}}))' "$1")" | json "d['job_id']")
    wait_job "$j" >/dev/null
    curl -s "$B/api/dialogue/$j" | json "str(d['status']) + ' ' + str(d['lines'][0]['seconds'])"
  }
  pause_dialogue_diff() {
    local a b
    a=$(dlg_secs "Xin chào các bạn. [nghỉ 0.1s] Hẹn gặp lại nhé."); b=$(dlg_secs "Xin chào các bạn. [nghỉ 1.1s] Hẹn gặp lại nhé.")
    $PY -c "import sys; a=sys.argv[1].split(); b=sys.argv[2].split(); assert a[0]==b[0]=='done', (a,b); assert 0.85 <= float(b[1])-float(a[1]) <= 1.15, (a,b); print(a,b)" "$a" "$b"
  }
  check "dòng hội thoại: [nghỉ 1.1s] dài hơn [nghỉ 0.1s] đúng khoảng 1 s" retry3 pause_dialogue_diff
fi

echo "== project"
check "lưu project" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/projects -H 'Content-Type: application/json' -d '{\"name\":\"Smoke\",\"script\":\"[A]: x\",\"cast\":{}}')\" = 200 ]"
check "mở project" bash -c "curl -s $B/api/projects/smoke | grep -q '\"script\"'"
check "liệt kê project" bash -c "curl -s $B/api/projects | grep -q smoke"
check "xoá project" expect_status 200 -X DELETE "$B/api/projects/smoke"

echo "== dọn dẹp thư viện"
check "xoá giọng mix" expect_status 200 -X DELETE "$B/api/library/${MIX#lib:}"
check "xoá giọng clone" expect_status 200 -X DELETE "$B/api/library/${LIB#lib:}"
check "giọng đã xoá → 404" expect_status 404 "$B/api/library/${LIB#lib:}/preview"
check "lịch sử giữ tên giọng đã xoá (voice_label + voice_deleted)" bash -c "curl -s '$B/api/history?kind=tts' | $PY -c \"import sys,json; m=[x for x in json.load(sys.stdin) if x.get('voice')=='$LIB']; assert m and m[0]['voice_label'] and m[0]['voice_deleted'] is True, m\""

echo "== giao diện (khung mới: tệp tĩnh, giao diện cũ, tổng quan)"
check "GET / trả khung mới (module JS + tokens.css, không còn giao diện cũ)" bash -c "curl -s $B/ | grep -q 'type=\"module\" src=\"/js/app.js\"' && curl -s $B/ | grep -q '/css/tokens.css' && ! curl -s $B/ | grep -q 'id=\"tab-tts\"'"
check "GET /css/tokens.css (text/css, có biến màu, no-cache)" bash -c "curl -sD - $B/css/tokens.css | tr -d '\r' | grep -qi '^content-type: text/css' && curl -s $B/css/tokens.css | grep -q -- '--accent' && curl -sD - -o /dev/null $B/css/tokens.css | tr -d '\r' | grep -qi '^cache-control: no-cache'"
check "GET /js/app.js là JavaScript" bash -c "curl -sD - -o /dev/null $B/js/app.js | tr -d '\r' | grep -qiE '^content-type: (text|application)/(javascript|x-javascript)'"
check "GET /legacy trả giao diện cũ (liên kết sâu #book, #lib-add)" bash -c "curl -s $B/legacy | grep -q 'Giao diện cũ' && curl -s $B/legacy | grep -q 'lib-add'"
if command -v node >/dev/null; then
  check "mọi file static/js/**/*.js đúng cú pháp ES module" bash -c "for f in static/js/*.js static/js/views/*.js; do node --check --input-type=module < \$f || exit 1; done"
  check "errors.js: lỗi kỹ thuật → lời thường + cách khắc phục (node tests/js/errors.test.mjs)" node tests/js/errors.test.mjs
  check "titlepattern.js: một dòng tiêu đề mẫu → mẫu tìm chương (node tests/js/titlepattern.test.mjs)" node tests/js/titlepattern.test.mjs
fi

echo "== sách nói (nhập .txt/.epub, tách chương, làm sạch, ngăn cảnh → [nghỉ])"
$PY scripts/smoke_books.py "$B" >"$WORK/books.out" 2>&1
grep -E '^(PASS|FAIL)  ' "$WORK/books.out"
PASS=$((PASS + $(grep -c '^PASS  ' "$WORK/books.out")))
FAIL=$((FAIL + $(grep -c '^FAIL  ' "$WORK/books.out")))
grep -qE '^(PASS|FAIL)  ' "$WORK/books.out" || bad "sách nói: smoke_books.py không chạy được" "$(tail -3 "$WORK/books.out" | tr '\n' ' ')"

echo "== hàng đợi sách nói (server riêng: kill -9 / SIGINT giữa chừng, tiếp tục, xuất MP3 + m4b; ~3 phút, SKIP_QUEUE=1 để bỏ)"
if [ -z "${SKIP_QUEUE:-}" ]; then
  # dung sai 0.12 = 0.1 yêu cầu + 0.02 cho độ ngẫu nhiên của model (mỗi lần dựng, đuôi lặng của từng câu lệch vài chục ms)
  if $PY scripts/measure_pauses.py --tol 0.12 >"$WORK/pauses.out" 2>&1; then
    ok "khoảng lặng xuống đoạn / sau tiêu đề trong audio chương: mọi chỗ trong ±0.12 s, cả mối nối đoạn cắt ($(grep -c ' OK$' "$WORK/pauses.out") chỗ đo, lệch lớn nhất $(grep -E ' OK$' "$WORK/pauses.out" | awk '{for(i=1;i<=NF;i++) if ($i ~ /^[+-][0-9.]+$/) {v=$i<0?-$i:$i; if (v>m) m=v}} END{print m}') s)"
  else
    bad "khoảng lặng xuống đoạn / sau tiêu đề trong audio chương" "$(grep -E 'LỆCH|Error|assert' "$WORK/pauses.out" | head -5 | tr '\n' ' ')"
  fi
  $PY scripts/smoke_queue.py >"$WORK/queue.out" 2>&1
  grep -E '^(PASS|FAIL)  ' "$WORK/queue.out"
  PASS=$((PASS + $(grep -c '^PASS  ' "$WORK/queue.out")))
  FAIL=$((FAIL + $(grep -c '^FAIL  ' "$WORK/queue.out")))
  grep -qE '^(PASS|FAIL)  ' "$WORK/queue.out" || bad "hàng đợi: smoke_queue.py không chạy được" "$(tail -3 "$WORK/queue.out" | tr '\n' ' ')"
  grep -qE '^FAIL  ' "$WORK/queue.out" && sed -n '/^--- cuối server.log/,$p' "$WORK/queue.out" | head -30
fi

echo "== giới hạn: lịch sử 50 bản, LRU cache (module trực tiếp, data tạm riêng)"
check "lịch sử giữ đúng 50 bản mới nhất" env TTS_DATA_DIR="$WORK/hist" $PY - <<'PYEOF'
import history
for i in range(55):
    history.save("tts", {"text": f"t{i}"}, b"a", "wav")
items = history.list_items()
assert len(items) == 50, len(items)
assert items[0]["text"] == "t54" and items[-1]["text"] == "t5", (items[0]["text"], items[-1]["text"])
assert len(list(history.HISTORY.glob("*.wav"))) == 50  # audio của bản bị cắt cũng được xoá
PYEOF
check "LRU cache (TTS_CACHE_MB nhỏ): xoá cũ nhất, giữ bản vừa dùng + dòng của job sống, cảnh báo khi vẫn vượt" env TTS_CACHE_MB=0.003 TTS_DATA_DIR="$WORK/lru" $PY - <<'PYEOF'
import logging, os
import dialogue
c = dialogue.CACHE
c.mkdir(parents=True)
for i in range(5):                                   # 5 file x 1000 B, mtime tăng dần; limit = 0.003 MB ≈ 3145 B
    f = c / f"k{i}.wav"; f.write_bytes(b"x" * 1000); os.utime(f, (1000 + i, 1000 + i))
job = dialogue.Job("j1", [], {}, 0, 0, 0); job.keys = ["k0"]; dialogue.JOBS["j1"] = job   # k0 thuộc job đang sống
os.utime(c / "k2.wav", (5000, 5000))                  # k2 vừa được dùng (cache hit → touch)
dialogue.prune_cache()                                # dùng giới hạn từ TTS_CACHE_MB
left = sorted(p.name for p in c.glob("*.wav"))
assert "k1.wav" not in left and "k0.wav" in left and "k2.wav" in left, left
records = []
class H(logging.Handler):
    def emit(self, r): records.append(r.getMessage())
dialogue.log.addHandler(H())
dialogue.prune_cache(limit=500)                       # k0 (job sống) vẫn nằm đó và đã vượt 500 B → phải cảnh báo
assert any("vượt TTS_CACHE_MB" in m for m in records), records
PYEOF

echo
echo "Kết quả: $PASS PASS, $FAIL FAIL"
[ "$FAIL" -eq 0 ] || { echo "--- cuối server.log:"; tail -15 "$WORK/server.log"; exit 1; }
