// Làm sách nói: danh sách truyện (tiến độ). Trình thêm truyện / bảng điều khiển mới sẽ làm ở các bước sau;
// trong lúc đó mọi thao tác dùng trình cũ (/legacy) nên không mất tính năng nào.
import { h } from "../dom.js";
import { overview } from "../overview.js";

const openOld = (hash = "book") => { location.href = "/legacy#" + hash; };

export function bookCard(b) {
  const pct = b.chapters ? Math.round((b.done / b.chapters) * 100) : 0;
  const tag = b.running ? h("span", { class: "tag run" }, "Đang tạo")
    : b.status !== "ready" ? h("span", { class: "tag" }, "Chưa chia chương")
    : b.done === b.chapters && b.chapters ? h("span", { class: "tag ok" }, "Đã xong") : null;
  return h("div", { class: "card book", role: "button", tabindex: 0, onclick: () => openOld("book=" + encodeURIComponent(b.id)),
    onkeydown: (e) => { if (e.key === "Enter") openOld("book=" + encodeURIComponent(b.id)); } },
    h("div", {}, h("h3", {}, b.title, " ", tag), h("div", { class: "muted" }, [b.author, b.status === "ready" ? `${b.chapters} chương · đã tạo ${b.done}` : "cần chia chương"].filter(Boolean).join(" · ")),
      b.status === "ready" && h("div", { class: "bar", style: "margin-top:12px" }, h("i", { style: `width:${pct}%` }))),
    h("button", { class: "btn", tabindex: -1 }, "Mở"));
}

export function mountBooks(root) {
  const list = h("div", { class: "booklist" });
  root.append(
    h("div", { class: "crumb" }, h("a", { href: "#/" }, "Trang chính"), " › ", h("span", {}, "Làm sách nói")),
    h("div", { class: "row", style: "justify-content:space-between;margin-bottom:8px" }, h("h2", {}, "Sách nói của bạn"),
      h("button", { class: "btn primary", onclick: () => openOld("book") }, "＋ Thêm truyện")),
    h("p", { class: "lead" }, "Thêm file truyện, chọn giọng, rồi để máy tạo từng chương."),
    h("div", { class: "notice ok" }, "Phần làm sách nói đang được làm lại cho dễ dùng hơn. Trong lúc đó bạn dùng trình hiện có (mọi tính năng vẫn còn): bấm “Thêm truyện” hoặc mở một truyện bên dưới."),
    list);
  const paint = () => {
    const books = (overview.data && overview.data.books) || [];
    list.replaceChildren(...(books.length ? books.map(bookCard) : [h("p", { class: "muted" }, overview.data ? "Chưa có truyện nào. Bấm “Thêm truyện” để bắt đầu." : "Đang tải…")]));
  };
  paint();
  document.addEventListener("gv:overview", paint);
  return () => document.removeEventListener("gv:overview", paint);
}
