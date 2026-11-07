// Bộ chọn giọng dùng chung: tìm, lọc (yêu thích · nam / nữ · miền Bắc / Trung / Nam), 2 nhóm "Của tôi" và "Có sẵn".
import { h } from "./dom.js";
import { api, sendForm } from "./api.js";
import { resetVoices } from "./store.js";
import { play } from "./player.js";
import { showError } from "./ui.js";

export const keyOf = (v) => `${v.engine}|${v.id}`;
export const splitKey = (k) => { const i = k.indexOf("|"); return { engine: k.slice(0, i), voice: k.slice(i + 1) }; };
export const REGION = { bac: "miền Bắc", trung: "miền Trung", nam: "miền Nam" };
export const kindLabel = (engine) => (engine && engine.local ? "Giọng trên máy" : "Giọng online");
export const isMine = (v) => v.source !== "preset";
const PREVIEW_TEXT = "Xin chào, đây là giọng đọc thử.";
const previews = new Map();

export const displayName = (v) => v.name || v.label || v.id;

export function metaLine(v, engines) {
  const g = v.gender ? v.gender[0].toUpperCase() + v.gender.slice(1) : "";
  const kind = v.source === "mix" ? "Giọng pha" : v.source === "clone" ? "Giọng ghi âm" : kindLabel(engines[v.engine]);
  return [g, REGION[v.region], kind].filter(Boolean).join(" · ");
}

/** Nghe thử một giọng bằng trình phát dính đáy (nhớ lại lần đầu để lần sau phát ngay). */
export async function previewVoice(v) {
  try {
    const key = keyOf(v);
    let url = previews.get(key);
    if (!url) {
      const res = v.id.startsWith("lib:")
        ? await api("/api/library/" + v.id.slice(4) + "/preview")
        : await sendForm("/api/tts", { text: PREVIEW_TEXT, engine: v.engine, voice: v.id });
      url = URL.createObjectURL(await res.blob());
      previews.set(key, url);
    }
    await play({ src: url, title: displayName(v), sub: "Nghe thử giọng" });
  } catch (e) { showError(e); }
}

export const forgetPreview = (v) => previews.delete(keyOf(v));

export async function setFavorite(v, on) {
  await sendForm("/api/favorites", { engine: v.engine, voice: v.id, favorite: on });
  resetVoices();
  v.favorite = on;
}

/**
 * VoicePicker({ voices, engines, value, onPick, actions, only })
 *  value   : khoá "engine|id" đang chọn (tô sáng)
 *  onPick  : bấm vào dòng giọng → chọn (bỏ qua nếu không truyền)
 *  actions : (v) => Node[] nút thêm cuối dòng (ví dụ "Dùng để đọc")
 *  only    : (v) => bool lọc cứng trước (ví dụ chỉ giọng của một loại)
 */
export function VoicePicker({ voices, engines, value, onPick, actions, only, tall = false }) {
  const st = { q: "", fav: false, gender: "", region: "" };
  const list = h("div", { class: "vlist" + (tall ? " free" : "") });
  const base = voices.filter((v) => (!only || only(v)) && (!v.lang || v.lang.startsWith("vi")));

  const chip = (label, on, fn) => h("button", { type: "button", class: "chip" + (on ? " on" : ""), onclick: () => { fn(); paintChips(); paint(); } }, label);
  const chips = h("div", { class: "chiprow" });
  function paintChips() {
    chips.replaceChildren(
      chip("♥ Yêu thích", st.fav, () => { st.fav = !st.fav; }),
      h("span", { class: "sep" }),
      chip("Giọng nam", st.gender === "nam", () => { st.gender = st.gender === "nam" ? "" : "nam"; }),
      chip("Giọng nữ", st.gender === "nữ", () => { st.gender = st.gender === "nữ" ? "" : "nữ"; }),
      h("span", { class: "sep" }),
      ...["bac", "trung", "nam"].map((r) => chip(REGION[r][0].toUpperCase() + REGION[r].slice(1), st.region === r, () => { st.region = st.region === r ? "" : r; })),
    );
  }

  const row = (v) => {
    const usable = v.usable !== false;
    const sel = value && keyOf(v) === value;
    const fav = h("button", { type: "button", class: "fav" + (v.favorite ? " on" : ""), "aria-label": v.favorite ? "Bỏ yêu thích" : "Yêu thích", title: v.favorite ? "Bỏ yêu thích" : "Yêu thích",
      onclick: async (e) => { e.stopPropagation(); try { await setFavorite(v, !v.favorite); paint(); } catch (er) { showError(er); } } }, v.favorite ? "♥" : "♡");
    const playBtn = h("button", { type: "button", class: "play", "aria-label": "Nghe thử " + displayName(v), title: "Nghe thử", disabled: !usable,
      onclick: (e) => { e.stopPropagation(); previewVoice(v); } }, "▶");
    const r = h("div", { class: "vrow" + (sel ? " sel" : "") + (usable ? "" : " dim") + (onPick && usable ? " pick" : ""), role: onPick ? "radio" : undefined, "aria-checked": onPick ? String(!!sel) : undefined,
      tabindex: onPick && usable ? 0 : undefined,
      onclick: () => { if (onPick && usable) onPick(v); },
      onkeydown: (e) => { if ((e.key === "Enter" || e.key === " ") && onPick && usable) { e.preventDefault(); onPick(v); } } },
      h("div", { class: "vinfo" },
        h("b", {}, (v.source === "mix" ? "🎚️ " : v.source === "clone" ? "🎙️ " : "") + displayName(v), sel && h("span", { class: "tick" }, " ✓ Đang chọn")),
        h("div", { class: "muted" }, metaLine(v, engines)),
        !usable && h("div", { class: "muted" }, "⚠ " + (v.unusable_reason || "Chưa dùng được"))),
      h("div", { class: "vact" }, playBtn, fav, ...(actions ? actions(v) : [])));
    return r;
  }

  function paint() {
    const q = st.q.trim().toLowerCase();
    const shown = base.filter((v) => (!q || (displayName(v) + " " + (v.tags || []).join(" ") + " " + (v.description || "")).toLowerCase().includes(q))
      && (!st.fav || v.favorite) && (!st.gender || v.gender === st.gender) && (!st.region || v.region === st.region));
    const groups = [["Của tôi", shown.filter(isMine)], ["Có sẵn", shown.filter((v) => !isMine(v))]];
    const byFav = (a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0);
    list.replaceChildren(...groups.filter(([, g]) => g.length).flatMap(([name, g]) => [h("div", { class: "vgroup" }, name + ` · ${g.length}`), ...g.sort(byFav).map(row)]));
    if (!shown.length) list.append(h("p", { class: "muted" }, "Không có giọng nào khớp. Thử bỏ bớt bộ lọc."));
  }

  const search = h("input", { type: "search", placeholder: "Tìm giọng theo tên…", "aria-label": "Tìm giọng", oninput: (e) => { st.q = e.target.value; paint(); } });
  paintChips(); paint();
  return h("div", { class: "vpicker" }, search, chips, list);
}
