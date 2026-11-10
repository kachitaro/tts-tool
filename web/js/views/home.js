// Màn chính: 3 thẻ lớn + truyện đang làm dở.
import { h } from "../dom.js";
import { go } from "../router.js";
import { overview } from "../overview.js";
import { bookCard } from "./books.js";

export function mountHome(root) {
  const bigcard = (cls, emoji, title, text, to, cta) => h("button", { class: "bigcard " + cls, onclick: () => go(to) },
    h("span", { class: "emoji", "aria-hidden": "true" }, emoji), h("div", {}, h("h3", {}, title), h("p", {}, text)), h("span", { class: "go" }, cta));
  const dolist = h("div", {});
  root.append(
    h("div", { class: "pagehead" }, h("h2", {}, "Chào bạn, hôm nay muốn làm gì?")),
    h("p", { class: "lead" }, "Chọn một việc bên dưới. Việc nào cũng làm được ngay, không cần cài đặt gì thêm."),
    h("div", { class: "bigcards" },
      bigcard("main", "📚", "Làm sách nói", "Biến cả một bộ truyện thành sách nói, từng chương một.", "/sach", "Bắt đầu →"),
      bigcard("", "🗣️", "Đọc văn bản", "Dán một đoạn chữ, nghe đọc ngay. Có thể cho nhiều người cùng đọc.", "/doc", "Mở →"),
      bigcard("", "🎙️", "Giọng đọc", "Nghe thử các giọng, thêm giọng từ file ghi âm hoặc pha giọng mới.", "/giong", "Xem →")),
    dolist);
  const paint = () => {
    const books = ((overview.data && overview.data.books) || []).filter((b) => b.status === "ready" && b.done < b.chapters);
    dolist.replaceChildren(...(books.length ? [h("h3", { style: "margin:36px 0 14px" }, "Đang làm dở"), h("div", { class: "booklist" }, ...books.map(bookCard))] : []));
  };
  paint();
  document.addEventListener("gv:overview", paint);
  return () => document.removeEventListener("gv:overview", paint);
}
