// Từ MỘT dòng tiêu đề chương mẫu suy ra mẫu tìm tiêu đề (regex) cho server. Hàm thuần, thử bằng node: tests/js/titlepattern.test.mjs.
// Người dùng chỉ cần dán "Chương 5: Gặp gỡ"; ô regex chỉ hiện trong Nâng cao.

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\\/-]/g, "\\$&");
const CJK_NUM = "零〇一二三四五六七八九十百千万两兩";
const UNITS = "章回节節话話集卷";

/** @returns {string|null} regex (server so khớp từ đầu dòng, không phân biệt hoa thường) hoặc null nếu dòng trống */
export function inferTitlePattern(line) {
  const s = String(line || "").replace(/^\s+|\s+$/g, "");
  if (!s) return null;
  const token = (t) => (/^\d+$/.test(t) ? "\\d+" : esc(t));
  const words = (t) => t.trim().split(/\s+/).filter(Boolean).map(token).join("\\s+");
  // Từ khoá chương + số ("Chương 5", "Hồi 12", "Chapter 3", "第5章"): lấy lần xuất hiện CUỐI ("Quyển 2 Chương 5" → số của Chương)
  const kw = [...s.matchAll(/(chương|chuong|hồi|hoi|chapter|chap|phần|phan|tập|tap|quyển|quyen|第)\s*(\d+|[零〇一二三四五六七八九十百千万两兩]+|[IVXLCDM]{1,7}(?![\p{L}\d]))/giu)].pop();
  let idx, len, kind;
  if (kw) { len = kw[2].length; idx = kw.index + kw[0].length - len; kind = /^\d/.test(kw[2]) ? "d" : /^[IVXLCDM]+$/i.test(kw[2]) ? "r" : "c"; }
  else {
    const m = new RegExp(`(\\d+)|([${CJK_NUM}]+)(?=[${UNITS}\\s:：.])|(?<![\\p{L}\\d])([IVXLCDM]{1,7})(?![\\p{L}\\d])`, "u").exec(s);
    if (!m) return `^\\s*${words(s)}\\s*$`;        // tiêu đề không có số ("Mở đầu"): khớp nguyên dòng
    idx = m.index; len = m[0].length; kind = m[1] ? "d" : m[2] ? "c" : "r";
  }
  const prefix = s.slice(0, idx), after = s.slice(idx + len);
  const cls = kind === "d" ? "\\d+" : kind === "c" ? `[${CJK_NUM}\\d]+` : "[IVXLCDM]+";
  const unit = after && UNITS.includes(after[0]) ? after[0] : "";
  const head = prefix.trim() ? words(prefix) + (/[\s\p{L}]$/u.test(prefix) ? "\\s*" : "") : "";
  return `^\\s*${head}${cls}${unit}(?!\\d)`;
}
