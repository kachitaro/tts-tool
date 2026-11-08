// "Thêm giọng từ file ghi âm": hộp thoại 2 bước. Bước 1: chọn file hoặc ghi âm. Bước 2: đặt tên + xác nhận quyền dùng giọng.
import { h } from "../dom.js";
import { api } from "../api.js";
import { explain } from "../errors.js";
import { modal } from "../ui.js";
import { audioDuration, judgeDuration, recordMic } from "../recorder.js";
import { resetVoices } from "../store.js";
import { filesFromDrop } from "../dropfiles.js";
import { canRecord } from "../appenv.js";

const GENDERS = [["", "Không rõ"], ["nam", "Nam"], ["nữ", "Nữ"]];
const REGIONS = [["", "Không rõ"], ["bac", "Bắc"], ["trung", "Trung"], ["nam", "Nam"]];

/** Nhóm nút chọn một trong vài giá trị (dùng cho giới tính, vùng miền). */
export function choiceSeg(label, options, get, set) {
  const box = h("div", { class: "seg", role: "group", "aria-label": label });
  const paint = () => box.replaceChildren(...options.map(([v, t]) => h("button", { type: "button", class: get() === v ? "on" : "", "aria-pressed": String(get() === v), onclick: () => { set(v); paint(); } }, t)));
  paint();
  return h("div", {}, h("label", { class: "field" }, label), box);
}
export { GENDERS, REGIONS };

