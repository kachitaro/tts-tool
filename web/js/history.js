// Ngăn kéo "Lịch sử": mọi bản đã đọc (đọc một người và nhiều người), nghe lại, tải về, dùng lại, xoá.
import { h, $, fmtDate } from "./dom.js";
import { api, getJSON } from "./api.js";
import { play } from "./player.js";
import { showError, toast, confirmBox } from "./ui.js";
import { engines, voices } from "./store.js";
import { pending, go } from "./router.js";

const drawer = () => $("#drawer");

export function closeHistory() {
  drawer().classList.remove("open"); drawer().setAttribute("aria-hidden", "true"); $("#scrim").classList.add("hidden");
}

export async function openHistory() {
  drawer().classList.add("open"); drawer().setAttribute("aria-hidden", "false"); $("#scrim").classList.remove("hidden");
  drawer().replaceChildren(h("header", {}, h("h3", {}, "Lịch sử")), h("div", { class: "body" }, h("p", { class: "muted" }, "Đang tải…")));
  await paint();
}

async function paint() {
  let items, eng, vs;
  try { [items, eng, vs] = await Promise.all([getJSON("/api/history"), engines(), voices().catch(() => [])]); }
  catch (e) { showError(e); return; }
  const title = (m) => {
    if (m.kind === "dialogue") return `Nhiều người đọc · ${m.lines} dòng · ${m.seconds} giây`;
    const v = vs.find((x) => x.engine === m.engine && x.id === m.voice);
    const who = m.cloned_ref ? "giọng ghi âm" : (m.voice_label || (v && (v.name || v.label)) || m.voice || "giọng mặc định") + (m.voice_deleted ? " (đã xoá)" : "");
    return `${eng[m.engine]?.local ? "Giọng trên máy" : "Giọng online"} · ${who}`;
  };
  const row = (m) => {
    const url = `/api/history/${m.id}/audio`;
    const links = [[m.ext, url]];
    if (m.has_mp3 && m.ext !== "mp3") links.push(["mp3", url + "?fmt=mp3"]);
    return h("div", { class: "hitem" },
      h("div", { class: "muted" }, `${fmtDate(m.created_at)} · ${title(m)}`),
      h("div", { class: "txt" }, m.kind === "dialogue" ? m.script : m.text),
      h("div", { class: "row" },
        h("button", { class: "play", "aria-label": "Nghe lại", onclick: () => play({ src: url, title: (m.kind === "dialogue" ? m.script : m.text).slice(0, 60), sub: title(m) }) }, "▶"),
        h("button", { class: "btn small", onclick: () => { pending.reuse = m; closeHistory(); go("/doc"); } }, "Dùng lại"),
        ...links.map(([ext, href]) => h("a", { class: "btn small", href, download: `giong-noi.${ext}` }, "Tải " + ext.toUpperCase())),
        h("button", { class: "btn small danger", onclick: async () => {
          try { await api("/api/history/" + m.id, { method: "DELETE" }); paint(); } catch (e) { showError(e); } } }, "Xoá")));
  };
  drawer().replaceChildren(
    h("header", {}, h("h3", { style: "flex:1" }, "Lịch sử"),
      h("button", { class: "btn small danger", disabled: !items.length, onclick: async () => {
        if (!(await confirmBox({ title: "Xoá toàn bộ lịch sử?", body: "Các bản đã đọc sẽ bị xoá và không khôi phục được. Sách nói không bị ảnh hưởng.", ok: "Xoá tất cả", danger: true }))) return;
        try { await api("/api/history", { method: "DELETE" }); toast("Đã xoá lịch sử."); paint(); } catch (e) { showError(e); } } }, "Xoá tất cả"),
      h("button", { class: "btn small", onclick: closeHistory }, "Đóng")),
    h("div", { class: "body" }, h("p", { class: "muted" }, "Những lần đọc gần đây (giữ 50 bản mới nhất)."),
      ...(items.length ? items.map(row) : [h("p", { class: "muted" }, "Chưa có bản nào. Đọc thử một đoạn văn để bắt đầu.")])));
}
