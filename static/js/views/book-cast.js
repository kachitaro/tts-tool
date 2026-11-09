// Thẻ "Dàn giọng": mỗi nhân vật / loại nhân vật một giọng. Tool đoán ai đang nói qua phần dẫn ("Trần Bình An nói:", "– lão giả hỏi.").
import { h } from "../dom.js";
import { sendJSON } from "../api.js";
import { showError, toast, modal, switchEl, skeleton, confirmBox } from "../ui.js";
import { engines, voices } from "../store.js";
import { VoicePicker, keyOf, displayName, metaLine, previewVoice } from "../voicepicker.js";
import { patchBook } from "../bookapi.js";

const MAX_ROLES = 20, MAX_VOICES = 4;

/** Mẫu 8 vai thường gặp trong truyện phân vai: lời dẫn do giọng kể của truyện đọc, nên không có vai "dẫn truyện" ở đây. */
export const TEMPLATE = [
  { name: "Nam chính", gender: "nam", names: [], keywords: [] },
  { name: "Nam thanh niên", gender: "nam", names: [], keywords: ["thanh niên", "chàng trai", "thiếu niên", "công tử"] },
  { name: "Nam trung niên", gender: "nam", names: [], keywords: ["trung niên", "đại thúc", "người đàn ông"] },
  { name: "Lão ông", gender: "nam", names: [], keywords: ["lão giả", "lão nhân", "ông lão", "ông cụ", "lão gia", "tiền bối"] },
  { name: "Thiếu nữ", gender: "nữ", names: [], keywords: ["thiếu nữ", "cô gái", "cô nương", "tiểu thư"], two: true },
  { name: "Nữ trung niên", gender: "nữ", names: [], keywords: ["phu nhân", "thiếu phụ", "bà chủ", "người đàn bà"] },
  { name: "Lão bà", gender: "nữ", names: [], keywords: ["lão bà", "bà lão", "bà cụ", "lão thái"] },
];

const csv = (t) => t.split(/[,\n;]/).map((x) => x.trim()).filter(Boolean);
const keyOfSpec = (v) => `${v.engine}|${v.voice}`;

