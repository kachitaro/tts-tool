// Thêm truyện — trình hướng dẫn 3 bước: 1 Chọn file · 2 Kiểm tra · 3 Chọn giọng và nghe thử.
// Quay lại bước trước không mất dữ liệu: file đã nhận nằm trong truyện nháp trên server; các chỉnh sửa ở bước 2 và lựa chọn ở bước 3 giữ trong bộ nhớ.
import { h, debounce } from "../dom.js";
import { api, sendJSON } from "../api.js";
import { go } from "../router.js";
import { showError, toast, confirmBox, modal, switchEl } from "../ui.js";
import { engines, voices, prefs } from "../store.js";
import { VoicePicker, keyOf, displayName, metaLine, previewVoice } from "../voicepicker.js";
import { getSettings, effectiveDefault } from "../defaults.js";
import { play } from "../player.js";
import { askNotifyPermission } from "../overview.js";
import { getBook, patchBook, previewBook, confirmBook, deleteBook, runQueue, trial, trialFlag, queueOf } from "../bookapi.js";
import { inferTitlePattern } from "../titlepattern.js";
import { Pager, PAGE_SIZE } from "../pager.js";

const fmtN = (n) => Number(n).toLocaleString("vi-VN");
const fmtHours = (sec) => (sec >= 3600 ? `${(sec / 3600).toFixed(1).replace(".", ",")} giờ` : `${Math.max(1, Math.round(sec / 60))} phút`);
const SPEEDS = [["Chậm", -15], ["Vừa", 0], ["Nhanh", 20]];

// Cách gọi các quy tắc dọn văn bản bằng lời thường (khoá = tên quy tắc của server)
const RULE_TEXT = {
  unmask: "Khôi phục chữ bị che bằng dấu sao (ví dụ h*m thành ham)",
  join_numbers: "Ghép số bị tách rời (2. 513 thành 2.513)",
  blank_lines: "Bỏ dòng trống thừa, mỗi dòng là một đoạn văn",
  url_lines: "Bỏ dòng có đường link hoặc tên trang web",
  credit_lines: "Bỏ dòng ghi nguồn, tên người dịch",
  dup_lines: "Bỏ dòng lặp lại (quảng cáo đầu hoặc cuối trang)",
  separators: "Đổi dòng gạch ngăn cảnh (***, ---) thành một chỗ nghỉ",
  join_lines: "Nối những dòng bị ngắt giữa câu",
  quotes: "Thống nhất dấu ngoặc kép",
  ellipsis: "Thống nhất dấu ba chấm",
  control_chars: "Bỏ ký tự lạ vô hình, chuẩn hoá chữ có dấu",
};

function stepper(n, id) {
  const names = ["Chọn file", "Kiểm tra", "Chọn giọng"];
  const to = [() => "/sach/them", () => `/sach/${id}/kiem-tra`, () => `/sach/${id}/giong`];
  return h("ol", { class: "steps", "aria-label": "Các bước" }, ...names.map((t, i) => {
    const cls = "step" + (i + 1 === n ? " on" : i + 1 < n ? " done" : "");
    const inner = [h("span", { class: "n", "aria-hidden": "true" }, i + 1 < n ? "✓" : String(i + 1)), h("span", {}, t, i + 1 === n && h("span", { class: "sr" }, " (bước hiện tại)"))];
    return h("li", { class: cls, "aria-current": i + 1 === n ? "step" : undefined },
      i + 1 < n && id !== undefined ? h("a", { href: "#" + to[i](), class: "steplink" }, ...inner) : inner);
  }));
}
const crumb = (...tail) => h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("a", { href: "#/sach" }, "Làm sách nói"), ...tail.flatMap((t) => [" › ", h("span", {}, t)]));

// ═════════════════════════ Bước 1: chọn file ═════════════════════════
const W1 = { files: [], title: "", book: null };   // book: truyện nháp đã nhận file

