// Thử errors.js (đổi lỗi kỹ thuật → lời thường). Chạy: node tests/js/errors.test.mjs
import assert from "node:assert/strict";
import { explain } from "../../static/js/errors.js";

const BANNED = /\b(engine|precision|int8|fp32|alpha|slider|cache|regex|selector|seed|RTF|embedding|mode|job|queue)\b/i;
const cases = [
  [{ status: 500, message: "edge-tts lỗi: 502 No audio was received" }, /Giọng online đang bận/, /No audio was received/],
  [{ status: 502, message: "No audio was received. Please verify that your parameters are correct." }, /Giọng online đang bận/, /No audio/],
  [{ status: 0, message: "TypeError: Failed to fetch" }, /Không kết nối được/, /Failed to fetch/],
  [{ status: 400, message: "Chưa cài VieNeu-TTS. Chạy: pip install vieneu" }, /chưa được cài/, /pip install/],
  [{ status: 500, message: "VieNeu-TTS lỗi: CUDA out of memory" }, /Giọng trên máy gặp trục trặc/, /CUDA/],
  [{ status: 404, message: "Không tìm thấy giọng trong thư viện." }, /Không tìm thấy/, /Không tìm thấy giọng/],
  [{ status: 413, message: "x" }, /File quá lớn/, "x"],
  [{ status: 422, message: "Dữ liệu gửi lên không hợp lệ." }, /chưa hợp lệ/, /không hợp lệ/],
  [{ status: 503, message: "Traceback…" }, /bất ngờ/, /Traceback/],
];
for (const [err, title, detail] of cases) {
  const e = explain(err);
  assert.match(e.title, title, JSON.stringify(err));
  assert.ok(e.tip.length > 10, "phải có cách khắc phục: " + e.title);
  assert.match(e.detail, detail instanceof RegExp ? detail : new RegExp(detail));
  assert.ok(!BANNED.test(e.title + " " + e.tip), "từ kỹ thuật lọt vào câu hiển thị: " + e.title + " " + e.tip);
}
// Lỗi 400 server đã viết bằng tiếng Việt thì giữ nguyên, không có chi tiết thừa
const plain = explain({ status: 400, message: "Hãy nhập văn bản." });
assert.equal(plain.title, "Hãy nhập văn bản.");
assert.equal(plain.detail, "");
assert.equal(explain(new Error("boom")).title, "Tool gặp lỗi bất ngờ.");   // lỗi không có status
console.log("errors.test.mjs: ok");
