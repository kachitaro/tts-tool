// Hộp thoại "Cài đặt chung". Thuật ngữ kỹ thuật chỉ nằm trong khối "Nâng cao".
import { h } from "./dom.js";
import { getJSON, sendJSON } from "./api.js";
import { modal, switchEl, showError, toast } from "./ui.js";
import { engines, voices, prefs } from "./store.js";
import { getSettings, saveDefaultVoice, effectiveDefault } from "./defaults.js";
import { VoicePicker, keyOf, displayName, metaLine } from "./voicepicker.js";
import { askNotifyPermission } from "./overview.js";

export async function openSettings() {
  let q, eng, vs, st;
  try { [q, eng, vs, st] = await Promise.all([getJSON("/api/queue"), engines(), voices(), getSettings(true)]); } catch (e) { return showError(e); }
  const defBox = h("div", {});
  const paintDefault = () => {
    const d = effectiveDefault(vs, eng, st);
    defBox.replaceChildren(
      h("label", { class: "field" }, "Giọng mặc định"),
      h("div", { class: "vcurrent" },
        h("div", { class: "vinfo" }, h("b", {}, d.voice ? displayName(d.voice) : "Chưa có giọng nào"), d.voice && h("div", { class: "muted" }, metaLine(d.voice, eng))),
        h("button", { type: "button", class: "btn small", onclick: choose }, "Đổi"),
        d.source === "chosen" && h("button", { type: "button", class: "btn small", onclick: async () => {
          try { st = await saveDefaultVoice(null); paintDefault(); } catch (e) { showError(e); } } }, "Để tool tự chọn")),
      h("div", { class: "hint" }, d.source === "chosen" ? "Dùng cho đọc văn bản và truyện mới." : "Bạn chưa chọn nên tool dùng giọng có sao ★ đầu tiên trong nhóm giọng trên máy (không có thì giọng đầu danh sách)."));
  };
  const choose = () => {
    const p = modal([h("h3", {}, "Chọn giọng mặc định"), VoicePicker({ voices: vs, engines: eng, value: (() => { const d = effectiveDefault(vs, eng, st).voice; return d ? keyOf(d) : ""; })(),
      only: (v) => v.usable !== false, onPick: async (v) => {
        try { st = await saveDefaultVoice(v); p.close(); toast(`Giọng mặc định: ${displayName(v)}.`); openSettings(); } catch (e) { showError(e); } } }),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => { p.close(); openSettings(); } }, "Đóng"))], { wide: true });
  };
  paintDefault();
  const m = modal([
    h("h3", {}, "Cài đặt chung"),
    h("div", { class: "stack", style: "--gap:16px" },
      defBox,
      switchEl("Giữ máy không đi ngủ khi đang tạo sách nói", q.inhibit_sleep, async (on) => {
        try { await sendJSON("/api/queue/settings", { inhibit_sleep: on }); } catch (e) { showError(e); }
      }),
      h("div", { class: "hint", style: "margin-top:-8px" }, q.inhibit === "unavailable" ? "Máy này không hỗ trợ tính năng này, tool sẽ bỏ qua." : "Tạo cả bộ truyện mất nhiều giờ; máy sẽ không tự tắt màn hình đi ngủ giữa chừng."),
      switchEl("Báo cho tôi khi tạo xong (hiện thông báo trên màn hình)", prefs.get("notify", true), (on) => { prefs.set("notify", on); if (on) askNotifyPermission(); }),
      h("details", { class: "adv", style: "margin:0" }, h("summary", {}, "Nâng cao"),
        h("div", { class: "adv-body stack", style: "--gap:10px" },
          ...Object.values(eng).filter((e) => e.available).map((e) => h("div", { class: "muted" }, `${e.name}${e.precision ? " · độ chính xác " + e.precision : ""}`)),
          h("div", { class: "muted" }, "Muốn đổi độ chính xác của giọng trên máy: đặt biến môi trường VIENEU_PRECISION (fp32 hoặc int8) khi mở tool. Mặc định tool tự chọn theo máy."),
          h("div", { class: "muted" }, "Dữ liệu (giọng, lịch sử, truyện) nằm trong thư mục data/ cạnh tool."),
          h("a", { href: "/legacy" }, "Mở giao diện cũ (đủ mọi tuỳ chọn)"))),
      h("div", { class: "row end" }, h("button", { class: "btn primary", onclick: () => m.close() }, "Xong"))),
  ]);
}