export function openAddVoice({ engines, onSaved }) {
  const clonable = Object.entries(engines).map(([id, e]) => ({ ...e, id })).filter((e) => e.available && e.capabilities && e.capabilities.clone);   // /api/engines là bảng theo id
  const S = { file: null, url: "", info: null, name: "", gender: "", region: "", tags: "", description: "", consent: false, engine: clonable[0] && clonable[0].id, rec: null, recSec: 0, busy: false, err: "" };
  const box = h("div", {});
  const m = modal(box, { wide: true, onclose: () => { if (S.rec) S.rec.stop(); if (S.url) URL.revokeObjectURL(S.url); } });

  async function setSample(file) {
    if (S.url) URL.revokeObjectURL(S.url);
    S.file = file; S.url = URL.createObjectURL(file); S.info = null; S.err = "";
    draw();
    const d = await audioDuration(file);
    if (S.file !== file) return;
    S.info = judgeDuration(d);
    if (!S.name) S.name = file.name.replace(/\.[^.]+$/, "").replace(/^ghi-am$/, "").slice(0, 60);
    draw();
  }

  async function toggleRec() {
    if (S.rec) { S.rec.stop(); return; }
    S.err = "";
    try {
      const r = await recordMic((s) => { S.recSec = s; const el = box.querySelector("#recTime"); if (el) el.textContent = `Đang ghi… ${Math.floor(s)} giây`; });
      S.rec = r; draw();
      const f = await r.done;
      S.rec = null;
      if (f) await setSample(f); else { S.err = "Không thu được âm thanh. Kiểm tra micro rồi thử lại, hoặc chọn file ghi âm có sẵn."; draw(); }
    } catch (e) { S.rec = null; S.err = e.message; draw(); }
  }

  const header = (step) => [
    h("h3", {}, "Thêm giọng từ file ghi âm"),
    h("p", { class: "hint", style: "margin:0 0 14px" }, `Bước ${step} trên 2 — ${step === 1 ? "chọn file hoặc ghi âm" : "đặt tên và xác nhận"}`),
  ];

  function step1() {
    const input = h("input", { type: "file", accept: "audio/*", class: "sr", onchange: (e) => e.target.files[0] && setSample(e.target.files[0]) });
    const drop = h("label", { class: "drop small" + (S.file ? " has" : ""), tabindex: 0,
      ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); }, ondragleave: () => drop.classList.remove("over"),
      ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); filesFromDrop(e).then(([f]) => f && setSample(f)); },
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } } },
      input, h("div", { class: "big" }, S.file ? "🎙️ " + S.file.name : "Kéo file vào đây hoặc bấm để chọn"), h("div", { class: "muted" }, "File wav, mp3, m4a…"));
    const lvl = S.info && S.info.level;
    return [...header(1),
      h("div", { class: "notice" }, h("b", {}, "Mẫu tốt: "), "3–10 giây, một người nói, không nhạc nền, không tiếng ồn."),
      clonable.length ? null : h("div", { class: "notice err" }, "Máy này chưa có giọng nào cho phép tạo giọng từ ghi âm."),
      h("div", { class: "stack", style: "margin-top:14px" }, drop,
        canRecord()
          ? h("div", { class: "row" }, h("span", { class: "muted" }, "hoặc"),
            h("button", { type: "button", class: "btn" + (S.rec ? " danger" : ""), disabled: !clonable.length, onclick: toggleRec }, S.rec ? "■ Dừng ghi âm" : "● Ghi âm bằng micro"),
            h("span", { id: "recTime", class: "muted", "aria-live": "polite" }, S.rec ? "Đang ghi…" : ""))
          : h("div", { class: "row" }, h("button", { type: "button", class: "btn", disabled: !clonable.length, onclick: () => input.click() }, "Chọn file ghi âm"),
            h("span", { class: "muted" }, "Cửa sổ này chưa ghi âm trực tiếp được. Hãy ghi bằng ứng dụng khác rồi chọn file.")),
        S.err && h("div", { class: "notice err" }, S.err),
        S.file && h("div", { class: "card flat" }, h("div", { class: "row" }, h("b", {}, "Nghe lại mẫu"), h("button", { type: "button", class: "btn small ghost", onclick: () => { S.file = null; S.info = null; draw(); } }, "Chọn lại")),
          h("audio", { controls: true, src: S.url, style: "width:100%;margin-top:8px" }),
          h("div", { class: "notice " + (lvl === "bad" ? "err" : lvl === "warn" ? "warn" : lvl === "ok" ? "ok" : ""), style: "margin:10px 0 0" }, S.info ? S.info.text : "Đang xem thời lượng…")),
      ),
      h("div", { class: "row end", style: "margin-top:18px" },
        h("button", { type: "button", class: "btn", onclick: () => m.close() }, "Huỷ"),
        h("button", { type: "button", class: "btn primary", id: "addNext", disabled: !S.file || !S.info || S.info.level === "bad" || S.rec, onclick: () => { S.step = 2; draw(); } }, "Tiếp tục")),
    ];
  }

  async function save() {
    S.err = "";
    if (!S.name.trim()) { S.err = "Hãy đặt tên cho giọng."; return draw(); }
    if (!S.consent) { S.err = "Hãy tick xác nhận bạn là chủ giọng nói hoặc đã được người đó đồng ý."; return draw(); }
    S.busy = true; draw();
    const fd = new FormData();
    fd.append("name", S.name.trim()); fd.append("gender", S.gender); fd.append("region", S.region);
    fd.append("tags", S.tags); fd.append("description", S.description.trim());
    fd.append("engine", S.engine); fd.append("consent", "true"); fd.append("ref_audio", S.file);
    try {
      const meta = await (await api("/api/library", { method: "POST", body: fd })).json();
      resetVoices();
      m.close();
      onSaved(meta);
    } catch (e) { const x = explain(e); S.err = x.title + (x.tip ? " " + x.tip : ""); S.busy = false; draw(); }
  }

  function step2() {
    return [...header(2),
      h("div", { class: "stack" },
        h("div", {}, h("label", { class: "field", for: "vName" }, "Tên giọng"),
          h("input", { id: "vName", type: "text", maxlength: 60, value: S.name, placeholder: "Ví dụ: Giọng của mẹ", oninput: (e) => { S.name = e.target.value; } })),
        h("div", { class: "two" }, choiceSeg("Giọng nam hay nữ?", GENDERS, () => S.gender, (v) => { S.gender = v; }), choiceSeg("Giọng vùng nào?", REGIONS, () => S.region, (v) => { S.region = v; })),
        h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.consent, onchange: (e) => { S.consent = e.target.checked; if (S.consent && S.err.startsWith("Hãy tick")) { S.err = ""; box.querySelector("[role=alert]")?.remove(); } } }),
          h("span", {}, h("b", {}, "Tôi là chủ giọng nói này hoặc đã được người đó đồng ý."), h("br"), h("span", { class: "muted" }, "Đừng nhân bản giọng người khác khi chưa được phép."))),
        h("details", { class: "adv", style: "margin:0" }, h("summary", {}, "Nâng cao"), h("div", { class: "adv-body stack", style: "--gap:10px" },
          clonable.length > 1 && h("div", {}, h("label", { class: "field" }, "Loại giọng"),
            h("select", { onchange: (e) => { S.engine = e.target.value; } }, ...clonable.map((e) => h("option", { value: e.id, selected: e.id === S.engine }, e.name || e.label || e.id)))),
          h("div", {}, h("label", { class: "field" }, "Thẻ (cách nhau bằng dấu phẩy)"), h("input", { type: "text", value: S.tags, placeholder: "ví dụ: kể chuyện, ấm áp", oninput: (e) => { S.tags = e.target.value; } })),
          h("div", {}, h("label", { class: "field" }, "Ghi chú"), h("input", { type: "text", maxlength: 300, value: S.description, oninput: (e) => { S.description = e.target.value; } })))),
        S.err && h("div", { class: "notice err", role: "alert" }, S.err),
        S.busy && h("div", { class: "notice" }, "Đang xử lý mẫu giọng… lần đầu có thể mất vài phút vì tool phải tải model.")),
      h("div", { class: "row end", style: "margin-top:18px" },
        h("button", { type: "button", class: "btn", disabled: S.busy, onclick: () => { S.step = 1; S.err = ""; draw(); } }, "← Quay lại"),
        h("button", { type: "button", class: "btn primary", id: "addSave", disabled: S.busy, onclick: save }, S.busy ? "Đang lưu…" : "Lưu giọng này")),
    ];
  }

  function draw() {
    const focusId = document.activeElement && document.activeElement.id;
    box.replaceChildren(...(S.step === 2 ? step2() : step1()));
    if (focusId && focusId !== "recTime") { const el = box.querySelector("#" + focusId); if (el && !el.disabled) el.focus(); }
  }
  S.step = 1; draw();
}
