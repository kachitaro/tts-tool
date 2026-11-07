// Làm sách nói: danh sách truyện. Bấm vào truyện → trang truyện; truyện chưa chia chương → tiếp tục bước Kiểm tra.
import { h } from "../dom.js";
import { go } from "../router.js";
import { overview } from "../overview.js";

export const bookPath = (b) => (b.status === "ready" ? `/sach/${encodeURIComponent(b.id)}` : `/sach/${encodeURIComponent(b.id)}/kiem-tra`);

export function bookCard(b) {
  const pct = b.chapters ? Math.round((b.done / b.chapters) * 100) : 0;
  const tag = b.running ? h("span", { class: "tag run" }, "Đang tạo")
    : b.status !== "ready" ? h("span", { class: "tag" }, "Chưa xong bước chuẩn bị")
    : b.done === b.chapters && b.chapters ? h("span", { class: "tag ok" }, "✓ Đã xong") : null;
  const open = () => go(bookPath(b));
  return h("div", { class: "card book", role: "link", tabindex: 0, "aria-label": b.title, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
    h("div", {}, h("h3", {}, b.title, " ", tag),
      h("div", { class: "muted" }, [b.author, b.status === "ready" ? `${b.chapters} chương · đã tạo ${b.done}` : "bấm để tiếp tục chia chương"].filter(Boolean).join(" · ")),
      b.status === "ready" && h("div", { class: "bar", role: "progressbar", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": "Đã tạo " + pct + "%", style: "margin-top:12px" }, h("i", { style: `width:${pct}%` }))),
    h("span", { class: "btn", "aria-hidden": "true" }, b.status === "ready" ? "Mở" : "Tiếp tục"));
}

export function mountBooks(root) {
  const list = h("div", { class: "booklist" });
  root.append(
    h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("span", {}, "Làm sách nói")),
    h("div", { class: "row", style: "justify-content:space-between;margin-bottom:8px" }, h("h2", {}, "Sách nói của bạn"),
      h("button", { class: "btn primary", onclick: () => go("/sach/them") }, "＋ Thêm truyện")),
    h("p", { class: "lead" }, "Thêm file truyện, chọn giọng, rồi để máy tạo từng chương."), list);
  const paint = () => {
    const books = (overview.data && overview.data.books) || [];
    list.replaceChildren(...(books.length ? books.map(bookCard)
      : [h("div", { class: "empty" }, h("div", { class: "emoji", "aria-hidden": "true" }, "📚"), h("p", {}, overview.data ? "Chưa có truyện nào." : "Đang tải…"),
        overview.data && h("button", { class: "btn primary", onclick: () => go("/sach/them") }, "Thêm truyện đầu tiên"))]));
  };
  paint();
  document.addEventListener("gv:overview", paint);
  return () => document.removeEventListener("gv:overview", paint);
}
