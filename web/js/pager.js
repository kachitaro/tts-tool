// Phân trang cho danh sách dài (truyện hàng nghìn chương): chỉ vẽ một trang mỗi lần.
import { h } from "./dom.js";

export const PAGE_SIZE = 50;

/** Pager({ total, page, size, onPage }) → Node. page bắt đầu từ 0. Ẩn khi chỉ có một trang. */
export function Pager({ total, page, size = PAGE_SIZE, onPage }) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return h("span", {});
  const jump = h("input", { type: "number", min: 1, max: pages, value: page + 1, "aria-label": "Số trang", style: "width:80px",
    onkeydown: (e) => { if (e.key === "Enter") onPage(Math.min(pages, Math.max(1, +jump.value || 1)) - 1); } });
  const b = (label, to, aria, disabled) => h("button", { type: "button", class: "btn small", "aria-label": aria, disabled, onclick: () => onPage(to) }, label);
  return h("div", { class: "pager row" },
    b("«", 0, "Trang đầu", page === 0), b("‹", page - 1, "Trang trước", page === 0),
    h("span", { class: "muted" }, "Trang ", jump, ` / ${pages}`),
    b("›", page + 1, "Trang sau", page >= pages - 1), b("»", pages - 1, "Trang cuối", page >= pages - 1));
}
