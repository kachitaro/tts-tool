// Thử titlepattern.js: một dòng tiêu đề mẫu → mẫu tìm tiêu đề. Chạy: node tests/js/titlepattern.test.mjs
import assert from "node:assert/strict";
import { inferTitlePattern } from "../../web/js/titlepattern.js";

const text = [
  "Chương 1: Mở đầu", "Những dòng văn thường, không phải tiêu đề.", "Chương 2", "Chuong 3 - Gặp gỡ",
  "Hồi 4. Biến cố", "CHƯƠNG 5 — TRỞ VỀ", "Chapter 6", "第7章 开始", "Quyển 2 Chương 8: Lửa", "9. Cuối cùng", "Chương XII", "Mở đầu",
  "Chương trình truyền hình hôm nay rất hay và dài hơn một dòng thường gặp.", "Chương 100 năm sau, anh vẫn nhớ.",
];
const heads = (pat) => text.filter((l) => new RegExp(pat, "i").test(l));

const cases = [
  ["Chương 5: Gặp gỡ", ["Chương 1: Mở đầu", "Chương 2", "CHƯƠNG 5 — TRỞ VỀ", "Chương 100 năm sau, anh vẫn nhớ."]],   // không phân biệt hoa thường; "Chuong" không dấu là chữ khác
  ["chuong 3 - Gặp gỡ", ["Chuong 3 - Gặp gỡ"]],
  ["Hồi 4. Biến cố", ["Hồi 4. Biến cố"]],
  ["CHƯƠNG 5 — TRỞ VỀ", ["Chương 1: Mở đầu", "Chương 2", "CHƯƠNG 5 — TRỞ VỀ", "Chương 100 năm sau, anh vẫn nhớ."]],
  ["Chapter 6", ["Chapter 6"]],
  ["第7章 开始", ["第7章 开始"]],
  ["Quyển 2 Chương 8: Lửa", ["Quyển 2 Chương 8: Lửa"]],          // lấy số của "Chương", số của "Quyển" thành \d+ nên khớp mọi quyển
  ["9. Cuối cùng", ["9. Cuối cùng"]],
  ["Chương XII", ["Chương XII"]],
  ["Mở đầu", ["Mở đầu"]],
];
for (const [example, want] of cases) {
  const pat = inferTitlePattern(example);
  assert.ok(pat, example);
  new RegExp(pat, "i");                                           // phải biên dịch được
  assert.deepEqual(heads(pat), want, `${example} → ${pat}`);
  assert.ok(new RegExp(pat, "i").test(example), "phải khớp chính dòng mẫu: " + example);
}
assert.equal(inferTitlePattern("   "), null);
assert.equal(inferTitlePattern(null), null);
assert.ok(!heads(inferTitlePattern("Chương 5: Gặp gỡ")).includes("Chương trình truyền hình hôm nay rất hay và dài hơn một dòng thường gặp."));
console.log("titlepattern.test.mjs: ok");
