// Thẻ "Cài đặt" của truyện: tên, giọng, tốc độ, nghỉ, dung lượng. Phần kỹ thuật nằm trong "Nâng cao".
import { h } from "../dom.js";
import { api, getJSON, sendJSON } from "../api.js";
import { go } from "../router.js";
import { showError, toast, confirmBox, modal, switchEl } from "../ui.js";
import { engines, voices } from "../store.js";
import { VoicePicker, keyOf, displayName, metaLine, previewVoice } from "../voicepicker.js";
import { patchBook, deleteBook } from "../bookapi.js";
import { editEntry, emptyEntry, describe } from "../lexicon-editor.js";
import { sizeText } from "./book.js";

const SPEEDS = [["Chậm", -15], ["Vừa", 0], ["Nhanh", 20]];
const speedLabel = (p) => (SPEEDS.find(([, v]) => v === p) || [])[0];

export function mountSettingsTab(root, { id, book, q, onChanged }) {
  let alive = true, E = {}, V = [];
  const st = { title: book.title, author: book.author || "", voice: `${book.voice.engine}|${book.voice.voice}`, speed: book.speed || 0, custom: speedLabel(book.speed || 0) ? "" : String(book.speed),
    dlg: !!(book.dialogue_voice && book.dialogue_voice.enabled), dlgVoice: book.dialogue_voice ? `${book.dialogue_voice.engine}|${book.dialogue_voice.voice}` : "",
    readTitle: book.read_title !== false, pp: book.paragraph_pause_s ?? 0.6, tp: book.title_pause_s ?? 1.2, norm: book.normalize !== false };
  const area = h("div", {}), diskBox = h("div", {});
  root.append(area);
  Promise.all([engines(), voices()]).then(([e, v]) => { if (alive) { E = e; V = v; draw(); } }).catch((e) => showError(e));
  const voiceOf = (k) => V.find((v) => keyOf(v) === k);

  function pick(key) {
    const m = modal([h("h3", {}, "Chọn giọng"), VoicePicker({ voices: V, engines: E, value: st[key], only: (x) => x.usable !== false, onPick: (x) => { st[key] = keyOf(x); m.close(); draw(); } }),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))], { wide: true });
  }
  const voiceRow = (key, label) => { const v = voiceOf(st[key]); return h("div", {}, h("label", { class: "field" }, label),
    h("div", { class: "vcurrent" }, h("div", { class: "vinfo" }, h("b", {}, v ? displayName(v) : "(giọng không còn dùng được)"), v && h("div", { class: "muted" }, metaLine(v, E))),
      v && h("button", { class: "play", "aria-label": "Nghe thử " + displayName(v), onclick: () => previewVoice(v) }, "▶"), h("button", { class: "btn small", onclick: () => pick(key) }, "Đổi giọng"))); };

  async function save() {
    const v = voiceOf(st.voice);
    if (!v) return showError(new Error("Hãy chọn một giọng còn dùng được."));
    const d = voiceOf(st.dlgVoice) || v;
    const speed = st.custom !== "" && !Number.isNaN(+st.custom) ? Math.round(+st.custom) : st.speed;
    try {
      await patchBook(id, { title: st.title, author: st.author, voice: { engine: v.engine, voice: v.id }, speed, read_title: st.readTitle, normalize: st.norm,
        paragraph_pause_s: +st.pp, title_pause_s: +st.tp, dialogue_voice: { enabled: st.dlg, engine: d.engine, voice: d.id } });
      toast("Đã lưu cài đặt. Chương nào bị ảnh hưởng sẽ hiện “cần tạo lại”.");
      onChanged();
    } catch (e) { showError(e); }
  }

  async function paintDisk() {
    try {
      const d = await getJSON(`/api/books/${encodeURIComponent(id)}/disk`), pg = q.purgeable || { chapters: 0, bytes: 0 };
      diskBox.replaceChildren(h("div", { class: "card flat", style: "margin-top:16px" }, h("h3", { style: "font-size:20px" }, "Dung lượng"),
        h("p", {}, "Truyện này đang chiếm ", h("b", {}, sizeText(d.total)), " trên máy.", h("span", { class: "muted" }, ` Bản gốc của các chương đã tạo: ${sizeText(d.audio)}; file đã chuẩn bị để tải: ${sizeText(d.export)}.`)),
        h("button", { class: "btn", disabled: !pg.chapters, onclick: purge }, pg.chapters ? `Dọn bản gốc các chương đã tải về (giải phóng ${sizeText(pg.bytes)})` : "Dọn bản gốc các chương đã tải về"),
        h("div", { class: "hint" }, pg.chapters ? "Chương nào đã tải về mới được dọn. File đã tải không bị xoá; muốn nghe hoặc sửa lại chương đó thì tạo lại." : "Chưa chương nào được tải về nên chưa có gì để dọn.")));
    } catch { /* bỏ qua */ }
  }
  async function purge() {
    const pg = q.purgeable;
    if (!(await confirmBox({ title: `Giải phóng ${sizeText(pg.bytes)}?`, body: `Tool xoá bản gốc của ${pg.chapters} chương đã tải về. File MP3 / m4b bạn đã tải không bị ảnh hưởng. Muốn nghe lại hoặc sửa các chương đó, bạn cần tạo lại chương.`, ok: "Giải phóng", danger: true }))) return;
    try { const r = await sendJSON(`/api/books/${encodeURIComponent(id)}/audio/purge-exported`, {}); toast(`Đã giải phóng ${sizeText(r.freed)}.`); onChanged(); paintDisk(); } catch (e) { showError(e); }
  }

  function draw() {
    area.replaceChildren(h("div", { class: "card flat stack" },
      h("div", { class: "two" }, h("div", {}, h("label", { class: "field" }, "Tên truyện"), h("input", { type: "text", value: st.title, maxLength: 200, oninput: (e) => { st.title = e.target.value; } })),
        h("div", {}, h("label", { class: "field" }, "Tác giả"), h("input", { type: "text", value: st.author, maxLength: 200, oninput: (e) => { st.author = e.target.value; } }))),
      voiceRow("voice", "Giọng kể"),
      h("div", {}, h("label", { class: "field" }, "Đọc nhanh hay chậm?"), h("div", { class: "seg", role: "group", "aria-label": "Tốc độ đọc" }, ...SPEEDS.map(([t, p]) =>
        h("button", { type: "button", class: st.custom === "" && st.speed === p ? "on" : "", onclick: () => { st.speed = p; st.custom = ""; draw(); } }, t)))),
      switchEl("Lời thoại đọc bằng giọng khác", st.dlg, (on) => { st.dlg = on; if (on && !st.dlgVoice) st.dlgVoice = st.voice; draw(); }),
      st.dlg ? voiceRow("dlgVoice", "Giọng đọc lời thoại") : null,
      switchEl("Đọc tên chương ở đầu mỗi chương", st.readTitle, (on) => { st.readTitle = on; }),
      h("div", { class: "two" }, h("div", {}, h("label", { class: "field" }, "Nghỉ giữa các đoạn văn (giây)"), h("input", { type: "number", min: 0, max: 3, step: 0.1, value: st.pp, oninput: (e) => { st.pp = e.target.value; } })),
        h("div", {}, h("label", { class: "field" }, "Nghỉ sau tên chương (giây)"), h("input", { type: "number", min: 0, max: 5, step: 0.1, value: st.tp, oninput: (e) => { st.tp = e.target.value; } }))),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: save }, "Lưu cài đặt"), h("span", { class: "muted" }, "Đổi giọng, tốc độ hay chỗ nghỉ thì các chương đã tạo cần tạo lại.")),
      h("details", { class: "adv" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body stack" },
        h("div", {}, h("label", { class: "field" }, "Tốc độ tinh chỉnh (%)"), h("input", { type: "number", min: -50, max: 200, step: 5, value: st.custom, placeholder: "Để trống để dùng Chậm / Vừa / Nhanh", style: "max-width:260px", oninput: (e) => { st.custom = e.target.value; } })),
        switchEl("Tự đọc số, ngày tháng, đơn vị cho đúng (chuẩn hoá văn bản)", st.norm, (on) => { st.norm = on; }),
        h("div", {}, h("b", {}, "Cách đọc tên riêng dùng chung cho mọi truyện"), h("div", {}, h("button", { class: "btn small", style: "margin-top:6px", onclick: globalLexicon }, "Mở danh sách chung"))),
        h("div", {}, h("b", {}, "Chia chương lại hoặc dọn văn bản"), h("p", { class: "muted", style: "margin:4px 0 8px" }, "Mở lại bước Kiểm tra. Khi xác nhận, các chương đã tạo sẽ bị xoá và phải tạo lại."),
          h("button", { class: "btn small", onclick: async () => {
            if (!(await confirmBox({ title: "Chia chương lại?", body: "Bạn có thể xem và chỉnh trước. Chỉ khi bấm tiếp tục ở bước Kiểm tra thì các chương đã tạo mới bị xoá.", ok: "Mở bước Kiểm tra", cancel: "Thôi" }))) return;
            go(`/sach/${id}/kiem-tra`); } }, "Mở bước Kiểm tra")),
        h("div", {}, h("b", {}, "Xoá truyện này"), h("p", { class: "muted", style: "margin:4px 0 8px" }, "Xoá cả file gốc, các chương và audio đã tạo. Không khôi phục được."),
          h("button", { class: "btn small danger", onclick: async () => {
            if (!(await confirmBox({ title: `Xoá truyện “${book.title}”?`, body: "Toàn bộ chương và audio đã tạo của truyện này sẽ bị xoá khỏi máy và không khôi phục được.", ok: "Xoá truyện", danger: true }))) return;
            try { await deleteBook(id); toast("Đã xoá truyện."); go("/sach"); } catch (e) { showError(e); } } }, "Xoá truyện"))))),
      diskBox);
    paintDisk();
  }

  async function globalLexicon() {
    let list;
    try { list = await getJSON("/api/lexicon"); } catch (e) { return showError(e); }
    const box = h("div", {});
    const put = async (next) => { try { list = await sendJSON("/api/lexicon", next, "PUT"); paint(); toast("Đã lưu cách đọc dùng chung."); onChanged(); } catch (e) { showError(e); } };
    const edit = async (i) => {
      const r = await editEntry(i == null ? emptyEntry() : list[i], { title: i == null ? "Thêm tên dùng chung" : "Cách đọc tên này", canDelete: i != null });
      if (!r) return; const next = [...list];
      if (r._delete) next.splice(i, 1); else { const { _delete, ...e } = r; if (i == null) next.push(e); else next[i] = e; }
      put(next);
    };
    const paint = () => box.replaceChildren(list.length ? h("div", { class: "chlist" }, ...list.map((e, i) => h("div", { class: "chrow" }, h("div", { class: "name" }, h("b", {}, e.match), h("div", { class: "sub" }, describe(e))),
      h("button", { class: "btn small", onclick: () => edit(i) }, "Sửa")))) : h("p", { class: "muted" }, "Chưa có tên nào dùng chung."));
    paint();
    const m = modal([h("h3", {}, "Cách đọc tên riêng dùng chung"), h("p", { class: "muted" }, "Áp dụng cho mọi truyện. Tên đã có ở từng truyện riêng thì dùng cách đọc của truyện đó."), box,
      h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "btn", onclick: () => edit(null) }, "＋ Thêm tên"), h("button", { class: "btn primary", style: "margin-left:auto", onclick: () => m.close() }, "Xong"))], { wide: true });
  }
  return () => { alive = false; };
}
