// Sửa cách đọc tên riêng: mỗi mục = cụm chữ + "đọc thành…" + dừng trước / sau (giây).
import { h } from "./dom.js";
import { modal, showError, switchEl } from "./ui.js";

export const emptyEntry = (match = "") => ({ match, replace: "", pause_before: 0, pause_after: 0, whole_word: true, case_sensitive: false });

export function describe(e) {
  const parts = [];
  if (e.replace) parts.push(`đọc là “${e.replace}”`);
  if (e.pause_before) parts.push(`dừng ${e.pause_before} giây trước`);
  if (e.pause_after) parts.push(`dừng ${e.pause_after} giây sau`);
  return parts.join(" · ") || "đọc bình thường";
}

/** Hộp "Đọc sai? Sửa" cho một mục → Promise<entry|null>. */
export function editEntry(entry, { title = "Cách đọc tên này", canDelete = false } = {}) {
  return new Promise((resolve) => {
    const e = { ...entry };
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } m.close(); };
    const num = (key) => h("input", { type: "number", min: 0, max: 5, step: 0.1, value: e[key], style: "max-width:120px", oninput: (ev) => { e[key] = Math.round((+ev.target.value || 0) * 10) / 10; } });
    const name = h("input", { type: "text", value: e.match, placeholder: "Ví dụ: Tiêu Viêm", oninput: (ev) => { e.match = ev.target.value; } });
    const rep = h("input", { type: "text", value: e.replace, placeholder: "Để trống nếu giữ nguyên chữ", oninput: (ev) => { e.replace = ev.target.value; } });
    const m = modal([
      h("h3", {}, title),
      h("div", { class: "stack", style: "--gap:14px" },
        h("div", {}, h("label", { class: "field" }, "Tên hoặc cụm chữ trong truyện"), name),
        h("div", {}, h("label", { class: "field" }, "Đọc thành…"), rep, h("div", { class: "hint" }, "Gõ cách đọc đúng, ví dụ “Tiêu Diễm”. Để trống nếu chữ đã đúng mà chỉ cần ngắt nghỉ.")),
        h("div", { class: "two" },
          h("div", {}, h("label", { class: "field" }, "Dừng trước (giây)"), num("pause_before")),
          h("div", {}, h("label", { class: "field" }, "Dừng sau (giây)"), num("pause_after"))),
        h("div", { class: "hint", style: "margin-top:-6px" }, "Tên Hán Việt hay bị đọc liền nhau; dừng khoảng 0,2 giây thường nghe tự nhiên hơn."),
        h("details", { class: "adv", style: "margin:0" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body stack", style: "--gap:10px" },
          switchEl("Chỉ khớp cả từ (không khớp một phần của từ khác)", e.whole_word, (on) => { e.whole_word = on; }),
          switchEl("Phân biệt chữ hoa và chữ thường", e.case_sensitive, (on) => { e.case_sensitive = on; }))),
        h("div", { class: "row end" },
          canDelete && h("button", { class: "btn danger", style: "margin-right:auto", onclick: () => done({ ...e, _delete: true }) }, "Xoá mục này"),
          h("button", { class: "btn", onclick: () => done(null) }, "Huỷ"),
          h("button", { class: "btn primary", onclick: () => {
            if (!e.match.trim()) return name.focus();
            if (!e.replace.trim() && !e.pause_before && !e.pause_after) return showError(new Error("Hãy điền “đọc thành…” hoặc chọn khoảng dừng."));
            done(e);
          } }, "Lưu"))),
    ], { onclose: () => { if (!settled) { settled = true; resolve(null); } } });
  });
}
