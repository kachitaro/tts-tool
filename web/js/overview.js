// Trạng thái chung (GET /api/overview): thanh trên cùng, màn chính, danh sách sách nói. Hỏi định kỳ, báo khi tạo xong.
import { getJSON } from "./api.js";
import { h } from "./dom.js";
import { getSettings } from "./defaults.js";
import { inApp } from "./appenv.js";
import { toast } from "./ui.js";

export const overview = { data: null };
let timer = null, lastFinish = null;

export async function refreshOverview() {
  clearTimeout(timer);
  try {
    const d = await getJSON("/api/overview");
    overview.data = d;
    const seq = d.queue.finish.seq;
    if (lastFinish !== null && seq > lastFinish) announceFinish(d.queue.finish);
    lastFinish = seq;
    document.dispatchEvent(new CustomEvent("gv:overview", { detail: d }));
  } catch { /* tool tạm không trả lời: lần sau thử lại */ }
  timer = setTimeout(refreshOverview, overview.data && overview.data.current ? 3000 : 8000);
}

function announceFinish(f) {
  const trial = !!f.trial;   // vừa tạo thử N chương: tool đã dừng, chờ người dùng nghe thử
  const body = trial ? `${f.title || "Sách nói"}: đã xong ${f.done} chương thử. Nghe thử rồi bấm Tạo tiếp.`
    : `${f.title || "Sách nói"}: xong ${f.done} chương` + (f.errors ? `, ${f.errors} chương lỗi` : "");
  toast(trial ? [h("b", {}, `Đã xong ${f.done} chương thử. `), "Nghe thử rồi bấm Tạo tiếp.", h("div", { class: "row", style: "margin-top:10px" }, h("a", { class: "btn small primary", href: "#/sach/" + encodeURIComponent(f.book) }, "Mở truyện"))] : ["Tạo sách nói xong. ", body],
    { kind: f.errors && !trial ? "error" : "info", ms: 12000 });
  desktopNotice(trial ? "Giọng Việt — đã xong chương thử" : "Giọng Việt — tạo xong", body);
}

/** Thông báo của trình duyệt. Trong app cửa sổ riêng không dùng (webview thường không có), server đã gọi notify-send. */
async function desktopNotice(title, body) {
  if (inApp() || !("Notification" in window) || Notification.permission !== "granted") return;
  try { if ((await getSettings(true)).notify === false) return; } catch { /* không đọc được cài đặt: cứ báo */ }
  new Notification(title, { body });
}

/** Xin quyền thông báo của trình duyệt (gọi khi người dùng chủ động bấm một nút bắt đầu việc dài). */
export async function askNotifyPermission() {
  if (inApp() || !("Notification" in window) || Notification.permission !== "default") return;
  try { if ((await getSettings()).notify === false) return; } catch { /* cứ hỏi */ }
  Notification.requestPermission();
}
