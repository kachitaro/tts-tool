// Trang truyện = bảng điều khiển: tiến độ lớn, Tạm dừng / Tiếp tục, Tải về, danh sách chương, tên riêng, cài đặt.
import { h, fmtLeft, sleep, sizeText, scrollPage } from "../dom.js";
import { saveAs } from "../appenv.js";
import { api, getJSON, sendJSON } from "../api.js";
import { go } from "../router.js";
import { skeleton, showError, toast, confirmBox, modal, savedToast } from "../ui.js";
import { play } from "../player.js";
import { menuButton } from "../menu.js";
import { Pager, PAGE_SIZE } from "../pager.js";
import { askNotifyPermission } from "../overview.js";
import { getBook, chaptersOf, queueOf, runQueue, startTrial, dismissTrial, trial, deleteBook } from "../bookapi.js";
import { mountNamesTab } from "./book-names.js";
import { mountSettingsTab } from "./book-settings.js";

const fmtN = (n) => Number(n).toLocaleString("vi-VN");
const fmtDur = (s) => (s >= 3600 ? `${(s / 3600).toFixed(1).replace(".", ",")} giờ` : s >= 60 ? `${Math.round(s / 60)} phút` : `${Math.round(s)} giây`);

export { fmtN };

const FILTERS = [["all", "Tất cả"], ["done", "Đã xong"], ["wait", "Đang chờ"], ["todo", "Chưa tạo"], ["stale", "Cần tạo lại"], ["error", "Lỗi"]];
const isDone = (c) => c.status === "done" || c.status === "exported";
const matchers = {
  all: () => true, done: isDone, wait: (c) => c.status === "queued" || c.status === "running", todo: (c) => c.status === "pending",
  stale: (c) => c.stale, error: (c) => c.status === "error",
};
const tabState = new Map();   // id → { tab, filter, page }

