// Lấy danh sách File từ sự kiện thả. Trình duyệt thường (và Chromium) đưa File sẵn trong dataTransfer.files; riêng WebKitGTK
// (backend của app cửa sổ riêng) không đưa File khi kéo từ ngoài vào, nên desktop/app.py giữ đường dẫn file vừa thả và phát lại qua
// js_api dropped_files() → mỗi file có một URL dùng một lần (/_app/drop/<mã>) để đọc bằng fetch.
import { appApi, inApp } from "./appenv.js";

export async function filesFromDrop(e) {
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) return [...e.dataTransfer.files];
  if (!inApp() || ![...((e.dataTransfer && e.dataTransfer.types) || [])].includes("text/uri-list")) return [];   // kéo chữ / ảnh trong trang: không phải file
  const api = await appApi();
  if (!api) return [];
  const list = await api.dropped_files();
  const out = [];
  for (const d of list) {
    const blob = await (await fetch(d.url)).blob();
    out.push(new File([blob], d.name, { type: d.type || blob.type, lastModified: d.mtime ? d.mtime * 1000 : Date.now() }));
  }
  return out;
}

/** Chặn trình duyệt tự mở file khi thả trượt ra ngoài vùng thả (mặc định nó rời khỏi trang sang file đó). */
export function guardStrayDrops() {
  for (const ev of ["dragover", "drop"]) window.addEventListener(ev, (e) => { if (e.dataTransfer && [...(e.dataTransfer.types || [])].some((t) => t === "Files" || t === "text/uri-list")) e.preventDefault(); });
}