export function mountWizardStart(root) {
  let alive = true;
  const body = h("div", { class: "stack" });
  const draw = () => {
    if (!alive) return;
    const input = h("input", { type: "file", multiple: true, accept: ".txt,.text,.epub,.html,.htm,.zip", class: "visually-hidden", id: "wFiles",
      onchange: (e) => addFiles([...e.target.files]) });
    const drop = h("label", { class: "drop", for: "wFiles", tabindex: 0,
      ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); }, ondragleave: () => drop.classList.remove("over"),
      ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles([...e.dataTransfer.files]); },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } } },
      h("div", { class: "big" }, W1.book || W1.files.length ? "Thêm hoặc đổi file" : "Kéo file vào đây, hoặc bấm để chọn"),
      h("div", { class: "muted" }, "Nhận file .txt, .epub, .html, hoặc một file .zip chứa nhiều file"), input);
    const chips = W1.book
      ? W1.book.sources.map((s) => chip(s.name, `${fmtN(s.bytes / 1024 | 0)} KB`))
      : W1.files.map((f, i) => chip(f.name, `${fmtN(Math.max(1, f.size / 1024 | 0))} KB`, () => { W1.files.splice(i, 1); draw(); }));
    const have = W1.book || W1.files.length;
    body.replaceChildren(
      h("p", { class: "hint", style: "margin-top:0" }, "💡 Tool sẽ tự chia truyện thành từng chương để bạn nghe và tạo từng phần."),
      drop,
      chips.length ? h("div", { class: "stack", style: "--gap:8px" }, W1.book && h("div", { class: "notice ok", style: "margin:0" }, `Đã nhận ${W1.book.sources.length} file ✓`), ...chips.slice(0, 8),
        chips.length > 8 && h("div", { class: "muted" }, `… và ${chips.length - 8} file nữa`)) : null,
      have ? h("div", { class: "stack" },
        h("div", {}, h("label", { class: "field", for: "wTitle" }, "Tên truyện"),
          h("input", { type: "text", id: "wTitle", value: W1.book ? W1.book.title : W1.title, disabled: !!W1.book, placeholder: "Để trống: tool lấy tên từ file", oninput: (e) => { W1.title = e.target.value; } }),
          h("div", { class: "hint" }, W1.book ? "Muốn đổi tên, sửa ở phần Cài đặt của truyện sau khi tạo xong." : "Có thể sửa sau.")),
        h("div", { class: "row end" }, W1.book && h("button", { class: "btn", onclick: resetDraft }, "Chọn file khác"),
          h("button", { class: "btn primary", id: "wNext", onclick: next }, "Tiếp tục →"))) : null);
  };
  const chip = (name, size, onremove) => h("div", { class: "filechip" }, h("span", { "aria-hidden": "true" }, "🗂️"), h("div", { style: "flex:1;min-width:0" }, h("b", { class: "ellip" }, name), h("div", { class: "muted" }, size)),
    onremove && h("button", { class: "btn small", "aria-label": "Bỏ file " + name, onclick: onremove }, "Bỏ"));
  async function addFiles(list) {
    if (!list.length) return;
    if (W1.book) await dropDraft();
    const seen = new Set(W1.files.map((f) => f.name + f.size));
    W1.files.push(...list.filter((f) => !seen.has(f.name + f.size)));
    draw();
  }
  async function dropDraft() { const id = W1.book && W1.book.id; W1.book = null; if (id) { try { await deleteBook(id); } catch { /* đã bị xoá */ } } }
  async function resetDraft() { await dropDraft(); W1.files = []; W1.title = ""; draw(); }
  async function next() {
    if (W1.book) return go(`/sach/${W1.book.id}/kiem-tra`);
    const btn = document.getElementById("wNext");
    btn.disabled = true; btn.textContent = "Đang đọc file…";
    try {
      const fd = new FormData();
      W1.files.forEach((f) => fd.append("files", f));
      fd.append("title", W1.title.trim());
      W1.book = await (await api("/api/books/import", { method: "POST", body: fd })).json();
      W1.files = [];
      go(`/sach/${W1.book.id}/kiem-tra`);
    } catch (e) { showError(e); if (btn) { btn.disabled = false; btn.textContent = "Tiếp tục →"; } }
  }
  root.append(crumb("Thêm truyện"), h("h2", {}, "Thêm truyện"), h("p", { class: "lead", style: "margin-bottom:12px" }, "Bước 1 — chọn file truyện của bạn."), stepper(1), body);
  draw();
  return () => { alive = false; };
}

// ═════════════════════════ Bước 2: kiểm tra ═════════════════════════
const FIX = new Map();   // id → trạng thái chỉnh sửa (giữ khi đi qua lại giữa các bước)

