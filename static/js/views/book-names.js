// Thẻ "Cách đọc tên riêng": danh sách tên đã chỉnh + gợi ý tên tìm thấy trong truyện (nghe thử, "Đọc sai? Sửa").
import { h } from "../dom.js";
import { getJSON, sendJSON } from "../api.js";
import { showError, toast, modal } from "../ui.js";
import { play } from "../player.js";
import { editEntry, emptyEntry, describe } from "../lexicon-editor.js";
import { patchBook } from "../bookapi.js";

const fmtN = (n) => Number(n).toLocaleString("vi-VN");

export function mountNamesTab(root, { id, book, onChanged }) {
  let alive = true, list = (book.lexicon || []).map((e) => ({ ...e })), sugg = null;
  const box = h("div", {}), sugBox = h("div", {});
  root.append(box, sugBox);

  async function save(next, okText) {
    try {
      const saved = await patchBook(id, { lexicon: next });
      list = saved.lexicon; book.lexicon = list; paint(); paintSug();
      toast(okText || "Đã lưu. Các chương đã tạo sẽ được đánh dấu “cần tạo lại”.");
      onChanged && onChanged();
      return true;
    } catch (e) { showError(e); return false; }
  }

  async function editAt(i, preset) {
    const base = i == null ? (preset || emptyEntry()) : list[i];
    const r = await editEntry(base, { title: i == null ? "Thêm cách đọc một tên" : "Cách đọc tên này", canDelete: i != null });
    if (!r) return false;
    const next = [...list];
    if (r._delete) next.splice(i, 1);
    else { const { _delete, ...e } = r; if (i == null) next.push(e); else next[i] = e; }
    return save(next);
  }

  function paint() {
    box.replaceChildren(h("div", { class: "card flat" }, h("h3", { style: "font-size:20px" }, "Cách đọc tên riêng"),
      h("p", { class: "muted" }, "Nếu tool đọc sai một tên (ví dụ “Tiêu Viêm”), thêm vào đây để tool đọc đúng ở mọi chương. Sau khi sửa, các chương đã tạo cần tạo lại."),
      list.length ? h("div", { class: "chlist" }, ...list.map((e, i) => h("div", { class: "chrow" },
        h("div", { class: "name" }, h("b", {}, e.match), h("div", { class: "sub" }, describe(e))),
        h("button", { class: "btn small", onclick: () => editAt(i) }, "Đọc sai? Sửa")))) : h("p", { class: "muted" }, "Chưa có tên nào. Bấm “Tìm tên riêng trong truyện” bên dưới để tool gợi ý."),
      h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "btn", onclick: () => editAt(null) }, "＋ Thêm tên"))));
  }

  const minCount = { v: 3 };
  async function scan(btn) {
    btn.disabled = true; btn.textContent = "Đang tìm…";
    try { sugg = (await getJSON(`/api/books/${encodeURIComponent(id)}/suggest?min_count=${minCount.v}`)).terms; paintSug(); }
    catch (e) { showError(e); }
    btn.disabled = false; btn.textContent = "Tìm tên riêng";
  }

  async function hear(t, btn) {
    btn.disabled = true;
    try {
      const res = await fetch(`/api/books/${encodeURIComponent(id)}/speak`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t.example }) });
      if (!res.ok) throw new Error((await res.json()).error || res.statusText);
      play({ src: URL.createObjectURL(await res.blob()), title: t.phrase, sub: "Nghe thử câu ví dụ" });
    } catch (e) { showError(e); }
    btn.disabled = false;
  }

  function paintSug() {
    const scanBtn = h("button", { class: "btn primary", onclick: (e) => scan(e.target) }, "Tìm tên riêng");
    sugBox.replaceChildren(h("div", { class: "card flat", style: "margin-top:16px" }, h("h3", { style: "font-size:20px" }, "Tìm tên riêng trong truyện"),
      h("p", { class: "muted" }, "Tool tìm các tên xuất hiện nhiều lần để bạn nghe thử và sửa nhanh những tên bị đọc sai."), scanBtn,
      h("details", { class: "adv" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body" }, h("label", { class: "field" }, "Chỉ gợi ý tên xuất hiện từ … lần"),
        h("input", { type: "number", min: 1, max: 100, value: minCount.v, style: "max-width:100px", oninput: (e) => { minCount.v = Math.max(1, +e.target.value || 3); } }))),
      sugg ? (sugg.length ? h("div", { class: "chlist", style: "margin-top:14px" }, ...sugg.map((t) => h("div", { class: "chrow" + (t.parent ? " child" : "") },
        h("div", { class: "name" }, h("b", {}, t.phrase), h("span", { class: "muted" }, ` · ${fmtN(t.count)} lần${t.parent ? ` · một phần của “${t.parent}”` : ""}`), h("div", { class: "sub" }, `“${t.example}”`)),
        h("button", { class: "play", "aria-label": "Nghe thử " + t.phrase, onclick: (e) => hear(t, e.currentTarget) }, "▶"),
        h("button", { class: "btn small", onclick: async () => { const ok = await editAt(null, { ...emptyEntry(t.phrase), pause_before: 0.2, case_sensitive: true }); if (ok) { sugg = sugg.filter((x) => x !== t); paintSug(); } } }, "Đọc sai? Sửa"))))
        : h("p", { class: "muted", style: "margin-top:12px" }, "Không có tên nào lặp lại đủ nhiều. Thử giảm số lần trong Nâng cao.")) : null));
  }
  paint(); paintSug();
  return () => { alive = false; };
}
