// Thẻ "Dàn giọng": mỗi nhân vật / loại nhân vật một giọng. Tool đoán ai đang nói qua phần dẫn ("Trần Bình An nói:", "– lão giả hỏi.").
import { h } from "../dom.js";
import { sendJSON } from "../api.js";
import { showError, toast, modal, switchEl, skeleton, confirmBox } from "../ui.js";
import { engines, voices } from "../store.js";
import { VoicePicker, keyOf, displayName, metaLine, previewVoice, AGE } from "../voicepicker.js";
import { go, pending } from "../router.js";
import { patchBook } from "../bookapi.js";

const MAX_ROLES = 20, MAX_VOICES = 4;

/** Mẫu 8 vai thường gặp trong truyện phân vai: lời dẫn do giọng kể của truyện đọc, nên không có vai "dẫn truyện" ở đây. */
export const TEMPLATE = [
  { name: "Nam chính", gender: "nam", age: "tre", slot: "", names: [], keywords: [] },
  { name: "Nam thanh niên", gender: "nam", age: "tre", slot: "nam_tre", names: [], keywords: ["thanh niên", "chàng trai", "thiếu niên", "công tử"] },
  { name: "Nam trung niên", gender: "nam", age: "trung_nien", slot: "nam_trung_nien", names: [], keywords: ["trung niên", "đại thúc", "người đàn ông"] },
  { name: "Lão ông", gender: "nam", age: "gia", slot: "nam_gia", names: [], keywords: ["lão giả", "lão nhân", "ông lão", "ông cụ", "lão gia", "tiền bối"] },
  { name: "Thiếu nữ", gender: "nữ", age: "tre", slot: "nu_tre", names: [], keywords: ["thiếu nữ", "cô gái", "cô nương", "tiểu thư"], two: true },
  { name: "Nữ trung niên", gender: "nữ", age: "trung_nien", slot: "nu_trung_nien", names: [], keywords: ["phu nhân", "thiếu phụ", "bà chủ", "người đàn bà"] },
  { name: "Lão bà", gender: "nữ", age: "gia", slot: "nu_gia", names: [], keywords: ["lão bà", "bà lão", "bà cụ", "lão thái"] },
];

/** id tạm cho vai chưa lưu (server giữ nguyên nếu hợp lệ: chữ thường + số, tối đa 12 ký tự). */
const newId = (roles) => { let id; do { id = "r" + Math.random().toString(36).slice(2, 8); } while (roles.some((r) => r.id === id)); return id; };
const slotOf = (c) => `${c.gender === "nam" ? "nam" : "nu"}_${c.group}`;
const csv = (t) => t.split(/[,\n;]/).map((x) => x.trim()).filter(Boolean);
const keyOfSpec = (v) => `${v.engine}|${v.voice}`;

