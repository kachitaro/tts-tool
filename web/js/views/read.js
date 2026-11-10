// Đọc văn bản: một người đọc, hoặc bật "Nhiều người đọc" để viết kịch bản [Tên]: lời.
import { h, debounce, sleep } from "../dom.js";
import { api, sendJSON, sendForm, getJSON } from "../api.js";
import { engines, voices, prefs } from "../store.js";
import { VoicePicker, keyOf, splitKey, kindLabel, displayName, metaLine, previewVoice } from "../voicepicker.js";
import { skeleton, modal, showError, toast, switchEl } from "../ui.js";
import { play } from "../player.js";
import { tagPicker } from "../tagpicker.js";
import { pending } from "../router.js";
import { getSettings, effectiveDefault } from "../defaults.js";

const SAMPLE_SCRIPT = "[Lan]: Chào anh, hôm nay anh khoẻ không?\n[Minh]: Anh khoẻ, cảm ơn em.\n\n[Lan]: Vậy thì tốt quá, mình đi dạo nhé.";
const SPEEDS = [["Chậm", -15], ["Vừa", 0], ["Nhanh", 20]];   // phần trăm gửi cho server (−50…200)
const HINT_F = ["chị", "bà", "cô", "mẹ", "dì", "lan", "hoa", "mai", "linh", "hương", "thảo", "ngọc", "trang", "thu", "nga", "my", "vy", "huệ", "cúc"];
const HINT_M = ["anh", "ông", "bác", "chú", "cậu", "thầy", "bố", "minh", "nam", "hùng", "dũng", "tuấn", "khoa", "long", "phong", "hải", "đức", "sơn"];
const nameGender = (n) => { const t = n.toLowerCase().split(/\s+/); return t.some((x) => HINT_F.includes(x)) ? "nữ" : t.some((x) => HINT_M.includes(x)) ? "nam" : ""; };

// Giữ trạng thái khi chuyển trang rồi quay lại (không mất chữ đã gõ)
const S = {
  multi: false, single: "", script: SAMPLE_SCRIPT, speed: prefs.get("speed", 0), custom: "", pitch: 0, norm: true,
  gap: 350, gapP: 800, cast: {}, speakers: [], lines: [], parseSeq: 0, result: null, job: null, ref: null,
};