export function mountBook(root, { id }) {
  let alive = true, book = null, chs = [], q = null, sig = "", tabCleanup = null, timer = null;
  const ts = tabState.get(id) || { tab: "chuong", filter: "all", page: 0 };
  tabState.set(id, ts);
  const top = h("div", {}), banners = h("div", { class: "stack", style: "--gap:12px;margin-bottom:var(--gap)" }), tabs = h("div", {}), content = h("div", {});
  root.append(h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("a", { href: "#/sach" }, "Làm sách nói"), " › ", h("span", { id: "bcTitle" }, "…")),
    banners, top, tabs, content);
  top.append(h("div", { class: "card" }, skeleton(3)));

  async function load() {
    try { [book, chs, q] = await Promise.all([getBook(id), chaptersOf(id).catch(() => []), queueOf(id)]); } catch (e) { root.replaceChildren(); showError(e); return false; }
    if (!alive) return false;
    if (book.status !== "ready") { go(`/sach/${id}/kiem-tra`); return false; }
    document.getElementById("bcTitle").textContent = book.title;
    return true;
  }

  // ───── khối trên cùng ─────
  const doneCount = () => (q.counts.done || 0) + (q.counts.exported || 0);
  function paintTop() {
    const total = q.chapters, done = doneCount(), r = q.running && q.running.book === id ? q.running : null;
    const frac = total ? (done + (r && r.seg_total ? r.seg_done / r.seg_total : 0)) / total : 0;
    const active = q.state === "running" || q.state === "pausing";
    const stale = chs.filter((c) => c.stale).length;
    const tr = q.trial;   // do server ghi vào book.json: {limit, done_at}
    const idle = q.state === "idle" || (q.state === "paused" && !r);
    // banner "đã xong 5 chương thử" (tool đã dừng, chờ bạn nghe thử)
    banners.replaceChildren(...[
      tr && tr.done_at && q.state === "idle" && q.remaining > 0 ? h("div", { class: "notice ok", style: "margin:0" }, h("b", {}, `Đã xong ${done} chương thử. `), "Nghe thử rồi bấm Tạo tiếp.",
        h("div", { class: "row", style: "margin-top:8px" }, h("button", { class: "btn primary small", onclick: async () => { await start({}); } }, "Tạo tiếp"),
          h("button", { class: "btn small", onclick: async () => { try { await dismissTrial(id); await refresh(true); } catch (e) { showError(e); } } }, "Để sau"))) : null,
      stale ? h("div", { class: "notice warn", style: "margin:0" }, h("b", {}, `${fmtN(stale)} chương cần tạo lại`), " vì bạn đã đổi cài đặt (giọng, tốc độ, cách đọc tên…) sau khi tạo. ",
        h("button", { class: "btn small", style: "margin-left:6px", onclick: () => start({ stale_only: true, regenerate: true }) }, "Tạo lại")) : null,
      q.note ? h("div", { class: "notice warn", style: "margin:0" }, q.note) : null].filter(Boolean));
    const left = q.paused ? "Đang tạm dừng. Bấm “Tiếp tục” để tạo tiếp." : q.estimate_seconds != null && active ? `Còn khoảng ${fmtLeft(q.estimate_seconds)}. Bạn có thể để máy chạy qua đêm, tool sẽ báo khi xong.` : active ? "Đang tính thời gian còn lại…" : "";
    const allDone = total > 0 && done === total;
    const primary = active || q.paused
      ? h("button", { class: "btn primary", onclick: togglePause }, q.paused ? "▶ Tiếp tục" : "❚❚ Tạm dừng")
      : allDone ? downloadButton(true) : q.remaining > 0 ? h("button", { class: "btn primary", onclick: () => start({}) }, done ? "Tạo các chương còn lại" : "Tạo cả truyện") : null;
    top.replaceChildren(h("div", { class: "card dash" },
      h("div", {}, h("h2", {}, book.title), h("div", { class: "muted" }, [book.author, `giọng ${voiceLabel()}`].filter(Boolean).join(" · "))),
      h("div", {}, h("div", { class: "big" }, fmtN(done), " ", h("span", { style: "font-size:24px;color:var(--muted);font-weight:500" }, `trên ${fmtN(total)} chương`)),
        h("div", { class: "bar big", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": Math.round(frac * 100), "aria-label": "Tiến độ tạo sách nói", style: "margin:14px 0 8px" }, h("i", { style: `width:${(frac * 100).toFixed(1)}%` })),
        h("div", { class: "muted" }, r ? `Đang tạo chương ${r.n}: ${r.title || ""}. ` : "", left || (allDone ? "Đã xong cả truyện." : ""))),
      h("div", { class: "row" }, primary,
        !allDone && done > 0 ? downloadButton(false) : null,
        active || q.paused || q.queued_book ? h("button", { class: "btn danger", onclick: cancelAll }, "Dừng hẳn") : null,
        !active && !q.paused && done === 0 && total > 5 ? h("button", { class: "btn", onclick: () => { askNotifyPermission(); startTrial(id, 5).then(() => refresh(true)).catch(showError); } }, "Tạo thử 5 chương") : null)));
  }

  let voiceName = "";
  const voiceLabel = () => voiceName || book.voice.voice.replace(/^lib:/, "");
  getJSON("/api/voices").then((vs) => { const v = vs.find((x) => x.engine === book.voice.engine && x.id === book.voice.voice); if (v && alive) { voiceName = v.name || v.label; if (book) paintTop(); } }).catch(() => {});

  async function start(body) {
    askNotifyPermission();
    try { await runQueue(id, body); await refresh(true); } catch (e) { showError(e); }
  }
  async function togglePause() {
    try { await api("/api/queue/" + (q.paused ? "resume" : "pause"), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await refresh(true); } catch (e) { showError(e); }
  }
  async function cancelAll() {
    if (!(await confirmBox({ title: "Dừng hẳn việc đang tạo?", body: "Các chương đã xong vẫn được giữ. Chương đang tạo dở dừng lại sau đoạn hiện tại và có thể tạo tiếp sau.", ok: "Dừng hẳn", danger: true }))) return;
    try { await sendJSON("/api/queue/cancel", { book: id }); await refresh(true); } catch (e) { showError(e); }
  }

  // ───── Tải về ─────
  function downloadButton(primary) { return h("button", { class: "btn" + (primary ? " primary" : ""), onclick: openDownload }, "⬇ Tải về"); }

  function openDownload() {
    const done = (chs.filter((c) => c.status === "done")).length, gone = chs.filter((c) => c.status === "exported").length;
    if (!done) return toast(gone ? "Các chương này đã được tải về trước đó và bản gốc đã xoá. Tạo lại chương nếu muốn tải lần nữa." : "Chưa có chương nào xong để tải về.", { kind: "error", ms: 6000 });
    const state = { kbps: 64, from: "", to: "" };
    const msg = h("div", { class: "hint" }), files = h("div", { class: "stack", style: "--gap:6px;margin-top:10px" });
    const paintFiles = (list) => files.replaceChildren(...list.map((f) => h("div", {}, "Đã chuẩn bị: ", h("a", { href: `/api/books/${encodeURIComponent(id)}/export/${encodeURIComponent(f.name)}`, download: f.name }, `${f.name} (${sizeText(f.size)})`))));
    paintFiles(q.exports || []);
    const chosen = () => { if (state.from === "" && state.to === "") return null; const a = +state.from || 1, z = +state.to || chs.length; return Array.from({ length: Math.max(0, z - a + 1) }, (_, i) => a + i); };
    async function go2(kind) {
      msg.textContent = "Đang chuẩn bị…";
      try {
        const j = await sendJSON(`/api/books/${encodeURIComponent(id)}/export`, { kind, kbps: state.kbps, chapters: chosen() });
        for (;;) {
          const s = await getJSON("/api/exports/" + j.id);
          if (s.status === "error") throw new Error(s.error);
          if (s.status === "done") { msg.textContent = `Xong: ${s.chapters} chương.`; paintFiles([{ name: s.file, size: s.size }, ...(q.exports || []).filter((f) => f.name !== s.file)]); await refresh(true); return; }
          msg.textContent = `Đang chuẩn bị… ${Math.round((100 * s.done) / Math.max(1, s.total))}%`;
          await sleep(600);
        }
      } catch (e) { msg.textContent = ""; showError(e); }
    }
    const opt = (title, text, kind) => h("button", { type: "button", class: "bigopt", onclick: () => go2(kind) }, h("b", {}, title), h("span", { class: "muted" }, text));
    const m = modal([h("h3", {}, "Tải về"), h("p", { class: "muted" }, `${fmtN(done)} chương đã xong sẽ được tải${chs.length - done - gone ? `. ${fmtN(chs.length - done - gone)} chương chưa xong sẽ không có trong file.` : "."}`),
      h("div", { class: "stack", style: "--gap:10px" },
        opt("Từng chương (MP3)", "Một file zip, mỗi chương một file MP3. Dễ chép vào điện thoại hoặc đầu đĩa.", "mp3zip"),
        opt("Một file nghe trên điện thoại (có mục lục)", "Nghe liền mạch, bấm nhảy tới chương bất kỳ (định dạng .m4b: dùng ứng dụng sách nói như Apple Books, Smart AudioBook Player).", "m4b")),
      msg, files,
      h("details", { class: "adv" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body two" },
        h("div", {}, h("label", { class: "field" }, "Chất lượng MP3"), (() => { const s = h("select", { onchange: (e) => { state.kbps = +e.target.value; } }, ...[64, 80, 96].map((k) => h("option", { value: k }, `${k} kbps${k === 64 ? " (nhỏ, đủ nghe giọng nói)" : ""}`))); return s; })()),
        h("div", {}, h("label", { class: "field" }, "Chỉ tải chương từ … đến …"), h("div", { class: "row", style: "flex-wrap:nowrap" },
          h("input", { type: "number", min: 1, placeholder: "1", "aria-label": "Từ chương", oninput: (e) => { state.from = e.target.value; } }), "đến",
          h("input", { type: "number", min: 1, placeholder: String(chs.length), "aria-label": "Đến chương", oninput: (e) => { state.to = e.target.value; } }))))),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))]);
  }

  // ───── thẻ phụ ─────
  function paintTabs() {
    tabs.replaceChildren(h("div", { class: "tabs", role: "tablist" }, ...[["chuong", "Các chương"], ["ten", "Cách đọc tên riêng"], ["caidat", "Cài đặt"]].map(([k, t]) =>
      h("button", { type: "button", role: "tab", "aria-selected": String(ts.tab === k), class: ts.tab === k ? "on" : "", onclick: () => { ts.tab = k; paintTabs(); } }, t))));
    if (tabCleanup) { tabCleanup(); tabCleanup = null; }
    content.replaceChildren();
    if (ts.tab === "chuong") paintChapters();
    else if (ts.tab === "ten") tabCleanup = mountNamesTab(content, { id, book, onChanged: () => refresh(true) });
    else tabCleanup = mountSettingsTab(content, { id, book, q, onChanged: async () => { await reloadBook(); await refresh(true); } });
  }
  async function reloadBook() { book = await getBook(id); }

  // ───── danh sách chương (phân trang) ─────
  function statusText(c) {
    if (c.status === "running") return c.segments && c.segments.total ? `Đang tạo… ${Math.round((100 * c.segments.done) / c.segments.total)}%` : "Đang tạo…";
    if (c.stale) return "Cần tạo lại (bạn đã đổi cài đặt)";
    if (c.status === "done") return `Đã xong · ${fmtDur(c.audio_seconds || 0)}`;
    if (c.status === "exported") return "Đã tải về · bản gốc đã xoá, tạo lại nếu muốn nghe hoặc sửa";
    if (c.status === "queued") return c.segments && c.segments.done ? `Đang chờ (đã làm dở ${c.segments.done}/${c.segments.total})` : "Đang chờ";
    if (c.status === "error") return "Chưa tạo được: " + (c.error || "lỗi không rõ");
    return "Chưa tạo";
  }

  function paintChapters() {
    const fltr = matchers[ts.filter] || matchers.all;
    const list = chs.filter(fltr);
    const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    if (ts.page >= pages) ts.page = pages - 1;
    const rows = list.slice(ts.page * PAGE_SIZE, (ts.page + 1) * PAGE_SIZE);
    const counts = Object.fromEntries(FILTERS.map(([k]) => [k, chs.filter(matchers[k]).length]));
    content.replaceChildren(
      h("div", { class: "row", style: "justify-content:space-between;margin-bottom:12px" },
        h("div", { class: "chips" }, ...FILTERS.filter(([k]) => k === "all" || counts[k] > 0 || k === ts.filter).map(([k, t]) =>
          h("button", { type: "button", class: "chip" + (ts.filter === k ? " on" : ""), "aria-pressed": String(ts.filter === k), onclick: () => { ts.filter = k; ts.page = 0; paintChapters(); } }, `${t} · ${fmtN(counts[k])}`))),
        menuButton("⋯ Tạo nhiều chương", [{ label: "Tạo một khoảng chương…", hint: "Ví dụ chương 20 đến 40", onclick: rangeDialog },
          { label: "Tạo 5 chương chưa xong tiếp theo", onclick: () => start({ limit: 5 }) }], { aria: "Tạo nhiều chương" })),
      list.length ? h("div", { class: "chlist" }, ...rows.map(chapterRow)) : h("div", { class: "empty" }, h("p", { class: "muted" }, ts.filter === "all" ? "Truyện chưa có chương nào." : "Không có chương nào ở nhóm này.")),
      h("div", { style: "margin-top:12px" }, Pager({ total: list.length, page: ts.page, onPage: (p) => { ts.page = p; paintChapters(); scrollPage(content.offsetTop - 80); } })),
      h("p", { class: "hint" }, `Mỗi chương có nút ▶ để nghe ngay trong lúc đang tạo các chương khác. Đang hiện ${fmtN(rows.length)} trong ${fmtN(list.length)} chương.`));
  }

  const busyPlay = new Set();
  async function listen(c, opts = {}) {
    if (busyPlay.has(c.n)) return;
    busyPlay.add(c.n); paintChapters();
    try {
      api(`/api/books/${encodeURIComponent(id)}/queue/focus`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ n: c.n }) }).catch(() => {});
      if (isDone(c) && c.status === "done" && !opts.trial) {
        await play({ src: `/api/books/${encodeURIComponent(id)}/chapters/${c.n}/audio.mp3`, title: c.title || `Chương ${c.n}`, sub: book.title });
      } else {
        const r = await trial(id, c.n, { chars: opts.chars || 300, offset: opts.offset || 0 }, () => {}, () => alive);
        await play({ src: r.url, title: c.title || `Chương ${c.n}`, sub: opts.offset ? "Nghe thử đoạn giữa chương" : "Nghe thử đầu chương" });
      }
    } catch (e) { if (alive) showError(e); }
    busyPlay.delete(c.n); if (alive) paintChapters();
  }

  async function viewText(c) {
    try {
      const d = await getJSON(`/api/books/${encodeURIComponent(id)}/chapters/${c.n}`);
      const m = modal([h("h3", {}, `${c.n}. ${c.title || ""}`), h("pre", { class: "chaptext" }, d.reading_text), h("div", { class: "row end" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))], { wide: true });
    } catch (e) { showError(e); }
  }

  function chapterRow(c) {
    const busy = busyPlay.has(c.n);
    const play1 = h("button", { type: "button", class: "play", disabled: busy, "aria-label": (c.status === "done" ? "Nghe chương " : "Nghe thử chương ") + c.n, title: c.status === "done" ? "Nghe chương này" : "Nghe thử đầu chương",
      onclick: () => listen(c) }, busy ? "…" : "▶");
    const items = [
      isDone(c) || c.status === "error" ? { label: "Tạo lại chương này", hint: "Xoá bản đã tạo và đọc lại", onclick: () => start({ chapters: [c.n], regenerate: true }) }
        : { label: c.status === "pending" ? "Tạo chương này" : "Đẩy lên trước", onclick: () => start({ chapters: [c.n] }) },
      { label: "Nghe thử 1 phút đầu chương", onclick: () => listen(c, { trial: true, chars: 900 }) },
      { label: "Nghe thử 1 phút từ giữa chương", hint: "Nơi hay có lời thoại và tên riêng", onclick: () => listen(c, { trial: true, chars: 900, offset: 0.5 }) },
      { label: "Xem chữ của chương", onclick: () => viewText(c) },
      c.status === "done" ? { label: "Tải chương này (MP3)", onclick: () => saveAs(`/api/books/${encodeURIComponent(id)}/chapters/${c.n}/audio.mp3`, `${c.n}.mp3`, { onDone: savedToast }).catch(showError) } : null,
    ];
    return h("div", { class: "chrow" }, h("div", { class: "name" }, h("b", {}, `${c.n}. `), c.title || "(không có tên)", h("div", { class: "sub" + (c.stale || c.status === "error" ? " warnc" : "") }, statusText(c))),
      c.status === "running" && c.segments && c.segments.total ? h("div", { style: "width:90px" }, h("div", { class: "bar" }, h("i", { style: `width:${Math.round((100 * c.segments.done) / c.segments.total)}%` }))) : null,
      play1, menuButton("⋯", items, { aria: `Thêm lựa chọn cho chương ${c.n}` }));
  }

  function rangeDialog() {
    const a = h("input", { type: "number", min: 1, max: chs.length, value: 1, "aria-label": "Từ chương" }), z = h("input", { type: "number", min: 1, max: chs.length, value: Math.min(chs.length, 20), "aria-label": "Đến chương" });
    const m = modal([h("h3", {}, "Tạo một khoảng chương"), h("div", { class: "row" }, "Từ chương", a, "đến chương", z),
      h("p", { class: "hint" }, "Chương đã xong sẽ được bỏ qua."),
      h("div", { class: "row end" }, h("button", { class: "btn", onclick: () => m.close() }, "Huỷ"), h("button", { class: "btn primary", onclick: () => {
        const x = Math.max(1, +a.value || 1), y = Math.min(chs.length, +z.value || x);
        if (y < x) return a.focus();
        m.close(); start({ chapters: Array.from({ length: y - x + 1 }, (_, i) => x + i) }); } }, "Tạo"))]);
  }

  // ───── làm mới theo nhịp ─────
  let topSig = "";
  async function refresh(force = false) {
    try {
      q = await queueOf(id);
      const s = JSON.stringify([q.counts, q.running && [q.running.n, q.running.seg_done], q.state, q.paused, q.queued_book]);
      const changed = force || s !== sig;
      if (changed) { sig = s; chs = await chaptersOf(id); }
      if (!alive) return;
      const t = JSON.stringify([s, q.estimate_seconds != null && Math.round(q.estimate_seconds / 60), q.note, q.trial && q.trial.done_at]);
      if (changed || t !== topSig) { topSig = t; paintTop(); }
      if (changed) paintTabs();
    } catch { /* thử lại lần sau */ }
  }
  const tick = async () => { await refresh(false); if (alive) timer = setTimeout(tick, q && (q.state === "running" || q.state === "pausing" || q.queued_book) ? 2000 : 6000); };

  (async () => { if (await load()) { paintTop(); paintTabs(); sig = JSON.stringify([q.counts, q.running && [q.running.n, q.running.seg_done], q.state, q.paused, q.queued_book]); timer = setTimeout(tick, 2000); } })();
  return () => { alive = false; clearTimeout(timer); if (tabCleanup) tabCleanup(); };
}
