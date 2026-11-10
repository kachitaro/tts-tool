// Bảng chọn thẻ kiểu ElevenLabs: cảm xúc, chỗ nghỉ, hiệu ứng âm thanh (có sẵn + của bạn).
// tagPicker({ textarea, emotionTags: () => ["[cười]"], multi: () => bool }) → Node (nút "[ ] Chèn thẻ" + bảng nổi)
import { h } from "./dom.js";
import { api, getJSON, sendForm } from "./api.js";
import { modal, confirmBox, toast, showError } from "./ui.js";
import { play } from "./player.js";

let catalogP = null;   // tải lười một lần khi mở bảng lần đầu; thêm / xoá âm thì tải lại
const loadCatalog = () => (catalogP ||= getJSON("/api/sfx").catch((e) => { catalogP = null; throw e; }));

/** Bỏ dấu, đ → d, chữ thường: "Tiếng sấm" khớp "tieng sam". */
const fold = (s) => s.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();

const PAUSES = [
  { label: "Ngắt nhẹ", insert: ", ", desc: "Dấu phẩy: ngắt hơi rất ngắn", raw: true },
  { label: "[nghỉ 0.5s]", insert: "[nghỉ 0.5s]", desc: "Im lặng nửa giây" },
  { label: "[nghỉ 1s]", insert: "[nghỉ 1s]", desc: "Im lặng một giây" },
  { label: "[nghỉ 2s]", insert: "[nghỉ 2s]", desc: "Im lặng hai giây" },
];

/** Chèn vào vị trí con trỏ (thay vùng đang chọn). Thẻ dính vào chữ thì tự thêm khoảng trắng. */
function insertAt(ta, text, raw) {
  const { selectionStart: a, selectionEnd: b, value } = ta;
  let t = text;
  if (!raw) {
    if (a > 0 && !/\s/.test(value[a - 1])) t = " " + t;
    if (b < value.length && !/[\s.,!?;:…]/.test(value[b])) t += " ";
  }
  ta.setRangeText(t, a, b, "end");
  ta.focus();
  ta.dispatchEvent(new Event("input", { bubbles: true }));
}