export function mountWizardCheck(root, { id }) {
  let alive = true, book = null, P = null, seq = 0, fixOpen = false, listOpen = false, listPage = 0, openRules = new Set(), undoRegex = null;
  const result = h("div", {}), fixEl = h("div", {}), advEl = h("div", {});
  root.append(crumb("Thêm truyện"), h("h2", {}, "Kiểm tra"), h("p", { class: "lead", style: "margin-bottom:12px" }, "Bước 2 — xem tool chia truyện có đúng ý bạn không."),
    stepper(2, id), h("div", { class: "card" }, h("p", { class: "muted" }, "Đang đọc truyện và chia chương…")));
  const card = root.lastElementChild;

  (async () => {
    try { book = await getBook(id); } catch (e) { root.replaceChildren(); return showError(e); }
    if (!alive) return;
    if (!FIX.has(id)) FIX.set(id, { regex: book.split.regex, mode: book.split.mode, ops: [...(book.split.ops || [])], selector: book.split.selector || "#chapter-c",
      clean: structuredClone(book.clean), exceptions: structuredClone(book.exceptions || []) });
    S = FIX.get(id);
    card.replaceChildren(result, h("div", { class: "row", style: "margin-top:16px" }, h("button", { class: "btn ghost", onclick: () => go("/sach/them") }, "← Quay lại")));
    card.append(fixEl, advEl);
    buildAdvanced();
    await refresh();
  })();
  let S = null;
  const body = () => ({ regex: S.regex, mode: S.mode, ops: S.ops, selector: S.selector, clean: S.clean, exceptions: S.exceptions });

  /** Chạy lại xem trước; trả true nếu thành công (sai thì hoàn tác thay đổi qua undo). */
  async function refresh(undo) {
    const mine = ++seq;
    try {
      const p = await previewBook(id, body());
      if (mine !== seq || !alive) return true;
      P = p; paint();
      return true;
    } catch (e) {
      if (mine !== seq || !alive) return false;
      if (undo) undo();
      showError(e);
      if (!P) result.replaceChildren(h("div", { class: "notice err" }, "Chưa chia được chương. ", e.message));
      return false;
    }
  }
  const refreshSoon = debounce(() => refresh(), 500);

  // ── cảnh báo bằng lời thường ──
  function warnings() {
    const out = [];
    for (const w of P.warnings || []) if (!/nội dung rất ngắn/.test(w)) out.push({ text: w });   // "rất ngắn" báo lại bên dưới, theo tên chương và có nút sửa
    const unknown = P.masked_unknown || [];
    if (unknown.length) out.push({ text: `Còn ${unknown.length} từ bị che bằng dấu sao mà tool chưa đoán được.`, action: ["Điền ngay", fillMasked], key: "masked" });
    const short = P.chapters.filter((c) => c.chars < 300), long = P.chapters.filter((c) => c.chars > Math.max(30000, medianChars() * 8));
    const nm = (c) => `“${(c.title || `chương ${c.n}`).slice(0, 50)}”`;
    if (short.length) out.push({ text: `${short.length === 1 ? `${nm(short[0])} rất ngắn` : `${short.length} chương rất ngắn (ví dụ ${short.slice(0, 2).map(nm).join(", ")})`} — có thể là trang quảng cáo hoặc chương bị cắt.`,
      action: ["Sửa", () => { fixOpen = true; listOpen = true; paint(); }] });
    if (long.length) out.push({ text: `${long.length === 1 ? `${nm(long[0])} rất dài` : `${long.length} chương rất dài`} — có thể hai chương bị dính làm một.`, action: ["Sửa", () => { fixOpen = true; listOpen = true; paint(); }] });
    if (P.dropped) out.push({ text: `Tool đã bỏ ${P.dropped} đoạn rỗng hoặc quá ngắn.` });
    return out;
  }
  const medianChars = () => { const a = P.chapters.map((c) => c.chars).sort((x, y) => x - y); return a.length ? a[a.length >> 1] : 0; };

  function fillMasked() {
    const rows = (P.masked_unknown || []).map((u) => {
      const inp = h("input", { type: "text", placeholder: "từ đúng là…", style: "max-width:180px", "aria-label": "Từ đúng của " + u.word });
      const save = h("button", { class: "btn small", onclick: async () => {
        if (!inp.value.trim()) return inp.focus();
        try { await sendJSON("/api/masked-words", { masked: u.word, correct: inp.value }); toast(`Đã nhớ “${inp.value.trim()}”. Tool sẽ tự khôi phục từ này ở các truyện sau.`); row.remove(); await refresh(); } catch (e) { showError(e); } } }, "Lưu");
      const row = h("div", { class: "exrow" }, h("div", {}, h("b", {}, u.word), h("span", { class: "muted" }, ` ${u.count} lần · chương ${u.chapter}`), h("div", { class: "hint" }, u.example)), h("div", { class: "row", style: "flex-wrap:nowrap" }, inp, save));
      return row;
    });
    const m = modal([h("h3", {}, "Điền từ bị che"), h("p", { class: "muted" }, "Mỗi dấu sao thay cho một chữ. Gõ từ đúng, tool sẽ nhớ và tự khôi phục lần sau."), ...rows,
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn primary", onclick: () => m.close() }, "Xong"))], { wide: true });
  }

  // ── vẽ kết quả ──
  function paint() {
    const ws = warnings(), n = P.chapters.length, est = P.chapters.reduce((a, c) => a + c.est_seconds, 0), total = P.chapters.reduce((a, c) => a + c.chars, 0);
    const clean = ws.length === 0 && n > 0;
    const head = h("div", {}, h("h3", { style: "font-size:26px" }, n ? (clean ? `Tìm thấy ${fmtN(n)} chương ✓` : `Tìm thấy ${fmtN(n)} chương`) : "Chưa tìm thấy chương nào"),
      n ? h("p", { class: "muted", style: "margin:4px 0 0" }, `Khoảng ${fmtN(total)} chữ, nghe hết khoảng ${fmtHours(est)}.`) : h("p", { class: "muted" }, "Hãy bấm “Có chỗ sai” để chỉ cho tool thấy tiêu đề chương viết thế nào."));
    const warnEls = ws.map((w) => h("div", { class: "notice warn" }, "⚠ ", w.text, " ", w.action && h("button", { class: "btn small", style: "margin-left:8px", onclick: w.action[1] }, w.action[0])));
    const listBtn = n ? h("details", { class: "adv", style: "border:0;margin:10px 0 0;padding:0", open: listOpen, ontoggle: (e) => { listOpen = e.target.open; } },
      h("summary", {}, listOpen ? "Thu gọn danh sách chương" : "Xem danh sách chương"), h("div", { class: "adv-body" }, chapterList())) : null;
    result.replaceChildren(...[head, ...warnEls, listBtn,
      h("div", { class: "row", style: "margin-top:16px" },
        h("button", { class: "btn primary", disabled: !n, id: "cont", onclick: proceed }, clean ? "Tiếp tục" : "Đúng rồi, tiếp tục"),
        h("button", { class: clean ? "btn ghost" : "btn", "aria-expanded": String(fixOpen), onclick: () => { fixOpen = !fixOpen; paint(); } }, clean ? "Có chỗ sai?" : "Có chỗ sai"))].filter(Boolean));
    paintFix();
  }

  function chapterList() {
    const rows = P.chapters.slice(listPage * PAGE_SIZE, (listPage + 1) * PAGE_SIZE);
    const tools = (c, k) => fixOpen ? h("span", { class: "row", style: "flex-wrap:nowrap" },
      k + 1 < P.chapters.length && h("button", { class: "btn small", onclick: () => merge(k) }, "Gộp với chương sau"),
      h("button", { class: "btn small", onclick: () => split(c) }, "Tách…")) : null;
    return h("div", {}, h("div", { class: "chlist" }, ...rows.map((c, i) => {
      const k = listPage * PAGE_SIZE + i;
      return h("div", { class: "chrow" }, h("div", { class: "name" }, h("b", {}, `${c.n}. `), c.title || "(không có tên)", h("div", { class: "sub" }, `${fmtN(c.chars)} chữ`)), tools(c, k));
    })), h("div", { style: "margin-top:10px" }, Pager({ total: P.chapters.length, page: listPage, onPage: (p) => { listPage = p; paint(); } })));
  }

  async function applyOps(ops) {
    const before = S.ops.length;
    S.ops.push(...ops);
    await refresh(() => { S.ops.length = before; });
  }
  const merge = (k) => { const a = P.chapters[k].raw, b = P.chapters[k + 1].raw; return applyOps(Array.from({ length: b - a }, () => ({ op: "merge", i: a }))); };
  function split(c) {
    const needle = h("input", { type: "text", placeholder: "Ví dụ: Sáng hôm sau", "aria-label": "Câu mở đầu phần mới" });
    const title = h("input", { type: "text", placeholder: "Để trống nếu không cần", "aria-label": "Tên phần mới" });
    const m = modal([h("h3", {}, `Tách chương ${c.n}`), h("div", { class: "stack", style: "--gap:12px" },
      h("div", {}, h("label", { class: "field" }, "Phần mới bắt đầu từ dòng có chữ…"), needle, h("div", { class: "hint" }, "Gõ vài chữ đầu của dòng đầu tiên thuộc chương mới.")),
      h("div", {}, h("label", { class: "field" }, "Tên phần mới"), title),
      h("div", { class: "row end" }, h("button", { class: "btn", onclick: () => m.close() }, "Huỷ"),
        h("button", { class: "btn primary", onclick: () => { if (!needle.value.trim()) return needle.focus(); m.close(); applyOps([{ op: "split", i: c.raw, contains: needle.value, title: title.value }]); } }, "Tách")))]);
  }

  // ── công cụ sửa ──
  function paintFix() {
    if (!fixOpen) return fixEl.replaceChildren();
    const perFile = S.mode === "per_file";
    // 1) Mẫu tiêu đề
    const ex = h("input", { type: "text", id: "tpEx", placeholder: "Ví dụ: Chương 5: Gặp gỡ", "aria-label": "Một dòng tiêu đề chương mẫu", style: "flex:1" });
    const tryBtn = h("button", { class: "btn", onclick: async () => {
      const pat = inferTitlePattern(ex.value);
      if (!pat) return ex.focus();
      undoRegex = { regex: S.regex, mode: S.mode }; S.regex = pat; S.mode = "regex";
      const ok = await refresh(() => { S.regex = undoRegex.regex; S.mode = undoRegex.mode; });
      if (ok) toast(`Với dòng mẫu này tool tìm thấy ${fmtN(P.chapters.length)} chương.`);
    } }, "Thử mẫu này");
    const undoBar = () => undoRegex && h("div", { class: "hint" }, "Vừa đổi cách chia chương. ", h("button", { class: "btn small ghost", onclick: async () => { const u = undoRegex; undoRegex = null; S.regex = u.regex; S.mode = u.mode; await refresh(); paintFix(); } }, "Quay lại như cũ"));
    const sec1 = h("section", {}, h("b", {}, "Tiêu đề chương trong truyện viết thế nào?"),
      perFile ? h("div", {}, h("p", { class: "muted", style: "margin:4px 0 8px" }, "Mỗi file của bạn đang là một chương nên không cần mẫu tiêu đề."),
        h("button", { class: "btn small", onclick: async () => { undoRegex = { regex: S.regex, mode: S.mode }; S.mode = "regex"; await refresh(() => { S.mode = undoRegex.mode; undoRegex = null; }); paintFix(); } }, "Mỗi file có nhiều chương? Chia theo tiêu đề trong văn bản"), undoBar())
      : h("div", {}, h("p", { class: "muted", style: "margin:4px 0 8px" }, "Dán một dòng tiêu đề chương giống trong truyện, tool sẽ tự tìm các dòng giống vậy."),
        h("div", { class: "row", style: "flex-wrap:nowrap" }, ex, tryBtn),
        h("div", { class: "chips", style: "margin-top:8px" }, ...["Chương 5: Gặp gỡ", "Hồi 5. Gặp gỡ", "Chapter 5", "第5章 开始", "5. Gặp gỡ"].map((t) => h("button", { type: "button", class: "chip", onclick: () => { ex.value = t; ex.focus(); } }, t))),
        undoBar()));
    // 2) Gộp / tách
    const sec2 = h("section", {}, h("b", {}, "Gộp hoặc tách chương"),
      h("p", { class: "muted", style: "margin:4px 0 8px" }, "Mở danh sách chương ở trên: mỗi chương có nút “Gộp với chương sau” và “Tách…”."),
      h("div", { class: "row" }, h("button", { class: "btn small", onclick: () => { listOpen = true; paint(); } }, "Mở danh sách chương"),
        S.ops.length > 0 && h("button", { class: "btn small", onclick: async () => { const old = S.ops; S.ops = []; await refresh(() => { S.ops = old; }); } }, `Bỏ ${S.ops.length} lần gộp / tách`)));
    // 3) Dọn văn bản
    const catalog = book.rules_catalog;
    const sec3 = h("section", {}, h("b", {}, "Dọn văn bản"), h("p", { class: "muted", style: "margin:4px 0 8px" }, "Tool tự dọn các thứ dưới đây. Bỏ chọn nếu bạn không muốn; bấm “Xem những dòng bị đổi” để kiểm tra."),
      ...catalog.filter((r) => ruleActive(r)).map((r) => ruleRow(r)),
      catalog.some((r) => !ruleActive(r)) ? h("details", { class: "adv", style: "margin-top:10px", open: S.showAllRules, ontoggle: (e) => { S.showAllRules = e.target.open; } },
        h("summary", {}, "Các quy tắc khác (hiện chưa có chỗ nào cần dọn)"), h("div", { class: "adv-body" }, ...catalog.filter((r) => !ruleActive(r)).map((r) => ruleRow(r)))) : null,
      S.exceptions.length ? h("div", { style: "margin-top:10px" }, h("div", { class: "muted" }, "Những dòng bạn đã giữ nguyên:"), ...S.exceptions.map((e, i) =>
        h("div", { class: "excl" }, h("span", { class: "ellip" }, `${RULE_TEXT[e.rule] || e.rule}: ${e.line}`),
          h("button", { class: "btn small", "aria-label": "Bỏ giữ nguyên dòng này", onclick: async () => { const old = [...S.exceptions]; S.exceptions.splice(i, 1); await refresh(() => { S.exceptions = old; }); } }, "✕")))) : null);
    fixEl.replaceChildren(h("div", { class: "fixpanel" }, h("h3", {}, "Chỗ nào chưa đúng? Chọn cách sửa"), sec1, sec2, sec3));
  }

  const ruleActive = (r) => (P.rules[r.name] && P.rules[r.name].count > 0) || S.clean.rules[r.name] === false;
  function ruleRow(r) {
    const info = P.rules[r.name], count = info ? info.count : 0, on = S.clean.rules[r.name] !== false, open = openRules.has(r.name);
    const sw = h("input", { type: "checkbox", checked: on, "aria-label": RULE_TEXT[r.name] || r.label, onchange: async () => {
      const old = S.clean.rules[r.name]; S.clean.rules[r.name] = sw.checked; await refresh(() => { S.clean.rules[r.name] = old; paintFix(); }); } });
    const examples = open && info ? h("div", { class: "exlist" }, ...info.examples.map((ex) => exRow(r.name, ex)),
      info.count > info.examples.length && h("div", { class: "hint" }, `… và ${fmtN(info.count - info.examples.length)} chỗ nữa không hiện`)) : null;
    return h("div", { class: "rulerow" }, h("label", { class: "check" }, sw, h("span", {}, RULE_TEXT[r.name] || r.label,
      h("span", { class: "muted" }, count ? ` · ảnh hưởng ${fmtN(count)} chỗ` : on ? " · không có chỗ nào" : "")),),
      count ? h("button", { class: "btn small ghost", "aria-expanded": String(open), onclick: () => { open ? openRules.delete(r.name) : openRules.add(r.name); paintFix(); } }, open ? "Ẩn" : "Xem những dòng bị đổi") : null, examples);
  }

  function exRow(name, ex) {
    const before = Array.isArray(ex.before) ? ex.before : [ex.before];
    const keep = ex.key ? h("button", { class: "btn small", onclick: async () => { const old = [...S.exceptions]; S.exceptions.push({ rule: name, line: ex.key }); await refresh(() => { S.exceptions = old; }); } }, "Giữ nguyên dòng này") : null;
    return h("div", { class: "exrow" }, h("div", {}, h("div", { class: "hint", style: "margin:0" }, `Chương ${ex.chapter}${ex.title ? " · " + ex.title : ""}`),
      ...before.map((t) => h("div", { class: "exl old" }, (ex.after ? "Trước: " : "Bị xoá: ") + t)), ex.after && h("div", { class: "exl new" }, "Sau: " + ex.after)), keep);
  }

  // ── Nâng cao (dựng một lần; ô nhập không bị vẽ lại) ──
  function buildAdvanced() {
    const regex = h("input", { type: "text", value: S.regex, spellcheck: false, "aria-label": "Mẫu tiêu đề chương (regex)", oninput: (e) => { S.regex = e.target.value; refreshSoon(); } });
    const mode = h("select", { "aria-label": "Cách chia chương", onchange: (e) => { S.mode = e.target.value; refresh(); paintFix(); } },
      h("option", { value: "regex" }, "Chia theo tiêu đề trong văn bản"), h("option", { value: "per_file" }, "Mỗi file một chương"));
    mode.value = S.mode;
    const isHtml = book.sources.some((s) => s.kind === "html");
    const sel = isHtml && h("div", {}, h("label", { class: "field" }, "Khung chương trong trang web (selector)"), h("input", { type: "text", value: S.selector, placeholder: "#chapter-c", spellcheck: false, oninput: (e) => { S.selector = e.target.value; refreshSoon(); } }),
      h("div", { class: "hint" }, "Dạng #id, .class, tag hoặc tag#id.class. Tool lấy nội dung từ khung này đến hết trang."));
    const pause = h("input", { type: "number", min: 0.1, max: 5, step: 0.1, value: S.clean.separator_pause, style: "max-width:120px", oninput: (e) => { S.clean.separator_pause = +e.target.value; refreshSoon(); } });
    const custom = h("div", {});
    const drawCustom = () => custom.replaceChildren(...S.clean.custom.map((r, i) => h("div", { class: "crule" },
      h("input", { type: "text", value: r.pattern, placeholder: "Tìm (regex)", "aria-label": "Mẫu cần tìm", oninput: (e) => { r.pattern = e.target.value; refreshSoon(); } }),
      h("input", { type: "text", value: r.replace, placeholder: "Thay bằng", "aria-label": "Thay bằng", oninput: (e) => { r.replace = e.target.value; refreshSoon(); } }),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: r.enabled, onchange: (e) => { r.enabled = e.target.checked; refresh(); } }), "Bật"),
      h("button", { class: "btn small", "aria-label": "Xoá quy tắc", onclick: () => { S.clean.custom.splice(i, 1); drawCustom(); refresh(); } }, "✕"))));
    drawCustom();
    advEl.replaceChildren(h("details", { class: "adv" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body stack" },
      h("div", {}, h("label", { class: "field" }, "Cách chia chương"), mode),
      h("div", {}, h("label", { class: "field" }, "Mẫu tiêu đề chương (regex, khớp từ đầu dòng, không phân biệt hoa thường)"), regex,
        h("div", { class: "row", style: "margin-top:6px" }, h("button", { class: "btn small", onclick: () => { regex.value = book.default_regex; S.regex = book.default_regex; refresh(); } }, "Về mẫu mặc định"))),
      sel,
      h("div", {}, h("label", { class: "field" }, "Chỗ nghỉ ở dấu ngăn cảnh (giây)"), pause),
      h("div", {}, h("label", { class: "field" }, "Quy tắc dọn riêng (tìm → thay bằng)"), custom,
        h("button", { class: "btn small", onclick: () => { S.clean.custom.push({ pattern: "", replace: "", enabled: true }); drawCustom(); } }, "＋ Thêm quy tắc")))));
  }

  async function proceed() {
    const b = document.getElementById("cont");
    b.disabled = true; b.textContent = "Đang chia chương…";
    try { await confirmBook(id, body()); go(`/sach/${id}/giong`); }
    catch (e) { showError(e); b.disabled = false; b.textContent = "Tiếp tục"; }
  }
  return () => { alive = false; };
}

