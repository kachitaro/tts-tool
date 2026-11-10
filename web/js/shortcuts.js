// Phím tắt toàn trang: Ctrl+Enter đọc, Space phát/dừng, ? mở bảng phím tắt. Esc đóng hộp thoại do ui.js / menu.js / app.js lo.
import { h, $ } from "./dom.js";
import { modal } from "./ui.js";
import { toggle } from "./player.js";
import { appApi, inApp } from "./appenv.js";

export const SHORTCUTS = [
  ["Ctrl + Enter", "Đọc văn bản đang gõ (ở trang Đọc văn bản)"],
  ["Space", "Phát hoặc dừng âm thanh ở thanh phát (khi bạn không đang gõ chữ)"],
  ["Esc", "Đóng hộp thoại, menu hoặc ngăn Lịch sử"],
  ["?", "Mở bảng phím tắt này"],
];

/** Đang gõ chữ hoặc đang đứng trên một điều khiển tự dùng phím Space / Enter? */
export function typing(el) {
  if (!el) return false;
  return el.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON|A|SUMMARY)$/.test(el.tagName) || el.getAttribute?.("role") === "radio";
}

const APP_SHORTCUTS = [
  ["F5 hoặc Ctrl + R", "Tải lại trang"],
  ["Ctrl + = / Ctrl + −", "Phóng to / thu nhỏ chữ"],
  ["Ctrl + 0", "Về cỡ chữ ban đầu"],
];

export function showShortcuts() {
  const m = modal([h("h3", {}, "Phím tắt"),
    h("dl", { class: "kv" }, ...[...SHORTCUTS, ...(inApp() ? APP_SHORTCUTS : [])].flatMap(([k, d]) => [h("dt", {}, h("kbd", {}, k)), h("dd", {}, d)])),
    h("div", { class: "row end", style: "margin-top:16px" }, h("button", { class: "btn primary", onclick: () => m.close() }, "Xong"))]);
}

/** Trong cửa sổ app không có thanh địa chỉ nên phải tự làm các phím của trình duyệt: tải lại, phóng to / thu nhỏ. */
function initAppKeys() {
  const zoom = async (how) => { const api = await appApi(); if (api) api.zoom(how); };
  document.addEventListener("keydown", (e) => {
    const ctrl = e.ctrlKey || e.metaKey;
    if (e.key === "F5" || (ctrl && e.key.toLowerCase() === "r")) { e.preventDefault(); location.reload(); }
    else if (ctrl && (e.key === "=" || e.key === "+")) { e.preventDefault(); zoom("in"); }
    else if (ctrl && (e.key === "-" || e.key === "_")) { e.preventDefault(); zoom("out"); }
    else if (ctrl && e.key === "0") { e.preventDefault(); zoom("reset"); }
  });
  document.addEventListener("wheel", (e) => { if (e.ctrlKey) { e.preventDefault(); zoom(e.deltaY < 0 ? "in" : "out"); } }, { passive: false });
}

export function initShortcuts() {
  if (inApp()) initAppKeys();
  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented) return;
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && location.hash.startsWith("#/doc")) {
      const b = $("#goBtn"); if (b && !b.disabled) { e.preventDefault(); b.click(); }
    } else if (e.key === " " && !e.ctrlKey && !e.metaKey && !e.altKey && !typing(e.target) && !$("#modalHost .modal")) {
      e.preventDefault(); toggle();
    } else if (e.key === "?" && !typing(e.target) && !$("#modalHost .modal")) {
      e.preventDefault(); showShortcuts();
    }
  });
}
