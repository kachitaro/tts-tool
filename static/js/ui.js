// Thành phần giao diện dùng chung: thông báo, hộp thoại, hộp xác nhận.
import { h, $ } from "./dom.js";
import { explain } from "./errors.js";

let toastTimer;
export function toast(content, { kind = "info", ms = kind === "error" ? 14000 : 3500 } = {}) {
  const host = $("#toastHost");
  host.replaceChildren(h("div", { class: "toast " + kind, role: kind === "error" ? "alert" : "status" }, content));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => host.replaceChildren(), ms);
}

/** Báo lỗi bằng lời thường; lỗi gốc nằm trong "Xem chi tiết". */
export function showError(err, { retry } = {}) {
  const e = explain(err);
  toast([
    h("b", {}, e.title),
    e.tip && h("div", {}, e.tip),
    retry && h("div", { class: "row", style: "margin-top:10px" }, h("button", { class: "btn small", onclick: () => { $("#toastHost").replaceChildren(); retry(); } }, "Thử lại")),
    e.detail && h("details", { class: "notice" }, h("summary", {}, "Xem chi tiết"), h("code", {}, e.detail)),
  ], { kind: "error" });
  return e;
}

/** Hộp thoại. content: Node | Node[]. Trả { close, el }. Esc hoặc bấm nền để đóng. */
export function modal(content, { wide = false, onclose } = {}) {
  const host = $("#modalHost");
  const close = () => { host.replaceChildren(); document.removeEventListener("keydown", onKey); onclose && onclose(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const el = h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" }, content);
  host.replaceChildren(h("div", { class: "scrim", onclick: close }), el);
  document.addEventListener("keydown", onKey);
  el.querySelector("input, textarea, select, button")?.focus?.();
  return { close, el };
}

/** Hộp xác nhận nói rõ hậu quả → Promise<boolean>. */
export function confirmBox({ title, body, ok = "Đồng ý", cancel = "Để lại", danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } m.close(); };
    const m = modal([
      h("h3", {}, title), body && h("p", {}, body),
      h("div", { class: "row end", style: "margin-top:18px" },
        h("button", { class: "btn", onclick: () => finish(false) }, cancel),
        h("button", { class: "btn primary" + (danger ? " danger-fill" : ""), onclick: () => finish(true) }, ok)),
    ], { onclose: () => { if (!done) { done = true; resolve(false); } } });
  });
}

/** Khung xám nhấp nháy giữ chỗ lúc đang tải (thay cho chữ "Đang tải…"). rows: số dòng; cards: dựng thành thẻ. */
export function skeleton(rows = 3, { cards = false } = {}) {
  return h("div", { class: "skel" + (cards ? " cards" : ""), role: "status", "aria-busy": "true", "aria-label": "Đang tải" },
    ...Array.from({ length: rows }, (_, i) => h("div", { class: "skel-row", style: `width:${cards ? 100 : [92, 78, 85, 64][i % 4]}%` })));
}

/** Công tắc bật/tắt kiểu điện thoại. */
export function switchEl(label, checked, onchange) {
  const input = h("input", { type: "checkbox", checked: !!checked, onchange: () => onchange(input.checked) });
  return h("label", { class: "switch" }, input, label);
}
