// Giọng đọc: lưới thẻ giọng chia nhóm Yêu thích / Giọng của tôi / Giọng có sẵn; thêm giọng từ ghi âm; pha giọng.
import { h } from "../dom.js";
import { api, sendJSON } from "../api.js";
import { explain } from "../errors.js";
import { engines, voices, resetVoices, prefs } from "../store.js";
import { VoicePicker, isMine, forgetPreview, displayName } from "../voicepicker.js";
import { skeleton, showError, toast, confirmBox, modal } from "../ui.js";
import { go, pending } from "../router.js";
import { openAddVoice, choiceSeg, GENDERS, REGIONS, AGES } from "./voice-add.js";

/** Đổi tên (và giới tính, vùng miền) một giọng của tôi. */
function renameDialog(v, done) {
  const S = { name: displayName(v), gender: v.gender || "", region: v.region || "", age: v.age_source === "user" ? v.age : "", err: "", busy: false };
  const box = h("div", {});
  const m = modal(box);
  const draw = () => box.replaceChildren(
    h("h3", {}, "Đổi tên giọng"),
    h("div", { class: "stack" },
      h("div", {}, h("label", { class: "field", for: "rnName" }, "Tên giọng"), h("input", { id: "rnName", type: "text", maxlength: 60, value: S.name, oninput: (e) => { S.name = e.target.value; } })),
      h("div", { class: "two" }, choiceSeg("Giọng nam hay nữ?", GENDERS, () => S.gender, (x) => { S.gender = x; }), choiceSeg("Giọng vùng nào?", REGIONS, () => S.region, (x) => { S.region = x; })),
      choiceSeg("Giọng nghe bao nhiêu tuổi?", AGES, () => S.age, (x) => { S.age = x; }),
      S.err && h("div", { class: "notice err", role: "alert" }, S.err)),
    h("div", { class: "row end", style: "margin-top:18px" },
      h("button", { type: "button", class: "btn", onclick: () => m.close() }, "Huỷ"),
      h("button", { type: "button", class: "btn primary", disabled: S.busy, onclick: save }, "Lưu")));
  async function save() {
    if (!S.name.trim()) { S.err = "Tên giọng không được để trống."; return draw(); }
    S.busy = true;
    const fd = new FormData();
    fd.append("name", S.name.trim()); fd.append("gender", S.gender); fd.append("region", S.region); fd.append("age", S.age);
    try { await api("/api/library/" + v.id.slice(4), { method: "PATCH", body: fd }); resetVoices(); forgetPreview(v); m.close(); done(); }
    catch (e) { const x = explain(e); S.err = x.title + (x.tip ? " " + x.tip : ""); S.busy = false; draw(); }
  }
  draw();
}

/** Đổi độ tuổi của một giọng (giọng có sẵn: "Dùng gợi ý" = bỏ lựa chọn của bạn, về gợi ý của tool). */
function ageDialog(v, done) {
  const preset = !v.id.startsWith("lib:");
  const opts = AGES.map(([k, t]) => [k, k === "" ? (preset ? "Dùng gợi ý" : "Không rõ") : t]);
  const S = { age: v.age_source === "user" ? v.age : "" };
  const box = h("div", {});
  const m = modal(box);
  const draw = () => box.replaceChildren(
    h("h3", {}, `Độ tuổi của giọng ${displayName(v)}`),
    h("p", { class: "muted" }, preset && v.age_source === "suggested" ? "Tool đang gợi ý theo phong cách giọng, chưa phải nghe giọng thật. Bạn nghe thử rồi chọn lại cho đúng." : "Chọn độ tuổi nghe giống nhất. Dàn giọng nhân vật dùng nhãn này để chọn giọng đúng tuổi."),
    choiceSeg("Giọng nghe bao nhiêu tuổi?", opts, () => S.age, (x) => { S.age = x; }),
    h("div", { class: "row end", style: "margin-top:18px" }, h("button", { type: "button", class: "btn", onclick: () => m.close() }, "Huỷ"), h("button", { type: "button", class: "btn primary", onclick: save }, "Lưu")));
  async function save() {
    try { await sendJSON("/api/voices/age", { engine: v.engine, voice: v.id, age: S.age }, "PUT"); resetVoices(); forgetPreview(v); m.close(); done(); }
    catch (e) { showError(e); }
  }
  draw();
}

export function mountVoices(root) {
  const body = h("div", {}, skeleton(6, { cards: true }));
  let eng = {}, alive = true;
  root.append(
    h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("span", {}, "Giọng đọc")),
    h("div", { class: "row", style: "justify-content:space-between" }, h("h2", {}, "Giọng đọc"),
      h("div", { class: "row" },
        h("button", { class: "btn primary", id: "addVoice", onclick: () => openAddVoice({ engines: eng, onSaved: (meta) => { toast(`Đã thêm giọng “${meta.name}”. Bấm ▶ để nghe thử.`); refresh(); } }) }, "🎙️ Thêm giọng từ file ghi âm"),
        h("a", { class: "btn", id: "mixVoice", href: "#/giong/pha" }, "🎚️ Pha giọng mới"))),
    h("p", { class: "lead" }, "Bấm ▶ để nghe thử. Bấm ★ để đánh dấu giọng bạn hay dùng."), body);

  const menu = (v) => [
    { label: "Dùng để đọc", onclick: () => { if (v.usable === false) return toast(v.unusable_reason || "Giọng này chưa dùng được.", { kind: "error" }); prefs.set("engine", v.engine); prefs.set("voice:" + v.engine, v.id); toast(`Đã chọn giọng ${displayName(v)} để đọc.`); go("/doc"); } },
    { label: "Đổi độ tuổi…", onclick: () => ageDialog(v, () => { toast("Đã lưu độ tuổi."); refresh(); }) },
    isMine(v) && v.id.startsWith("lib:") && { label: "Đổi tên", onclick: () => renameDialog(v, () => { toast("Đã lưu."); refresh(); }) },
    isMine(v) && v.id.startsWith("lib:") && { label: "Xoá", danger: true, onclick: async () => {
      if (!(await confirmBox({ title: `Xoá giọng “${displayName(v)}”?`, body: "Giọng sẽ bị xoá khỏi máy và không khôi phục được. Sách nói và bản đọc đã tạo vẫn giữ nguyên.", ok: "Xoá giọng", danger: true }))) return;
      try { await api("/api/library/" + v.id.slice(4), { method: "DELETE" }); forgetPreview(v); resetVoices(); toast("Đã xoá giọng."); refresh(); } catch (e) { showError(e); }
    } },
  ];
  const emptyMine = h("div", {}, "Bạn chưa có giọng riêng nào. Bấm “Thêm giọng từ file ghi âm” để nhân bản một giọng, hoặc “Pha giọng mới” để trộn hai giọng có sẵn.");

  async function refresh() {
    try {
      const vs = await voices(true);
      if (alive) body.replaceChildren(VoicePicker({ voices: vs, engines: eng, menu, emptyMine }));
    } catch (e) { body.replaceChildren(); showError(e); }
  }
  (async () => {
    try {
      eng = await engines(); await refresh();
      // từ thẻ Dàn giọng ("Chưa có giọng già…") dẫn sang đây thì mở luôn hộp thêm giọng
      if (pending.voiceAction === "add" && alive) { pending.voiceAction = null; document.getElementById("addVoice").click(); }
    } catch (e) { body.replaceChildren(); showError(e); }
  })();
  return () => { alive = false; };
}
