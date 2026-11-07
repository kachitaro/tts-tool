// Giọng đọc: hai nhóm "Của tôi" (ghi âm, pha) và "Có sẵn". Thêm / sửa giọng và pha giọng dùng trình cũ ở bước này.
import { h } from "../dom.js";
import { api } from "../api.js";
import { engines, voices, resetVoices, prefs } from "../store.js";
import { VoicePicker, isMine, forgetPreview, keyOf, displayName } from "../voicepicker.js";
import { showError, toast, confirmBox } from "../ui.js";
import { go } from "../router.js";

export function mountVoices(root) {
  const body = h("div", {}, h("p", { class: "muted" }, "Đang tải danh sách giọng…"));
  root.append(
    h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("span", {}, "Giọng đọc")),
    h("div", { class: "row", style: "justify-content:space-between" }, h("h2", {}, "Giọng đọc"),
      h("div", { class: "row" },
        h("button", { class: "btn primary", onclick: () => { location.href = "/legacy#lib-add"; } }, "🎙️ Thêm giọng từ file ghi âm"),
        h("button", { class: "btn", onclick: () => { location.href = "/legacy#mix"; } }, "🎚️ Pha giọng mới"))),
    h("p", { class: "lead" }, "Bấm ▶ để nghe thử. Bấm ♥ để đánh dấu giọng bạn hay dùng."), body);
  let alive = true;
  (async () => {
    try {
      const [eng, vs] = await Promise.all([engines(), voices()]);
      if (!alive) return;
      const actions = (v) => [
        h("button", { class: "btn small", disabled: v.usable === false, onclick: () => { prefs.set("engine", v.engine); prefs.set("voice:" + v.engine, v.id); toast(`Đã chọn giọng ${displayName(v)} để đọc.`); go("/doc"); } }, "Dùng để đọc"),
        isMine(v) && h("button", { class: "btn small", title: "Sửa tên, ghi chú", onclick: () => { location.href = "/legacy#lib"; } }, "Sửa"),
        isMine(v) && v.id.startsWith("lib:") && h("button", { class: "btn small danger", onclick: async () => {
          if (!(await confirmBox({ title: `Xoá giọng “${displayName(v)}”?`, body: "Giọng sẽ bị xoá khỏi máy và không khôi phục được. Sách nói và bản đọc đã tạo vẫn giữ nguyên.", ok: "Xoá giọng", danger: true }))) return;
          try { await api("/api/library/" + v.id.slice(4), { method: "DELETE" }); forgetPreview(v); resetVoices(); toast("Đã xoá giọng."); body.replaceChildren(); mountInto(); } catch (e) { showError(e); }
        } }, "Xoá"),
      ];
      const mountInto = async () => { const fresh = await voices(true); body.replaceChildren(VoicePicker({ voices: fresh, engines: eng, actions, tall: true })); };
      body.replaceChildren(VoicePicker({ voices: vs, engines: eng, actions, tall: true }));
    } catch (e) { body.replaceChildren(); showError(e); }
  })();
  return () => { alive = false; };
}