export function mountRead(root) {
  let alive = true, E = {}, V = [], engineId = null, ST = null;
  const cleanup = () => { alive = false; };
  root.append(skeleton(4));
  Promise.all([engines(), voices(), getSettings(true)]).then(([e, v, st]) => {
    if (!alive) return;
    E = e; V = v; ST = st;
    const avail = Object.entries(E).filter(([, x]) => x.available).map(([id]) => id);
    if (!avail.length) { root.replaceChildren(h("p", { class: "notice err" }, "Chưa có giọng nào dùng được. Mở Cài đặt → Nâng cao để xem cách cài.")); return; }
    engineId = prefs.get("engine");
    if (!avail.includes(engineId)) { const d = effectiveDefault(V, E, ST).voice; engineId = d && avail.includes(d.engine) ? d.engine : avail.includes("vieneu") ? "vieneu" : avail[0]; }
    applyReuse();
    draw();
  }).catch((e) => { root.replaceChildren(); showError(e); });

  // ───── tiện ích ─────
  const eng = () => E[engineId];
  const usable = (v) => v.usable !== false;
  const voicesOf = (id) => V.filter((v) => v.engine === id && usable(v) && (!v.lang || v.lang.startsWith("vi")));
  function chosenVoice(id = engineId) {
    const list = voicesOf(id), saved = prefs.get("voice:" + id);
    const d = effectiveDefault(V, E, ST).voice;
    return list.find((v) => v.id === saved) || (d && d.engine === id && list.find((v) => v.id === d.id)) || list.find((v) => v.source === "preset" && v.favorite) || list[0] || null;
  }
  const speedPct = () => (S.custom !== "" && !Number.isNaN(+S.custom) ? Math.max(-50, Math.min(200, Math.round(+S.custom))) : S.speed);
  const tagsOf = () => [...new Set((S.multi ? Object.values(E).filter((x) => x.available) : [eng()]).flatMap((x) => (x.capabilities.emotion_tags || [])))];

  function applyReuse() {
    const m = pending.reuse; pending.reuse = null;
    if (!m) return;
    S.result = null; S.job = null;
    if (m.kind === "dialogue") {
      Object.assign(S, { multi: true, script: m.script, speed: m.speed, custom: "", gap: m.gap_ms, gapP: m.paragraph_gap_ms, norm: m.normalize !== false,
        cast: Object.fromEntries(Object.entries(m.cast).map(([n, c]) => [n, c.engine + "|" + c.voice])) });
    } else {
      Object.assign(S, { multi: false, single: m.text, speed: m.speed, custom: "", pitch: m.pitch || 0, norm: m.normalize !== false });
      if (E[m.engine]?.available) { engineId = m.engine; prefs.set("engine", m.engine); }
      if (m.voice) prefs.set("voice:" + m.engine, m.voice);
      if (m.cloned_ref) setTimeout(() => toast("Bản gốc dùng giọng từ file ghi âm. Hãy chọn lại file trong phần Nâng cao nếu muốn dùng nó."), 300);
    }
  }

  // ───── khung chung ─────
  let castBox, countEl, resultBox, goBtn;

  function draw() {
    if (!alive) return;
    const ta = h("textarea", { id: "rText", spellcheck: false, "aria-label": S.multi ? "Kịch bản" : "Văn bản cần đọc", rows: 9,
      placeholder: S.multi ? "[Tên]: lời nói…" : "Dán hoặc gõ văn bản cần đọc vào đây…" });
    ta.value = S.multi ? S.script : S.single;
    countEl = h("span", { class: "muted" });
    const updateCount = () => { countEl.textContent = S.multi ? `${S.lines.length} dòng · ${S.speakers.length} người` : `${ta.value.length.toLocaleString("vi-VN")} ký tự`; };
    ta.addEventListener("input", () => { if (S.multi) { S.script = ta.value; scheduleParse(); } else { S.single = ta.value; } updateCount(); });
    updateCount();
    castBox = h("div", {});
    resultBox = h("div", {});
    goBtn = h("button", { class: "btn primary", id: "goBtn", onclick: generate }, S.multi ? "Tạo audio" : "Đọc");

    root.replaceChildren(
      h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("span", {}, "Đọc văn bản")),
      h("div", { class: "row", style: "justify-content:space-between" }, h("h2", {}, "Đọc văn bản"),
        switchEl("Nhiều người đọc", S.multi, (on) => { S.multi = on; S.result = null; S.job = null; draw(); if (on) parseNow(); })),
      h("p", { class: "lead" }, S.multi ? "Viết lời của từng người theo dạng [Tên]: lời nói. Rồi chọn giọng cho mỗi người." : "Dán hoặc gõ văn bản vào ô bên dưới, rồi bấm Đọc."),
      h("div", { class: "reader" },
        h("div", {}, ta, h("div", { class: "row", style: "margin-top:8px;justify-content:space-between" },
          h("span", { class: "row", style: "gap:12px" }, tagPicker({ textarea: ta, emotionTags: tagsOf, multi: () => S.multi }), countEl),
          h("span", { class: "muted" }, S.multi ? "Mỗi người một dòng. Dòng trống để nghỉ lâu hơn." : "Gõ Ctrl + Enter để đọc nhanh."))),
        S.multi ? castCard() : voiceCard(),
        h("div", { class: "row" }, goBtn),
        resultBox,
        advanced()));
    if (S.multi) paintCast();
    paintResult();
  }

  // ───── một người đọc ─────
  function voiceCard() {
    const avail = Object.entries(E).filter(([, x]) => x.available);
    const v = chosenVoice();
    const seg = avail.length > 1 && h("div", { class: "seg", role: "group", "aria-label": "Loại giọng", style: "margin-bottom:12px" },
      ...avail.map(([id, x]) => h("button", { type: "button", class: id === engineId ? "on" : "", onclick: () => { engineId = id; prefs.set("engine", id); draw(); } }, kindLabel(x))));
    const hint = eng().local ? (eng().loaded === false ? "Tự nhiên hơn. Lần đầu dùng phải tải thêm, có thể mất vài phút." : "Tự nhiên hơn, chạy ngay trên máy bạn.") : "Đọc nhanh nhưng cần có mạng.";
    return h("div", { class: "card flat" }, h("div", { class: "two" },
      h("div", {}, h("label", { class: "field" }, "Giọng đọc"), seg,
        v ? h("div", { class: "vcurrent" }, h("div", { class: "vinfo" }, h("b", {}, displayName(v)), h("div", { class: "muted" }, metaLine(v, E))),
          h("button", { type: "button", class: "play", "aria-label": "Nghe thử giọng", onclick: () => previewVoice(v) }, "▶"),
          h("button", { type: "button", class: "btn small", onclick: () => changeVoice() }, "Đổi giọng"))
          : h("p", { class: "muted" }, "Chưa có giọng nào cho loại này."),
        h("div", { class: "hint" }, hint)),
      h("div", {}, h("label", { class: "field" }, "Đọc nhanh hay chậm?"), speedSeg(draw))));
  }

  function speedSeg(after) {
    return h("div", { class: "seg", role: "group", "aria-label": "Tốc độ đọc" }, ...SPEEDS.map(([t, p]) =>
      h("button", { type: "button", class: S.custom === "" && S.speed === p ? "on" : "", onclick: () => { S.speed = p; S.custom = ""; prefs.set("speed", p); after(); } }, t)));
  }

  function changeVoice() {
    const m = modal([h("h3", {}, "Chọn giọng đọc"), VoicePicker({ voices: V, engines: E, value: (() => { const c = chosenVoice(); return c ? keyOf(c) : ""; })(),
      only: (v) => v.engine === engineId && usable(v), onPick: (v) => { prefs.set("voice:" + engineId, v.id); m.close(); draw(); } }),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))], { wide: true });
  }

  async function generate() {
    if (S.multi) return generateMulti();
    const text = S.single.trim();
    if (!text) return toast("Hãy nhập văn bản cần đọc.", { kind: "error", ms: 4000 });
    const v = chosenVoice();
    const caps = eng().capabilities;
    goBtn.disabled = true; goBtn.textContent = "Đang đọc…";
    const t0 = performance.now();
    try {
      const res = await api("/api/tts", { method: "POST", body: formOf({ text, engine: engineId, voice: v ? v.id : "", speed: speedPct(), pitch: caps.pitch ? S.pitch : 0,
        normalize: caps.normalize ? S.norm : true, ref_audio: caps.clone ? S.ref : null }) });
      const blob = await res.blob();
      const warn = res.headers.get("X-TTS-Warning");
      const url = URL.createObjectURL(blob);
      S.result = { kind: "single", url, ext: blob.type.includes("mpeg") ? "mp3" : "wav", secs: ((performance.now() - t0) / 1000).toFixed(1), text, warn: warn && decodeURIComponent(warn),
        who: S.ref ? "giọng từ file ghi âm" : v ? displayName(v) : "giọng mặc định" };
      paintResult();
      play({ src: url, title: text.slice(0, 60), sub: S.result.who });
    } catch (e) { showError(e, { retry: generate }); }
    finally { goBtn.disabled = false; goBtn.textContent = "Đọc"; }
  }

  const formOf = (o) => { const fd = new FormData(); for (const [k, val] of Object.entries(o)) if (val != null && val !== "") fd.append(k, val); return fd; };

  // ───── nhiều người đọc ─────
  const parseNow = () => parse();
  const scheduleParse = debounce(() => parse(), 400);

  async function parse() {
    const seq = ++S.parseSeq;
    try {
      const d = await sendJSON("/api/dialogue/parse", { script: S.script });
      if (seq !== S.parseSeq || !alive) return;
      S.speakers = d.speakers; S.lines = d.lines; S.parseErr = "";
      suggestCast(d.speakers);
    } catch (e) { if (seq === S.parseSeq) { S.parseErr = e.message; S.speakers = []; S.lines = []; } }
    if (!alive) return;
    if (countEl) countEl.textContent = `${S.lines.length} dòng · ${S.speakers.length} người`;
    paintCast();
  }

  function suggestCast(names) {
    const valid = new Set(V.filter(usable).map(keyOf));
    for (const n of names) if (S.cast[n] && !valid.has(S.cast[n])) delete S.cast[n];
    const pool = V.filter((v) => usable(v) && (!v.lang || v.lang.startsWith("vi"))).sort((a, b) => !!E[b.engine]?.capabilities.clone - !!E[a.engine]?.capabilities.clone);
    const used = new Set(names.map((n) => S.cast[n]).filter(Boolean));
    let alt = 0;
    for (const n of names.filter((x) => !S.cast[x])) {
      const g = nameGender(n) || (++alt % 2 ? "nữ" : "nam");
      const free = pool.filter((v) => !used.has(keyOf(v)));
      const pick = free.find((v) => v.gender === g) || free[0] || pool.find((v) => v.gender === g) || pool[0];
      if (pick) { S.cast[n] = keyOf(pick); used.add(keyOf(pick)); }
    }
  }

  function castCard() {
    return h("div", { class: "card flat" }, h("h3", { style: "font-size:20px;margin-bottom:6px" }, "Ai đọc giọng nào?"), h("div", {}, castBox),
      h("div", { class: "hint" }, "Tool tự tìm các tên trong kịch bản. Gõ thêm một [Tên] mới thì sẽ có thêm một dòng ở đây."),
      h("div", { style: "margin-top:14px" }, h("label", { class: "field" }, "Đọc nhanh hay chậm?"), speedSeg(() => draw())));
  }

  function voiceOfKey(k) { const { engine, voice } = splitKey(k); return V.find((v) => v.engine === engine && v.id === voice); }

  function paintCast() {
    if (!castBox) return;
    if (S.parseErr) { castBox.replaceChildren(h("div", { class: "notice warn" }, S.parseErr)); return; }
    if (!S.speakers.length) { castBox.replaceChildren(h("div", { class: "muted" }, "Chưa có người nào. Viết [Tên]: lời nói ở ô phía trên.")); return; }
    const bad = S.lines.filter((l) => unsupported(l.speaker, l.text).length).map((l) => l.i + 1);
    castBox.replaceChildren(...[...S.speakers.map((n) => {
      const v = S.cast[n] && voiceOfKey(S.cast[n]);
      return h("div", { class: "castrow" }, h("b", {}, n),
        h("button", { type: "button", class: "btn pickbtn", onclick: () => pickFor(n) }, v ? `${displayName(v)} · ${kindLabel(E[v.engine])}` : "Chọn giọng…", " ▾"),
        h("button", { type: "button", class: "play", "aria-label": "Nghe thử giọng của " + n, disabled: !v, onclick: () => v && previewVoice(v) }, "▶"));
    }), bad.length ? h("div", { class: "notice warn" }, `Dòng ${bad.join(", ")} có cảm xúc trong ngoặc vuông mà giọng online không đọc được; phần đó sẽ bị bỏ qua.`) : null].filter(Boolean));
  }

  function pickFor(name) {
    const m = modal([h("h3", {}, `Giọng cho ${name}`), VoicePicker({ voices: V, engines: E, value: S.cast[name], only: usable,
      onPick: (v) => { S.cast[name] = keyOf(v); m.close(); paintCast(); } }),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))], { wide: true });
  }

  function unsupported(speaker, text) {
    const k = S.cast[speaker]; if (!k) return [];
    const own = new Set(E[splitKey(k).engine]?.capabilities.emotion_tags || []);
    const known = tagsOf();
    return (text.match(/\[[^\]]+\]/g) || []).filter((t) => known.includes(t) && !own.has(t));
  }

  async function generateMulti() {
    if (!S.speakers.length) return toast("Kịch bản chưa có dòng nào. Viết dạng [Tên]: lời nói.", { kind: "error", ms: 5000 });
    const missing = S.speakers.filter((n) => !S.cast[n]);
    if (missing.length) return toast("Chưa chọn giọng cho: " + missing.join(", "), { kind: "error", ms: 5000 });
    goBtn.disabled = true; goBtn.textContent = "Đang tạo…";
    try {
      const body = { script: S.script, cast: Object.fromEntries(S.speakers.map((n) => [n, splitKey(S.cast[n])])), speed: speedPct(), gap_ms: +S.gap, paragraph_gap_ms: +S.gapP, normalize: S.norm };
      S.job = (await sendJSON("/api/dialogue", body)).job_id; S.ver = Date.now();
      S.result = { kind: "multi" };
      await pollJob();
    } catch (e) { showError(e, { retry: generateMulti }); }
    finally { if (goBtn) { goBtn.disabled = false; goBtn.textContent = "Tạo audio"; } }
  }

  async function pollJob() {
    for (;;) {
      if (!alive) return;
      const info = await getJSON("/api/dialogue/" + S.job);
      S.result = { kind: "multi", info };
      paintResult();
      if (info.status !== "running") {
        if (info.status === "error") return showError(new Error(info.error || "Không tạo được audio."));
        if (info.audio.wav) play({ src: `/api/dialogue/${info.id}/audio?v=${S.ver}`, title: "Nhiều người đọc", sub: `${info.total} dòng` });
        return;
      }
      await sleep(500);
    }
  }

  // ───── kết quả ─────
  function paintResult() {
    if (!resultBox) return;
    const r = S.result;
    if (!r) return resultBox.replaceChildren();
    if (r.kind === "single") {
      resultBox.replaceChildren(h("div", { class: "card" }, h("div", { class: "audiocard" },
        h("button", { class: "play", "aria-label": "Nghe", onclick: () => play({ src: r.url, title: r.text.slice(0, 60), sub: r.who }) }, "▶"),
        h("div", { style: "flex:1" }, h("b", {}, "Đã đọc xong"), h("div", { class: "muted" }, `${r.who} · mất ${r.secs} giây`)),
        h("a", { class: "btn small", href: r.url, download: `giong-noi.${r.ext}` }, "Tải về (" + r.ext.toUpperCase() + ")")),
        r.warn && h("div", { class: "notice warn" }, r.warn)));
      return;
    }
    const info = r.info;
    if (!info) return resultBox.replaceChildren(h("div", { class: "card" }, h("p", { class: "muted" }, "Đang bắt đầu…")));
    const url = (p) => `/api/dialogue/${info.id}/${p}`;
    const busy = info.status === "running";
    const head = busy
      ? h("div", {}, h("div", { class: "bar" }, h("i", { style: `width:${Math.round((info.done / info.total) * 100)}%` })),
        h("div", { class: "muted", style: "margin-top:6px" }, `Đang tạo… ${info.done}/${info.total} dòng`))
      : h("div", { class: "audiocard" },
        h("button", { class: "play", "aria-label": "Nghe cả đoạn", onclick: () => play({ src: url("audio?v=" + S.ver), title: "Nhiều người đọc", sub: `${info.total} dòng` }) }, "▶"),
        h("div", { style: "flex:1" }, h("b", {}, "Đã tạo xong"), h("div", { class: "muted" }, `${info.total} dòng`)),
        h("a", { class: "btn small", href: url("audio?fmt=wav"), download: "hoi-thoai.wav" }, "Tải về (WAV)"),
        info.audio.mp3 && h("a", { class: "btn small", href: url("audio?fmt=mp3"), download: "hoi-thoai.mp3" }, "Tải về (MP3)"));
    const redo = async (l, ev) => {
      ev.target.disabled = true;
      try {
        await sendJSON(`/api/dialogue/${S.job}/line/${l.i}`, {});
        S.ver = Date.now();
        toast(`Đã đọc lại dòng ${l.i + 1} với cách đọc khác.`);
        await pollJob();
      } catch (e) { showError(e); }
    };
    const lineRow = (l) => h("div", { class: "dline" },
      h("b", {}, `${l.i + 1}. ${l.speaker}`),
      h("span", {}, l.text, l.error && h("small", { class: "muted" }, " — " + l.error)),
      h("span", { class: "row", style: "flex-wrap:nowrap" },
        h("button", { class: "play", "aria-label": "Nghe dòng " + (l.i + 1), disabled: l.status !== "done",
          onclick: () => play({ src: url(`line/${l.i}/audio?v=${S.ver}`), title: l.text.slice(0, 60), sub: l.speaker }) }, "▶"),
        h("button", { class: "btn small", disabled: busy, onclick: (ev) => redo(l, ev) }, "Đọc lại dòng này")));
    resultBox.replaceChildren(h("div", { class: "card" }, head, h("div", { style: "margin-top:10px" }, ...info.lines.map(lineRow))));
  }

  // ───── Nâng cao ─────
  function advanced() {
    const caps = eng().capabilities;
    const num = (label, key, attrs) => h("div", {}, h("label", { class: "field" }, label), h("input", { type: "number", value: S[key], ...attrs, oninput: (e) => { S[key] = e.target.value; } }));
    return h("details", { class: "adv" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body stack" },
      h("div", {}, h("label", { class: "field" }, "Tốc độ tinh chỉnh (%)"),
        h("input", { type: "number", min: -50, max: 200, step: 5, placeholder: "Để trống để dùng Chậm / Vừa / Nhanh ở trên", value: S.custom, oninput: (e) => { S.custom = e.target.value; } }),
        h("div", { class: "hint" }, "−50 là chậm một nửa, 100 là nhanh gấp đôi. Điền số ở đây thì thay cho ba nút bên trên.")),
      S.multi ? h("div", { class: "two" }, num("Nghỉ giữa các câu thoại (mili-giây)", "gap", { min: 0, max: 5000 }), num("Nghỉ giữa các đoạn (mili-giây)", "gapP", { min: 0, max: 10000 })) : null,
      !S.multi && caps.pitch ? h("div", {}, h("label", { class: "field" }, "Cao độ giọng"), h("input", { type: "range", min: -50, max: 50, step: 5, value: S.pitch, style: "width:100%;accent-color:var(--accent)", oninput: (e) => { S.pitch = +e.target.value; } })) : null,
      !S.multi && caps.clone ? h("div", {}, h("label", { class: "field" }, "Dùng giọng từ file ghi âm (chỉ lần này)"),
        h("input", { type: "file", accept: "audio/*", onchange: (e) => { S.ref = e.target.files[0] || null; } }),
        h("div", { class: "hint" }, "File 3–8 giây, giọng rõ. Muốn dùng lại về sau, hãy thêm vào Giọng đọc.")) : null,
      switchEl("Tự đọc số, ngày tháng, đơn vị cho đúng (chuẩn hoá văn bản)", S.norm, (on) => { S.norm = on; }),
      S.multi ? projects() : null));
  }

  function projects() {
    const sel = h("select", { "aria-label": "Dự án đã lưu", style: "max-width:260px" }, h("option", { value: "" }, "— dự án đã lưu —"));
    const name = h("input", { type: "text", placeholder: "Tên dự án để lưu", style: "max-width:220px" });
    const load = async (selectId = "") => {
      try { const list = await getJSON("/api/projects"); sel.replaceChildren(h("option", { value: "" }, list.length ? "— chọn dự án —" : "— chưa có dự án —"), ...list.map((p) => h("option", { value: p.id }, p.name))); sel.value = selectId; }
      catch (e) { showError(e); }
    };
    load();
    return h("div", {}, h("label", { class: "field" }, "Dự án (lưu kịch bản và giọng để dùng lại)"), h("div", { class: "row" }, sel,
      h("button", { type: "button", class: "btn small", onclick: async () => {
        if (!sel.value) return toast("Hãy chọn một dự án.", { kind: "error", ms: 3000 });
        try { const p = await getJSON("/api/projects/" + sel.value);
          Object.assign(S, { script: p.script, speed: p.speed, custom: "", gap: p.gap_ms, gapP: p.paragraph_gap_ms, norm: p.normalize !== false,
            cast: Object.fromEntries(Object.entries(p.cast).map(([n, c]) => [n, c.engine + "|" + c.voice])) });
          draw(); parseNow(); toast(`Đã mở dự án “${p.name}”.`); } catch (e) { showError(e); } } }, "Mở"),
      h("button", { type: "button", class: "btn small danger", onclick: async () => {
        if (!sel.value) return; try { await api("/api/projects/" + sel.value, { method: "DELETE" }); await load(); toast("Đã xoá dự án."); } catch (e) { showError(e); } } }, "Xoá")),
      h("div", { class: "row", style: "margin-top:8px" }, name, h("button", { type: "button", class: "btn small", onclick: async () => {
        const nm = name.value.trim() || (sel.selectedOptions[0] && sel.value ? sel.selectedOptions[0].textContent : "");
        if (!nm) return toast("Hãy đặt tên cho dự án.", { kind: "error", ms: 3000 });
        try { const p = await sendJSON("/api/projects", { name: nm, script: S.script, cast: Object.fromEntries(S.speakers.filter((n) => S.cast[n]).map((n) => [n, splitKey(S.cast[n])])),
          speed: speedPct(), gap_ms: +S.gap, paragraph_gap_ms: +S.gapP, normalize: S.norm }); await load(p.id); toast(`Đã lưu dự án “${p.name}”.`); } catch (e) { showError(e); } } }, "Lưu thành dự án")));
  }

  return cleanup;
}