export function mountCastTab(root, { id, book, onChanged }) {
  let alive = true, E = {}, V = [];
  const cur = book.cast || { enabled: false, roles: [] };
  const S = { enabled: !!cur.enabled, roles: (cur.roles || []).map((r) => ({ ...r, voices: r.voices.map((v) => ({ ...v })), names: [...r.names], keywords: [...r.keywords] })), preview: null, busy: false, dirty: false };
  const area = h("div", {}, skeleton(3));
  root.append(area);
  Promise.all([engines(), voices()]).then(([e, v]) => { if (alive) { E = e; V = v; draw(); } }).catch(showError);
  const voiceOf = (spec) => V.find((v) => keyOf(v) === keyOfSpec(spec));
  const touch = () => { S.dirty = true; S.preview = null; };

  function pickVoice(role, slot) {
    const m = modal([h("h3", {}, "Chọn giọng"), VoicePicker({ voices: V, engines: E, value: role.voices[slot] ? keyOfSpec(role.voices[slot]) : "", only: (x) => x.usable !== false,
      onPick: (x) => { role.voices[slot] = { engine: x.engine, voice: x.id }; touch(); m.close(); draw(); } }),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))], { wide: true });
  }

  function addRole() {
    if (S.roles.length >= MAX_ROLES) return toast(`Tối đa ${MAX_ROLES} vai.`);
    const used = new Set(S.roles.flatMap((r) => r.voices.map(keyOfSpec)));
    const v = V.find((x) => x.usable !== false && !used.has(keyOf(x))) || V[0];
    S.roles.push({ name: "", voices: [{ engine: v.engine, voice: v.id }], names: [], keywords: [] });
    touch(); draw();
  }

  /** Mẫu: gán mỗi vai một giọng trên máy khác nhau, đúng giới tính (giọng chưa có nhãn tuổi nên lão ông / lão bà chỉ là giọng thường, bạn tự đổi). */
  function useTemplate() {
    const narr = `${book.voice.engine}|${book.voice.voice}`, taken = new Set([narr]);
    const pool = (g) => V.filter((x) => x.usable !== false && x.gender === g && x.source !== "mix" && (!x.lang || x.lang.startsWith("vi")) && E[x.engine] && E[x.engine].local);
    const pick = (g) => { const all = pool(g), v = all.find((x) => !taken.has(keyOf(x))) || all[0] || V.find((x) => x.usable !== false); if (v) taken.add(keyOf(v)); return v; };
    S.roles = TEMPLATE.map((t) => {
      const vs = [pick(t.gender), ...(t.two ? [pick(t.gender)] : [])].filter(Boolean);
      return { name: t.name, voices: vs.map((v) => ({ engine: v.engine, voice: v.id })), names: [...t.names], keywords: [...t.keywords] };
    });
    S.enabled = true; touch(); draw();
    toast("Đã điền mẫu 7 vai. Hãy thêm tên nhân vật vào từng vai, nghe thử giọng rồi bấm “Lưu dàn giọng”.");
  }

  const spec = () => ({ enabled: S.enabled, roles: S.roles.map((r) => ({ id: r.id, name: r.name, voices: r.voices, names: r.names, keywords: r.keywords })) });

  async function save() {
    S.busy = true; draw();
    try {
      const saved = await patchBook(id, { cast: spec() });
      book.cast = saved.cast; S.roles = saved.cast.roles.map((r) => ({ ...r })); S.dirty = false;
      toast("Đã lưu dàn giọng. Chương nào bị ảnh hưởng sẽ hiện “cần tạo lại”.");
      onChanged && onChanged();
    } catch (e) { showError(e); }
    S.busy = false; if (alive) draw();
  }

  async function check() {
    S.busy = true; draw();
    try { S.preview = await sendJSON(`/api/books/${encodeURIComponent(id)}/cast/preview`, { cast: spec() }); }
    catch (e) { showError(e); }
    S.busy = false; if (alive) draw();
  }

  function roleCard(r, i) {
    const voiceRow = (spec, k) => { const v = voiceOf(spec); return h("div", { class: "vcurrent" },
      h("div", { class: "vinfo" }, h("b", {}, v ? displayName(v) : "(giọng không còn dùng được)"), v && h("div", { class: "muted" }, metaLine(v, E))),
      v && h("button", { type: "button", class: "play", "aria-label": "Nghe thử " + displayName(v), onclick: () => previewVoice(v) }, "▶"),
      h("button", { type: "button", class: "btn small", onclick: () => pickVoice(r, k) }, "Đổi giọng"),
      r.voices.length > 1 && h("button", { type: "button", class: "btn small danger", "aria-label": "Bỏ giọng này", onclick: () => { r.voices.splice(k, 1); touch(); draw(); } }, "Bỏ")); };
    return h("div", { class: "card flat castrole" },
      h("div", { class: "row", style: "justify-content:space-between" },
        h("input", { type: "text", value: r.name, maxlength: 60, placeholder: "Tên vai, ví dụ: Lão ông", "aria-label": "Tên vai", style: "font-weight:600;max-width:320px", oninput: (e) => { r.name = e.target.value; touch(); } }),
        h("button", { type: "button", class: "btn small danger", onclick: () => { S.roles.splice(i, 1); touch(); draw(); } }, "Xoá vai")),
      h("div", { class: "stack", style: "--gap:10px;margin-top:12px" },
        h("div", {}, h("label", { class: "field" }, r.voices.length > 1 ? "Giọng (mỗi tên nhân vật cố định một giọng, xoay vòng)" : "Giọng"), ...r.voices.map(voiceRow),
          r.voices.length < MAX_VOICES && h("button", { type: "button", class: "btn small ghost", onclick: () => { const v = V.find((x) => x.usable !== false); r.voices.push({ engine: v.engine, voice: v.id }); touch(); pickVoice(r, r.voices.length - 1); } }, "＋ Thêm giọng")),
        h("div", { class: "two" },
          h("div", {}, h("label", { class: "field" }, "Tên nhân vật"), h("input", { type: "text", value: r.names.join(", "), placeholder: "Trần Bình An, Ninh Diêu", oninput: (e) => { r.names = csv(e.target.value); touch(); } }),
            h("div", { class: "hint" }, "Cách nhau bằng dấu phẩy. Viết đúng như trong truyện.")),
          h("div", {}, h("label", { class: "field" }, "Từ khoá chỉ loại người"), h("input", { type: "text", value: r.keywords.join(", "), placeholder: "lão giả, ông cụ", oninput: (e) => { r.keywords = csv(e.target.value); touch(); } }),
            h("div", { class: "hint" }, "Dùng khi phần dẫn không nêu tên: “– lão giả hỏi.”")))));
  }

  function previewBox() {
    const p = S.preview;
    if (!p) return null;
    const row = (name, e, warn) => h("div", { class: "castprev" },
      h("div", { class: "row", style: "justify-content:space-between" }, h("b", {}, name), h("span", { class: warn ? "tag" : "muted" }, `${e.lines} câu`)),
      ...e.samples.map((s) => h("div", { class: "muted ellip", title: `${s.text}  —  ${s.tag}` }, `Chương ${s.chapter}: “${s.text}”`, s.tag ? ` ← ${s.tag}` : "")));
    return h("div", { class: "card flat", style: "margin-top:16px" }, h("h3", { style: "font-size:20px;margin-bottom:6px" }, `Kết quả trên ${p.chapters.length} chương đầu`),
      p.dialogue_lines ? h("p", { class: "muted" }, `Có ${p.dialogue_lines} câu thoại. ${p.unmatched.lines} câu chưa nhận ra vai sẽ do giọng lời thoại chung (hoặc giọng kể) đọc.`) : h("p", { class: "muted" }, "Không thấy câu thoại nào trong các chương này."),
      ...p.roles.map((r) => row(r.name || "(chưa đặt tên)", r)), p.unmatched.lines ? row(p.unmatched.name, p.unmatched, true) : null,
      p.unmatched.lines ? h("div", { class: "hint" }, "Muốn nhận ra thêm: thêm tên nhân vật hoặc từ khoá có trong phần dẫn (“… nói”, “… hỏi”) vào đúng vai.") : null);
  }

  function draw() {
    if (!V.length) return;
    area.replaceChildren(
      h("div", { class: "card flat" }, h("h3", { style: "font-size:20px;margin-bottom:6px" }, "Dàn giọng nhân vật"),
        h("p", { class: "muted" }, "Mỗi nhân vật hay mỗi loại người một giọng riêng. Tool đoán ai đang nói qua phần dẫn như “Trần Bình An nói:” hoặc “– lão giả hỏi.”. Lời dẫn truyện do giọng kể của truyện đọc. Câu thoại không đoán được vai do giọng lời thoại chung đọc (đặt ở thẻ Cài đặt), nếu không bật thì do giọng kể đọc."),
        switchEl("Đọc lời thoại theo từng vai", S.enabled, (on) => { S.enabled = on; touch(); draw(); }),
        h("div", { class: "row", style: "margin-top:12px" },
          h("button", { type: "button", class: "btn", onclick: async () => { if (!S.roles.length || (await confirmBox({ title: "Thay bằng mẫu 7 vai?", body: "Các vai bạn đã tạo sẽ bị thay (chỉ khi bạn bấm Lưu mới ghi đè).", ok: "Thay bằng mẫu", cancel: "Giữ lại" }))) useTemplate(); } }, "Dùng mẫu 7 vai"),
          h("button", { type: "button", class: "btn", onclick: addRole }, "＋ Thêm vai"))),
      S.roles.length ? h("div", { class: "stack", style: "margin-top:16px" }, ...S.roles.map(roleCard)) : h("div", { class: "empty", style: "margin-top:16px" }, h("p", { class: "muted" }, "Chưa có vai nào. Bấm “Dùng mẫu 7 vai” hoặc “＋ Thêm vai”.")),
      previewBox(),
      h("div", { class: "stickyfoot" },
        h("button", { type: "button", class: "btn primary", id: "castSave", disabled: S.busy || !S.dirty, onclick: save }, S.busy ? "Đang xử lý…" : "Lưu dàn giọng"),
        h("button", { type: "button", class: "btn", id: "castCheck", disabled: S.busy || !S.roles.length, onclick: check }, "Kiểm tra trên 5 chương đầu"),
        S.dirty && h("span", { class: "muted" }, "Chưa lưu thay đổi.")));
  }
  return () => { alive = false; };
}