export function mountCastTab(root, { id, book, onChanged }) {
  let alive = true, E = {}, V = [];
  const cur = book.cast || { enabled: false, roles: [] };
  const S = { enabled: !!cur.enabled, roles: (cur.roles || []).map((r) => ({ ...r, voices: r.voices.map((v) => ({ ...v })), names: [...r.names], keywords: [...r.keywords] })), characters: (cur.characters || []).map((c) => ({ ...c })), paste: "", pasteErrors: [], preview: null, busy: false, dirty: false };
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
    S.roles.push({ id: newId(S.roles), name: "", voices: [{ engine: v.engine, voice: v.id }], names: [], keywords: [] });
    touch(); draw();
  }

  // ───── nhân vật: "Tên - giới tính - tuổi" ─────
  const roleName = (id) => (S.roles.find((r) => r.id === id) || {}).name;
  const autoRole = (c) => S.roles.find((r) => r.slot && r.slot === slotOf(c));
  async function addPasted() {
    if (!S.paste.trim()) return;
    try {
      const r = await sendJSON("/api/cast/parse-characters", { text: S.paste });
      for (const c of r.characters) { const k = S.characters.findIndex((x) => x.name.toLowerCase() === c.name.toLowerCase()); if (k >= 0) S.characters[k] = { ...c, role: S.characters[k].role }; else S.characters.push(c); }
      S.pasteErrors = r.errors;
      S.paste = r.errors.map((e) => e.text).join("\n");   // chỉ giữ lại các dòng lỗi để sửa
      if (r.characters.length) touch();
      draw();
      if (r.characters.length) toast(`Đã thêm ${r.characters.length} nhân vật.` + (r.errors.length ? ` ${r.errors.length} dòng lỗi còn ở ô bên trên, hãy sửa rồi bấm thêm lại.` : ""));
    } catch (e) { showError(e); }
  }
  async function editCharacter(c, field, value) {
    const next = { ...c, [field]: value };
    try {
      const r = await sendJSON("/api/cast/parse-characters", { text: `${next.name} - ${next.gender} - ${next.age ?? AGE[next.group]}` });
      if (r.errors.length) { toast(r.errors[0].error, { kind: "error" }); return draw(); }
      Object.assign(c, { name: r.characters[0].name, gender: r.characters[0].gender, age: r.characters[0].age, group: r.characters[0].group });
      touch(); draw();
    } catch (e) { showError(e); draw(); }
  }

  /** Mẫu: gán mỗi vai một giọng trên máy khác nhau, đúng giới tính (giọng chưa có nhãn tuổi nên lão ông / lão bà chỉ là giọng thường, bạn tự đổi). */
  function useTemplate() {
    const narr = `${book.voice.engine}|${book.voice.voice}`, taken = new Set([narr]);
    const pool = (g) => V.filter((x) => x.usable !== false && x.gender === g && x.source !== "mix" && (!x.lang || x.lang.startsWith("vi")) && E[x.engine] && E[x.engine].local);
    // đúng giới tính và đúng tuổi trước; chưa có giọng đúng tuổi thì lấy giọng đúng giới tính (thẻ sẽ nhắc giọng chưa đúng tuổi)
    const pick = (g, age) => { const all = pool(g), ok = all.filter((x) => x.age === age), v = ok.find((x) => !taken.has(keyOf(x))) || ok[0] || all.find((x) => !taken.has(keyOf(x))) || all[0] || V.find((x) => x.usable !== false); if (v) taken.add(keyOf(v)); return v; };
    S.roles = [];
    for (const t of TEMPLATE) {
      const vs = [pick(t.gender, t.age), ...(t.two ? [pick(t.gender, t.age)] : [])].filter(Boolean);
      S.roles.push({ id: newId(S.roles), name: t.name, slot: t.slot, voices: vs.map((v) => ({ engine: v.engine, voice: v.id })), names: [...t.names], keywords: [...t.keywords] });
    }
    S.characters.forEach((c) => { c.role = ""; });   // vai cũ bị thay nên lựa chọn tay cũ không còn nghĩa
    S.enabled = true; touch(); draw();
    toast("Đã điền mẫu 7 vai. Hãy thêm tên nhân vật vào từng vai, nghe thử giọng rồi bấm “Lưu dàn giọng”.");
  }

  const spec = () => ({ enabled: S.enabled, roles: S.roles.map((r) => ({ id: r.id, name: r.name, slot: r.slot || "", voices: r.voices, names: r.names, keywords: r.keywords })),
    characters: S.characters.map((c) => ({ name: c.name, gender: c.gender, age: c.age, group: c.group, role: c.role || "" })) });

  async function save() {
    S.busy = true; draw();
    try {
      const saved = await patchBook(id, { cast: spec() });
      book.cast = saved.cast; S.roles = saved.cast.roles.map((r) => ({ ...r })); S.characters = saved.cast.characters.map((c) => ({ ...c })); S.dirty = false;
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

  const need = (r) => (r.slot ? r.slot.replace(/^(nam|nu)_/, "") : "");
  function roleCard(r, i) {
    const voiceRow = (spec, k) => { const v = voiceOf(spec); return h("div", { class: "vcurrent" },
      h("div", { class: "vinfo" }, h("b", {}, v ? displayName(v) : "(giọng không còn dùng được)"), v && h("div", { class: "muted" }, metaLine(v, E)),
        v && need(r) && v.age !== need(r) && h("div", { class: "muted" }, `⚠ Vai này cần giọng ${AGE[need(r)]}, giọng này ${v.age ? "đang nhãn " + AGE[v.age] : "chưa có nhãn tuổi"}.`)),
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

  /** Nhóm tuổi có nhân vật mà chưa có giọng nào mang nhãn tuổi đó → nhắc tạo giọng (ghi âm / pha giọng). */
  function missingVoices() {
    const have = new Set(V.filter((x) => x.usable !== false && x.age).map((x) => x.age));
    const groups = ["gia", "trung_nien", "tre"].filter((g) => S.characters.some((c) => c.group === g) && !have.has(g));
    return groups.map((g) => h("div", { class: "notice warn" }, h("b", {}, `Chưa có giọng ${AGE[g]}. `), "Tạo từ file ghi âm hoặc Pha giọng, nhớ chọn độ tuổi khi lưu. Giọng có sẵn nào nghe hợp thì bạn cũng có thể gắn nhãn ở màn Giọng đọc (menu ⋯ → Đổi độ tuổi).",
      h("div", { class: "row", style: "margin-top:8px" },
        h("button", { type: "button", class: "btn small", onclick: () => { pending.voiceAction = "add"; go("/giong"); } }, "Thêm giọng từ file ghi âm"),
        h("button", { type: "button", class: "btn small", onclick: () => go("/giong/pha") }, "Pha giọng mới"))));
  }

  function charactersCard() {
    const row = (c) => {
      const auto = autoRole(c);
      return h("div", { class: "charrow" },
        h("input", { type: "text", value: c.name, maxlength: 60, "aria-label": "Tên nhân vật", onchange: (e) => editCharacter(c, "name", e.target.value) }),
        h("select", { "aria-label": "Giới tính", onchange: (e) => editCharacter(c, "gender", e.target.value) }, ...[["nam", "Nam"], ["nữ", "Nữ"]].map(([k, t]) => h("option", { value: k, selected: c.gender === k }, t))),
        h("input", { type: "text", value: c.age ?? AGE[c.group], size: 8, "aria-label": "Tuổi", title: `Nhóm: ${AGE[c.group]}`, onchange: (e) => editCharacter(c, "age", /^\d+$/.test(e.target.value.trim()) ? +e.target.value.trim() : e.target.value.trim()) }),
        h("select", { "aria-label": "Vai của " + c.name, onchange: (e) => { c.role = e.target.value; touch(); draw(); } },
          h("option", { value: "", selected: !c.role }, auto ? `Tự động: ${auto.name}` : `Tự động: chưa có vai ${AGE[c.group]} ${c.gender === "nam" ? "nam" : "nữ"}`),
          ...S.roles.map((r) => h("option", { value: r.id, selected: c.role === r.id }, r.name || "(chưa đặt tên)"))),
        h("button", { type: "button", class: "btn small danger", "aria-label": "Bỏ " + c.name, onclick: () => { S.characters.splice(S.characters.indexOf(c), 1); touch(); draw(); } }, "Bỏ"));
    };
    return h("div", { class: "card flat", style: "margin-top:16px" }, h("h3", { style: "font-size:20px;margin-bottom:6px" }, "Nhân vật"),
      h("p", { class: "muted" }, "Mỗi nhân vật một dòng: Tên - giới tính - tuổi. Tuổi là số hoặc trẻ / trung niên / già. Tool xếp theo tuổi: dưới 25 là trẻ, từ 25 đến 55 là trung niên, trên 55 là già, rồi tự đưa vào vai tương ứng. Bạn vẫn đổi vai bằng tay được."),
      h("textarea", { rows: 5, id: "castPaste", placeholder: "Trần Bình An - nam - 16\nLão Lưu - nam - già\nNinh Diêu - nữ - 15", "aria-label": "Danh sách nhân vật, mỗi dòng một người", oninput: (e) => { S.paste = e.target.value; } }, S.paste),
      S.pasteErrors.length ? h("div", { class: "notice err" }, ...S.pasteErrors.map((e) => h("div", {}, h("b", {}, `Dòng ${e.line}: `), e.error, h("div", { class: "muted ellip" }, e.text)))) : null,
      h("div", { class: "row", style: "margin-top:10px" }, h("button", { type: "button", class: "btn", id: "castAddChars", onclick: addPasted }, "Thêm nhân vật")),
      S.characters.length ? h("div", { class: "stack", style: "margin-top:14px;--gap:8px" }, h("div", { class: "charrow charhead muted" }, h("span", {}, "Tên"), h("span", {}, "Giới tính"), h("span", {}, "Tuổi"), h("span", {}, "Vai"), h("span", {})), ...S.characters.map(row)) : null,
      ...missingVoices());
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
      charactersCard(),
      S.roles.length ? h("div", { class: "stack", style: "margin-top:16px" }, ...S.roles.map(roleCard)) : h("div", { class: "empty", style: "margin-top:16px" }, h("p", { class: "muted" }, "Chưa có vai nào. Bấm “Dùng mẫu 7 vai” hoặc “＋ Thêm vai”.")),
      previewBox(),
      h("div", { class: "stickyfoot" },
        h("button", { type: "button", class: "btn primary", id: "castSave", disabled: S.busy || !S.dirty, onclick: save }, S.busy ? "Đang xử lý…" : "Lưu dàn giọng"),
        h("button", { type: "button", class: "btn", id: "castCheck", disabled: S.busy || !S.roles.length, onclick: check }, "Kiểm tra trên 5 chương đầu"),
        S.dirty && h("span", { class: "muted" }, "Chưa lưu thay đổi.")));
  }
  return () => { alive = false; };
}
