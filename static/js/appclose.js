// Đóng cửa sổ app khi đang tạo sách nói: app.py chặn việc đóng rồi gọi window.gvAppClose() (chỉ có trong app cửa sổ riêng).
import { h } from "./dom.js";
import { getJSON } from "./api.js";
import { modal, showError } from "./ui.js";
import { appApi, inApp } from "./appenv.js";

export function installAppClose() {
  if (!inApp()) return;
  window.gvAppClose = async () => {
    const api = await appApi();
    if (!api) return;
    let cur = null, info = {};
    try { cur = (await getJSON("/api/overview")).current; info = await api.info(); } catch { /* không có thông tin: vẫn hỏi, câu chữ chung chung */ }
    const where = cur ? `Đang tạo “${cur.title}”, ${cur.chapter ? `chương ${cur.chapter}/${cur.chapters}` : `${cur.done}/${cur.chapters} chương`}.` : "Đang tạo sách nói.";
    const choose = async (choice) => { m.close(); try { await api.close_choice(choice); } catch (e) { showError(e); } };
    const m = modal([
      h("h3", {}, "Đang tạo sách nói"),
      h("p", {}, where),
      h("p", { class: "muted" }, info.tray
        ? "“Chạy nền tiếp” đóng cửa sổ nhưng tool vẫn tạo; bấm biểu tượng ở khay hệ thống để mở lại hoặc thoát."
        : "“Chạy nền tiếp” thu nhỏ cửa sổ xuống thanh tác vụ và tool vẫn tạo."),
      h("div", { class: "row end", style: "margin-top:18px" },
        h("button", { type: "button", class: "btn ghost", onclick: () => m.close() }, "Ở lại"),
        h("button", { type: "button", class: "btn", id: "closeQuit", onclick: () => choose("quit") }, "Tạm dừng và thoát"),
        h("button", { type: "button", class: "btn primary", id: "closeBg", onclick: () => choose("background") }, "Chạy nền tiếp")),
    ]);
    document.getElementById("closeBg").focus();
  };
}
