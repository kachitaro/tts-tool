// Điều hướng theo dấu # (không tải lại trang). Mỗi màn: mount(root) → hàm dọn dẹp (tuỳ chọn).
const routes = new Map();
export const pending = { reuse: null };   // "Dùng lại" từ Lịch sử → màn Đọc văn bản nhận
let cleanup = null, current = null;

export const route = (path, mount) => routes.set(path, mount);
export const where = () => location.hash.replace(/^#/, "") || "/";

export function go(path) {
  if (where() === path) render(); else location.hash = path;
}

export function render() {
  const path = where();
  const mount = routes.get(path) || routes.get("/");
  const root = document.getElementById("view");
  if (typeof cleanup === "function") cleanup();
  root.replaceChildren();
  cleanup = mount(root);
  if (current !== path) window.scrollTo(0, 0);
  current = path;
  document.dispatchEvent(new CustomEvent("gv:route", { detail: path }));
}

export function startRouter() {
  window.addEventListener("hashchange", render);
  render();
}
