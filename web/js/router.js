// Điều hướng theo dấu # (không tải lại trang). Mỗi màn: mount(root, params) → hàm dọn dẹp (tuỳ chọn).
// Đường dẫn có tham số: "/sach/:id/kiem-tra". Đường dẫn chính xác được ưu tiên hơn đường dẫn có tham số.
import { scrollPage } from "./dom.js";
const routes = [];
export const pending = { reuse: null, voiceAction: null };   // "Dùng lại" từ Lịch sử → màn Đọc văn bản nhận
let cleanup = null, current = null;

export const route = (path, mount) => routes.push({ parts: path.split("/").filter(Boolean), mount });
export const where = () => location.hash.replace(/^#/, "") || "/";

function match(path) {
  const segs = path.split("/").filter(Boolean);
  let best = null;
  for (const r of routes) {
    if (r.parts.length !== segs.length) continue;
    const params = {};
    let exact = 0, ok = true;
    r.parts.forEach((p, i) => { if (p.startsWith(":")) params[p.slice(1)] = decodeURIComponent(segs[i]); else if (p === segs[i]) exact++; else ok = false; });
    if (ok && (!best || exact > best.exact)) best = { r, params, exact };
  }
  return best || routes.map((r) => ({ r, params: {}, exact: 0 })).find((x) => x.r.parts.length === 0);
}

export function go(path) {
  if (where() === path) render(); else location.hash = path;
}

export function render() {
  const path = where();
  const hit = match(path);
  const root = document.getElementById("view");
  if (typeof cleanup === "function") cleanup();
  root.replaceChildren();
  cleanup = hit.r.mount(root, hit.params);
  if (current !== path) scrollPage(0);
  current = path;
  document.dispatchEvent(new CustomEvent("gv:route", { detail: path }));
}

export function startRouter() {
  window.addEventListener("hashchange", render);
  render();
}
