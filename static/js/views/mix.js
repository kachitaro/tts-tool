// Pha giọng mới: chọn 2 giọng bằng thẻ, kéo thanh giữa hai giọng, thả tay là tự nghe thử, "Lưu giọng này".
import { h } from "../dom.js";
import { api } from "../api.js";
import { explain } from "../errors.js";
import { engines, voices, resetVoices, prefs } from "../store.js";
import { VoicePicker, keyOf, displayName, metaLine, previewVoice } from "../voicepicker.js";
import { skeleton, showError, toast, modal } from "../ui.js";
import { play } from "../player.js";
import { go } from "../router.js";
import { choiceSeg, GENDERS, REGIONS, AGES } from "./voice-add.js";

const SAMPLE = "Xin chào, đây là giọng đọc vừa được pha. Bạn nghe thử xem có hợp không nhé.";

export function mountMix(root) {
  let alive = true, eng = {}, E = null, V = [];
  const S = { a: null, b: null, pos: 50, text: SAMPLE, auto: prefs.get("mix:auto", true), busy: false, err: "", lastUrl: "" };
  let ctl = null, timer = null;
  const area = h("div", {}, skeleton(4));
  root.append(
    h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("a", { href: "#/giong" }, "Giọng đọc"), " › ", h("span", {}, "Pha giọng mới")),
    h("h2", {}, "Pha giọng mới"),
    h("p", { class: "lead" }, "Chọn hai giọng, rồi kéo thanh để quyết định giọng mới giống bên nào hơn. Thả tay ra là tool đọc thử ngay."), area);

  const pct = () => ({ a: 100 - S.pos, b: S.pos });
  const label = () => { const p = pct(); return `${p.a}% ${displayName(S.a)} · ${p.b}% ${displayName(S.b)}`; };

  function pickDialog(side) {
    const other = side === "a" ? "b" : "a";
    const m = modal([h("h3", {}, side === "a" ? "Chọn giọng thứ nhất" : "Chọn giọng thứ hai"),
      VoicePicker({ voices: V, engines: eng, value: keyOf(S[side]), only: (v) => v.engine === E.id && v.usable !== false,
        onPick: (v) => { if (keyOf(v) === keyOf(S[other])) S[other] = S[side]; S[side] = v; m.close(); draw(); schedule(); } }),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))], { wide: true });
  }

  const voiceCard = (side, title) => {
    const v = S[side];
    return h("div", { class: "card flat mixcard" }, h("div", { class: "hint", style: "margin:0 0 4px" }, title),
      h("b", { class: "ellip", style: "font-size:20px" }, displayName(v)), h("div", { class: "muted" }, metaLine(v, eng)),
      h("div", { class: "row", style: "margin-top:12px" },
        h("button", { type: "button", class: "play", "aria-label": "Nghe thử " + displayName(v), onclick: () => previewVoice(v) }, "▶"),
        h("button", { type: "button", class: "btn small", onclick: () => pickDialog(side) }, "Đổi giọng")));
  };

  function schedule() { clearTimeout(timer); if (S.auto) timer = setTimeout(preview, 600); }

  async function preview() {
    clearTimeout(timer);
    if (ctl) ctl.abort();
    const mine = (ctl = new AbortController());
    S.err = ""; S.busy = true; paintStatus();
    const fd = new FormData();
    fd.append("engine", E.id); fd.append("voice_a", S.a.id); fd.append("voice_b", S.b.id);
    fd.append("slider", String((100 - S.pos) / 100)); fd.append("text", S.text.trim() || SAMPLE);
    try {
      const blob = await (await api("/api/mix", { method: "POST", body: fd, signal: mine.signal })).blob();
      if (!alive || mine.signal.aborted) return;
      if (S.lastUrl) URL.revokeObjectURL(S.lastUrl);
      S.lastUrl = URL.createObjectURL(blob);
      S.busy = false; paintStatus();
      await play({ src: S.lastUrl, title: `Giọng pha: ${displayName(S.a)} × ${displayName(S.b)}`, sub: label() });
    } catch (e) {
      if (mine.signal.aborted || (e && e.name === "AbortError") || !alive) return;
      const x = explain(e); S.err = x.title + (x.tip ? " " + x.tip : ""); S.busy = false; paintStatus();
    }
  }

  const status = h("div", { class: "hint", role: "status", "aria-live": "polite" });
  function paintStatus() {
    status.className = "hint" + (S.err ? " err" : "");
    status.textContent = S.err || (S.busy ? "Đang pha giọng… lần đầu có thể mất vài giây." : "");
  }

  function saveDialog() {
    const same = (x, y) => (x && x === y ? x : "");
    const F = { name: `${displayName(S.a)} × ${displayName(S.b)}`.slice(0, 60), gender: same(S.a.gender, S.b.gender), region: same(S.a.region, S.b.region), age: "", tags: "", description: "", err: "", busy: false };
    const box = h("div", {});
    const m = modal(box);
    const drawSave = () => box.replaceChildren(
      h("h3", {}, "Lưu giọng này"), h("p", { class: "muted" }, label()),
      h("div", { class: "stack" },
        h("div", {}, h("label", { class: "field", for: "mxName" }, "Tên giọng mới"), h("input", { id: "mxName", type: "text", maxlength: 60, value: F.name, oninput: (e) => { F.name = e.target.value; } })),
        h("div", { class: "two" }, choiceSeg("Giọng nam hay nữ?", GENDERS, () => F.gender, (x) => { F.gender = x; }), choiceSeg("Giọng vùng nào?", REGIONS, () => F.region, (x) => { F.region = x; })),
        choiceSeg("Giọng nghe bao nhiêu tuổi?", AGES, () => F.age, (x) => { F.age = x; }),
        F.err && h("div", { class: "notice err", role: "alert" }, F.err)),
      h("div", { class: "row end", style: "margin-top:18px" },
        h("button", { type: "button", class: "btn", onclick: () => m.close() }, "Huỷ"),
        h("button", { type: "button", class: "btn primary", id: "mixSaveGo", disabled: F.busy, onclick: go_ }, F.busy ? "Đang lưu…" : "Lưu giọng này")));
    async function go_() {
      if (!F.name.trim()) { F.err = "Hãy đặt tên cho giọng."; return drawSave(); }
      F.busy = true; drawSave();
      const fd = new FormData();
      fd.append("engine", E.id); fd.append("voice_a", S.a.id); fd.append("voice_b", S.b.id); fd.append("slider", String((100 - S.pos) / 100));
      fd.append("name", F.name.trim()); fd.append("gender", F.gender); fd.append("region", F.region); fd.append("age", F.age); fd.append("tags", "pha");
      try {
        const meta = await (await api("/api/mix/save", { method: "POST", body: fd })).json();
        resetVoices(); m.close();
        toast(`Đã lưu giọng “${meta.name}”. Bạn tìm thấy nó trong nhóm Giọng của tôi.`);
        go("/giong");
      } catch (e) { const x = explain(e); F.err = x.title + (x.tip ? " " + x.tip : ""); F.busy = false; drawSave(); }
    }
    drawSave();
  }

  function draw() {
    const a = S.a, b = S.b;
    const range = h("input", { type: "range", id: "mixPos", min: 0, max: 100, step: 1, value: S.pos, "aria-label": `Pha giọng: kéo về ${displayName(a)} hoặc ${displayName(b)}`,
      oninput: (e) => { S.pos = +e.target.value; mixLbl.textContent = label(); }, onchange: () => schedule() });
    const mixLbl = h("div", { class: "mixlbl", id: "mixLbl" }, label());
    area.replaceChildren(
      h("div", { class: "two" }, voiceCard("a", "Giọng thứ nhất"), voiceCard("b", "Giọng thứ hai")),
      h("div", { class: "card flat", style: "margin-top:16px" },
        h("div", { class: "mixends" }, h("b", { class: "ellip" }, displayName(a)), h("b", { class: "ellip", style: "text-align:right" }, displayName(b))),
        range, mixLbl,
        h("div", { class: "row", style: "margin-top:12px" },
          h("button", { type: "button", class: "btn", id: "mixPreviewBtn", onclick: preview }, "▶ Nghe thử"), status)),
      h("div", { class: "row", style: "margin-top:18px" },
        h("button", { type: "button", class: "btn primary", id: "mixSave", onclick: saveDialog }, "Lưu giọng này"),
        h("a", { class: "btn ghost", href: "#/giong" }, "Thôi, quay lại")),
      h("details", { class: "adv" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body stack", style: "--gap:10px" },
        h("div", {}, h("label", { class: "field", for: "mixText" }, "Câu đọc thử"), h("input", { id: "mixText", type: "text", value: S.text, oninput: (e) => { S.text = e.target.value; } })),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.auto, onchange: (e) => { S.auto = e.target.checked; prefs.set("mix:auto", S.auto); } }), h("span", {}, "Tự nghe thử khi thả tay khỏi thanh kéo")))));
    paintStatus();
  }

  (async () => {
    try {
      [eng, V] = await Promise.all([engines(), voices(true)]);
      if (!alive) return;
      const found = Object.entries(eng).find(([, e]) => e.available && e.capabilities && e.capabilities.mix);
      E = found && { ...found[1], id: found[0] };   // /api/engines là bảng theo id
      if (!E) { area.replaceChildren(h("div", { class: "notice err" }, "Máy này chưa có giọng nào cho phép pha giọng. Cần cài giọng trên máy (VieNeu) trước.")); return; }
      const pool = V.filter((v) => v.engine === E.id && v.usable !== false && (!v.lang || v.lang.startsWith("vi")));
      if (pool.length < 2) { area.replaceChildren(h("div", { class: "notice err" }, "Cần ít nhất hai giọng dùng được để pha.")); return; }
      V = pool;
      S.a = pool[0]; S.b = pool.find((v) => v.gender && v.gender !== pool[0].gender) || pool[1];
      draw();
    } catch (e) { area.replaceChildren(); showError(e); }
  })();
  return () => { alive = false; clearTimeout(timer); if (ctl) ctl.abort(); };
}