// ═════════════════════════ Bước 3: chọn giọng và nghe thử ═════════════════════════
const V3 = new Map();

export function mountWizardVoice(root, { id }) {
  let alive = true, book = null, E = {}, V = [], ST = null, st = null, q = null;
  const area = h("div", {});
  root.append(crumb("Thêm truyện"), h("h2", {}, "Chọn giọng và nghe thử"), h("p", { class: "lead", style: "margin-bottom:12px" }, "Bước 3 — chọn người sẽ đọc truyện cho bạn."), stepper(3, id), area);
  area.append(h("p", { class: "muted" }, "Đang tải…"));
  (async () => {
    try { [book, E, V, ST, q] = await Promise.all([getBook(id), engines(), voices(), getSettings(), queueOf(id)]); } catch (e) { area.replaceChildren(); return showError(e); }
    if (!alive) return;
    if (book.status !== "ready") return go(`/sach/${id}/kiem-tra`);
    if (!V3.has(id)) {
      const cur = V.find((v) => v.engine === book.voice.engine && v.id === book.voice.voice);
      const def = effectiveDefault(V, E, ST).voice;
      V3.set(id, { voice: cur && book.voice.voice !== "Hải Đăng" ? keyOf(cur) : def ? keyOf(def) : cur ? keyOf(cur) : "", speed: book.speed || 0, dlg: false, dlgVoice: "",
        trial5: book.chapters.count > 20, pp: book.paragraph_pause_s ?? 0.6, tp: book.title_pause_s ?? 1.2, readTitle: book.read_title !== false });
    }
    st = V3.get(id);
    draw();
  })();
  const voiceOf = (k) => V.find((v) => keyOf(v) === k);
  const tr = { running: false, done: 0, total: 1, text: "" };

  async function saveSettings() {
    const v = voiceOf(st.voice);
    const body = { voice: { engine: v.engine, voice: v.id }, speed: st.speed, read_title: st.readTitle, paragraph_pause_s: +st.pp, title_pause_s: +st.tp };
    const d = voiceOf(st.dlgVoice) || v;
    body.dialogue_voice = { enabled: st.dlg, engine: d.engine, voice: d.id };
    await patchBook(id, body);
  }

  function draw() {
    if (!alive) return;
    const v = voiceOf(st.voice), n = book.chapters.count;
    const est = q.estimate_seconds, rate = q.rate_cps;
    const trialBox = h("div", { class: "card flat", style: "margin-top:18px" }, h("h3", { style: "font-size:20px;margin-bottom:6px" }, "Nghe thử 1 phút đầu chương 1"),
      h("p", { class: "muted" }, "Nghe trước xem giọng này đọc truyện của bạn có ưng không. Chưa tạo gì cả."),
      h("button", { class: "btn", disabled: !v || tr.running, onclick: runTrial }, tr.running ? "Đang chuẩn bị…" : `▶ Nghe thử bằng giọng ${v ? displayName(v) : ""}`),
      tr.text && h("div", { class: "bar", style: "margin-top:12px" }, h("i", { style: `width:${Math.round((tr.done / tr.total) * 100)}%` })),
      tr.text && h("div", { class: "hint" }, tr.text));
    const dlgBox = h("div", { class: "card flat", style: "margin-top:16px" }, switchEl("Lời thoại đọc bằng giọng khác", st.dlg, (on) => { st.dlg = on; if (on && !st.dlgVoice) st.dlgVoice = st.voice; draw(); }),
      h("p", { class: "hint" }, "Lời nhân vật (trong dấu ngoặc kép hoặc sau gạch đầu dòng) do một người khác đọc, phần dẫn vẫn do người kể đọc."),
      st.dlg && (() => { const d = voiceOf(st.dlgVoice); return h("div", { class: "vcurrent" }, h("div", { class: "vinfo" }, h("b", {}, d ? displayName(d) : "Chưa chọn"), d && h("div", { class: "muted" }, metaLine(d, E))),
        d && h("button", { class: "play", "aria-label": "Nghe thử giọng lời thoại", onclick: () => previewVoice(d) }, "▶"), h("button", { class: "btn small", onclick: () => pick("dlgVoice") }, "Đổi giọng")); })());
    const picker = VoicePicker({ voices: V, engines: E, value: st.voice, only: (x) => x.usable !== false, onPick: (x) => { st.voice = keyOf(x); tr.text = ""; draw(); } });
    area.replaceChildren(
      h("div", { class: "card flat" }, h("h3", { style: "font-size:20px;margin-bottom:10px" }, "Giọng kể"), picker),
      trialBox, dlgBox,
      h("div", { class: "card flat", style: "margin-top:16px" }, h("label", { class: "field" }, "Đọc nhanh hay chậm?"),
        h("div", { class: "seg", role: "group", "aria-label": "Tốc độ đọc" }, ...SPEEDS.map(([t, p]) => h("button", { type: "button", class: st.speed === p ? "on" : "", onclick: () => { st.speed = p; draw(); } }, t)))),
      h("div", { class: "stickyfoot" },
        h("button", { class: "btn primary", disabled: !v, id: "start", onclick: start }, "Bắt đầu tạo sách nói"),
        n > 5 && h("label", { class: "check" }, h("input", { type: "checkbox", checked: st.trial5, onchange: (e) => { st.trial5 = e.target.checked; } }),
          h("span", {}, h("b", {}, "Tạo thử 5 chương trước"), n > 20 ? " (nên chọn)" : "", h("br"), h("span", { class: "muted" }, st.trial5 ? "Tool tạo 5 chương rồi dừng lại, để bạn nghe thử. Ưng rồi mới bấm Tạo tiếp." : "Tool tạo liền cả truyện."))),
        est != null && h("span", { class: "muted" }, `Ước tính cả truyện: khoảng ${fmtHours(est)} (${rate} chữ mỗi giây).`)),
      h("details", { class: "adv" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body two" },
        h("div", {}, h("label", { class: "field" }, "Nghỉ giữa các đoạn văn (giây)"), h("input", { type: "number", min: 0, max: 3, step: 0.1, value: st.pp, oninput: (e) => { st.pp = e.target.value; } })),
        h("div", {}, h("label", { class: "field" }, "Nghỉ sau tên chương (giây)"), h("input", { type: "number", min: 0, max: 5, step: 0.1, value: st.tp, oninput: (e) => { st.tp = e.target.value; } })),
        switchEl("Đọc tên chương ở đầu mỗi chương", st.readTitle, (on) => { st.readTitle = on; }))),
      h("div", { class: "row", style: "margin-top:16px" }, h("button", { class: "btn ghost", onclick: () => go(`/sach/${id}/kiem-tra`) }, "← Quay lại")));
  }

  function pick(key) {
    const m = modal([h("h3", {}, "Chọn giọng"), VoicePicker({ voices: V, engines: E, value: st[key], only: (x) => x.usable !== false, onPick: (x) => { st[key] = keyOf(x); m.close(); draw(); } }),
      h("div", { class: "row end", style: "margin-top:14px" }, h("button", { class: "btn", onclick: () => m.close() }, "Đóng"))], { wide: true });
  }

  async function runTrial() {
    tr.running = true; tr.done = 0; tr.total = 1; tr.text = "Đang chuẩn bị bản nghe thử… khoảng nửa phút."; draw();
    try {
      await saveSettings();
      const r = await trial(id, 1, { chars: 900, offset: 0 }, (d, t, s) => { tr.done = d; tr.total = Math.max(1, t); tr.text = s === "queued" ? "Đang chờ tới lượt…" : `Đang đọc… ${d}/${t}`; if (alive) draw(); }, () => alive);
      tr.text = `Xong! Bản nghe thử dài ${Math.round(r.seconds)} giây, bạn đang nghe ở thanh phát bên dưới.`; tr.done = tr.total;
      play({ src: r.url, title: `${book.title} — nghe thử`, sub: `Chương 1 · giọng ${displayName(voiceOf(st.voice))}` });
    } catch (e) { tr.text = ""; if (alive) showError(e); }
    tr.running = false; if (alive) draw();
  }

  async function start() {
    const b = document.getElementById("start");
    b.disabled = true; b.textContent = "Đang bắt đầu…";
    try {
      await saveSettings();
      const five = st.trial5 && book.chapters.count > 5;
      askNotifyPermission();
      await runQueue(id, five ? { limit: 5 } : {});
      if (five) trialFlag.set(id); else trialFlag.clear(id);
      prefs.set("voice-last", st.voice);
      toast(five ? "Bắt đầu tạo 5 chương đầu. Xong tool sẽ dừng để bạn nghe thử." : "Bắt đầu tạo sách nói. Bạn có thể đóng trang này, tool vẫn chạy.");
      go(`/sach/${id}`);
    } catch (e) { showError(e); b.disabled = false; b.textContent = "Bắt đầu tạo sách nói"; }
  }
  return () => { alive = false; };
}