function addDialog(onAdded) {
  const name = h("input", { type: "text", maxLength: 30, placeholder: "Ví dụ: tiếng còi xe", "aria-label": "Tên thẻ" });
  const file = h("input", { type: "file", accept: "audio/*", "aria-label": "File âm thanh" });
  const err = h("div", { class: "notice err", hidden: true, role: "alert" });
  const add = h("button", { type: "button", class: "btn primary" }, "Thêm");
  const m = modal([
    h("h3", {}, "Thêm âm của bạn"),
    h("p", { class: "muted" }, "Chọn một file âm thanh ngắn (tối đa 15 giây, dài hơn sẽ bị cắt). Gõ tên thẻ để dùng, ví dụ [tiếng còi xe]."),
    h("label", { class: "field" }, "Tên thẻ", name),
    h("label", { class: "field", style: "margin-top:12px" }, "File âm thanh", file),
    err,
    h("div", { class: "row end", style: "margin-top:18px" }, h("button", { type: "button", class: "btn", onclick: () => m.close() }, "Huỷ"), add),
  ]);
  add.onclick = async () => {
    err.hidden = true;
    if (!name.value.trim()) { err.textContent = "Hãy gõ tên thẻ."; err.hidden = false; name.focus(); return; }
    if (!file.files[0]) { err.textContent = "Hãy chọn một file âm thanh."; err.hidden = false; return; }
    add.disabled = true; add.textContent = "Đang thêm…";
    try {
      const made = await (await sendForm("/api/sfx", { name: name.value.trim(), file: file.files[0] })).json();
      catalogP = null;
      m.close();
      toast(`Đã thêm ${made.label}. Gõ thẻ này vào văn bản để chèn tiếng đó.`);
      onAdded(made);
    } catch (e) {
      err.textContent = e.message; err.hidden = false; add.disabled = false; add.textContent = "Thêm";
    }
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") add.click(); });
}

export function tagPicker({ textarea, emotionTags, multi }) {
  let open = false, items = [], info = null, cat = null, loadErr = false;
  const search = h("input", { type: "search", placeholder: "Tìm thẻ: mưa, rain, gõ cửa…", "aria-label": "Tìm thẻ" });
  const list = h("div", { class: "tp-list" });
  const bar = h("div", { class: "tp-bar", "aria-live": "polite" });
  const pop = h("div", { class: "tp-pop hidden", role: "dialog", "aria-label": "Chèn thẻ" }, search, list, bar);
  const btn = h("button", { type: "button", class: "btn small", "aria-haspopup": "dialog", "aria-expanded": "false", onclick: () => (open ? close() : show()) }, "[ ] Chèn thẻ");
  const root = h("span", { class: "tp" }, btn, pop);

  const navEls = () => [...list.querySelectorAll(".tp-chip")];

  function close(toButton = true) {
    if (!open) return;
    open = false; pop.classList.add("hidden"); btn.setAttribute("aria-expanded", "false");
    if (toButton) btn.focus();
  }

  async function show() {
    open = true; pop.classList.remove("hidden"); btn.setAttribute("aria-expanded", "true");
    search.value = ""; paint(); place(); search.focus();
    if (!cat) {
      try { cat = await loadCatalog(); loadErr = false; } catch { loadErr = true; }
      paint(); place();
    }
  }

  /** Không đủ chỗ phía dưới (chừa chỗ cho thanh phát) thì mở lên trên, giống menu.js. Gọi sau mỗi lần vẽ lại. */
  function place() {
    pop.classList.remove("up");
    const r = pop.getBoundingClientRect();
    if (r.bottom > window.innerHeight - 96 && btn.getBoundingClientRect().top - r.height - 6 > 0) pop.classList.add("up");
  }

  const sections = () => {
    const q = fold(search.value.trim());
    const hit = (it) => !q || [it.label, it.desc, ...(it.aliases || [])].some((s) => fold(s).includes(q));
    const emo = emotionTags().map((t) => ({ label: t, insert: t, desc: "Cảm xúc của giọng đọc" }));
    const sfx = (src) => (cat || []).filter((c) => c.source === src).map((c) => ({ label: c.label, insert: c.label, desc: c.description, aliases: c.aliases, sfx: c }));
    const para = [...PAUSES, { label: "Xuống đoạn", insert: multi() ? "\n\n" : "\n", desc: "Xuống dòng để nghỉ lâu hơn", raw: true }];
    return [
      { title: "Cảm xúc", items: emo.filter(hit), empty: q ? "" : "Giọng đang chọn không có thẻ cảm xúc. Giọng chạy trên máy (VieNeu) có [cười], [thở dài], [hắng giọng]." },
      { title: "Chỗ nghỉ", items: para.filter(hit) },
      { title: "Hiệu ứng âm thanh", items: sfx("builtin").filter(hit), empty: !cat && !loadErr ? "Đang tải…" : loadErr ? "Không tải được danh sách hiệu ứng. Đóng bảng rồi mở lại." : "" },
      { title: "Âm của bạn", items: sfx("user").filter(hit), addChip: true },
    ];
  };

  function showInfo(it) {
    info = it;
    bar.replaceChildren(h("span", { class: "tp-info" }, h("b", {}, it.label), " — ", it.desc),
      it.sfx && h("button", { type: "button", class: "btn small", onclick: () => play({ src: `/api/sfx/${encodeURIComponent(it.sfx.id)}/audio`, title: it.label, sub: "Nghe thử hiệu ứng" }) }, "▶ Nghe thử"),
      it.sfx?.source === "user" && h("button", { type: "button", class: "btn small danger", onclick: () => remove(it.sfx) }, "Xoá"));
  }

  async function remove(s) {
    if (!(await confirmBox({ title: `Xoá ${s.label}?`, body: "Các văn bản đang dùng thẻ này sẽ đọc thẻ như chữ thường. Truyện đã tạo audio xong thì không đổi.", ok: "Xoá", cancel: "Để lại", danger: true }))) return;
    try {
      await api(`/api/sfx/${encodeURIComponent(s.id)}`, { method: "DELETE" });
      catalogP = null; cat = await loadCatalog(); info = null; paint(); toast(`Đã xoá ${s.label}.`);
    } catch (e) { showError(e); }
  }

  function paint() {
    items = [];
    list.replaceChildren(...sections().flatMap((s) => {
      if (!s.items.length && !s.empty && !s.addChip) return [];
      items.push(...s.items);
      return [h("div", { class: "tp-group" }, h("div", { class: "tp-title" }, s.title),
        h("div", { class: "tp-chips" },
          ...s.items.map((it) => h("button", { type: "button", class: "tp-chip", title: it.desc, onmouseenter: () => showInfo(it), onfocus: () => showInfo(it), onclick: () => { close(false); insertAt(textarea, it.insert, it.raw); } }, it.label)),
          s.addChip && h("button", { type: "button", class: "tp-chip add", onclick: () => addDialog(() => { loadCatalog().then((c) => { cat = c; paint(); }); }) }, "＋ Thêm từ file")),
        !s.items.length && s.empty ? h("div", { class: "muted tp-empty" }, s.empty) : null)];
    }));
    if (!list.firstChild) list.append(h("div", { class: "muted tp-empty" }, "Không có thẻ nào khớp. Thử từ khác, ví dụ “mưa” hoặc “rain”."));
    if (!info) bar.replaceChildren(h("span", { class: "muted" }, "Rê chuột hoặc chọn một thẻ để xem mô tả."));
  }

  search.addEventListener("input", paint);
  search.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); if (items[0]) { close(false); insertAt(textarea, items[0].insert, items[0].raw); } }
    else if (e.key === "ArrowDown") { e.preventDefault(); navEls()[0]?.focus(); }
  });
  list.addEventListener("keydown", (e) => {
    const els = navEls(), i = els.indexOf(document.activeElement);
    if (i < 0) return;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); els[Math.min(i + 1, els.length - 1)].focus(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); if (i === 0) search.focus(); else els[i - 1].focus(); }
  });
  pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
  const outside = (e) => {
    if (!root.isConnected) return document.removeEventListener("click", outside);   // màn đã vẽ lại: gỡ bộ nghe cũ
    if (open && !root.contains(e.target) && !e.target.closest(".modal")) close(false);
  };
  document.addEventListener("click", outside);
  return root;
}
