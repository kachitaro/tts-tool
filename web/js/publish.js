// Đăng bài lên laptop: hộp thoại "Đăng…" (chọn kênh, nội dung, giờ) và danh sách "Lịch đăng".
// Máy này chỉ gửi file + lịch sang laptop (qua /api/publish*); laptop tự đăng đúng giờ kể cả khi máy này tắt.
import { h, fmtDate } from "./dom.js";
import { getJSON, sendJSON, api } from "./api.js";
import { modal, showError, toast, confirmBox } from "./ui.js";

const pad = (n) => String(n).padStart(2, "0");
const toLocalInput = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const newId = () => (globalThis.crypto?.randomUUID?.() ?? `p${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`);
const CHANNEL_NAMES = { telegram: "Telegram", discord: "Discord", mastodon: "Mastodon" };
const STATUS = { pending: "Đang chờ", running: "Đang đăng", done: "Đã đăng", error: "Lỗi", missed: "Bị lỡ (quá giờ)" };

/** source: { kind: "history", id } | { kind: "chapter", book, n } | { kind: "export", book, name } */
export async function openPublish(source, caption = "") {
  let chans;
  try { chans = (await getJSON("/api/publish/channels")).filter((c) => c.configured); } catch (e) { return showError(e); }
  if (!chans.length) return toast("Laptop chưa cấu hình kênh nào. Điền secrets.json trên laptop (xem README, mục Đăng bài từ xa).", { kind: "error", ms: 8000 });
  const id = newId(); // một id cho cả hộp thoại: bấm lại / gửi lại khi rớt mạng không đăng đôi
  const boxes = chans.map((c, i) => h("input", { type: "checkbox", value: c.id, checked: i === 0 }));
  const text = h("textarea", { rows: 4, maxLength: 4000, placeholder: "Nội dung bài đăng" }, caption);
  const when = h("input", { type: "datetime-local", value: toLocalInput(new Date()) });
  const send = h("button", { class: "btn primary", type: "button", onclick: submit }, "Gửi lên laptop");
  const m = modal([
    h("h3", {}, "Đăng lên mạng xã hội"),
    h("div", { class: "stack", style: "--gap:12px" },
      h("div", {}, h("label", { class: "field" }, "Đăng lên"), h("div", { class: "row" }, ...chans.map((c, i) => h("label", { class: "switch" }, boxes[i], CHANNEL_NAMES[c.id] || c.id)))),
      h("div", {}, h("label", { class: "field" }, "Nội dung"), text),
      h("div", {}, h("label", { class: "field" }, "Giờ đăng"), when,
        h("div", { class: "hint" }, "Giờ hiện tại = đăng ngay khi laptop nhận được. Laptop tự đăng đúng giờ, máy này tắt cũng không sao.")),
      h("div", { class: "row end" }, h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Huỷ"), send)),
  ]);
  async function submit() {
    const picked = boxes.filter((b) => b.checked).map((b) => b.value);
    const t = new Date(when.value).getTime();
    if (!picked.length) return toast("Chưa chọn kênh nào.", { kind: "error" });
    if (Number.isNaN(t)) return toast("Giờ đăng không hợp lệ.", { kind: "error" });
    send.disabled = true; send.textContent = "Đang gửi…";
    try {
      await sendJSON("/api/publish/posts", { id, source, channels: picked, caption: text.value, when: t / 1000 });
      m.close();
      toast(`Đã gửi lên laptop, sẽ đăng lúc ${fmtDate(t)}.`);
    } catch (e) { send.disabled = false; send.textContent = "Gửi lên laptop"; showError(e); }
  }
}

export async function openSchedule() {
  const box = h("div", { class: "stack", style: "--gap:10px" }, h("p", { class: "muted" }, "Đang tải…"));
  const m = modal([h("h3", {}, "Lịch đăng"), box, h("div", { class: "row end", style: "margin-top:14px" },
    h("button", { class: "btn", type: "button", onclick: paint }, "Tải lại"), h("button", { class: "btn primary", type: "button", onclick: () => m.close() }, "Xong"))], { wide: true });
  async function paint() {
    let posts;
    try { posts = await getJSON("/api/publish/posts"); } catch (e) { box.replaceChildren(h("p", { class: "muted" }, "Không lấy được lịch từ laptop.")); return showError(e); }
    const row = (p) => {
      const fails = Object.entries(p.results || {}).filter(([, r]) => !r.ok);
      return h("div", { class: "hitem" },
        h("div", { class: "muted" }, `${fmtDate(p.when * 1000)} · ${p.channels.map((c) => CHANNEL_NAMES[c] || c).join(", ")} · ${STATUS[p.status] || p.status}${p.attempts && p.status === "pending" ? ` (thử lại lần ${p.attempts})` : ""}`),
        h("div", { class: "txt" }, p.caption || p.filename || "(không có nội dung)"),
        ...fails.map(([c, r]) => h("div", { class: "hint warnc" }, `${CHANNEL_NAMES[c] || c}: ${r.error}`)),
        h("div", { class: "row" },
          (p.status === "error" || p.status === "missed") && h("button", { class: "btn small", type: "button", onclick: async () => {
            try { await api(`/api/publish/posts/${encodeURIComponent(p.id)}/retry`, { method: "POST" }); paint(); } catch (e) { showError(e); } } }, "Đăng lại"),
          p.status !== "running" && h("button", { class: "btn small danger", type: "button", onclick: async () => {
            if (p.status === "pending" && !(await confirmBox({ title: "Xoá bài đang chờ?", body: "Bài sẽ không được đăng.", ok: "Xoá", danger: true }))) return;
            try { await api(`/api/publish/posts/${encodeURIComponent(p.id)}`, { method: "DELETE" }); paint(); } catch (e) { showError(e); } } }, "Xoá")));
    };
    box.replaceChildren(...(posts.length ? [...posts].reverse().map(row) : [h("p", { class: "muted" }, "Chưa có bài nào.")]));
  }
  paint();
}
