// Menu ⋯ nhỏ: menuButton("⋯", [{ label, hint, onclick, danger }]) → Node
import { h } from "./dom.js";

let openPop = null;
document.addEventListener("click", (e) => { if (openPop && !openPop.parentElement.contains(e.target)) { openPop.classList.add("hidden"); openPop = null; } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openPop) { openPop.classList.add("hidden"); openPop = null; } });

export function menuButton(label, items, { aria = "Thêm lựa chọn", cls = "btn small" } = {}) {
  const pop = h("div", { class: "pop hidden", role: "menu" }, ...items.filter(Boolean).map((it) =>
    h("button", { type: "button", role: "menuitem", class: it.danger ? "danger" : "", onclick: () => { pop.classList.add("hidden"); openPop = null; it.onclick(); } },
      it.label, it.hint && h("small", {}, it.hint))));
  const btn = h("button", { type: "button", class: cls, "aria-label": aria, "aria-haspopup": "menu", onclick: () => {
    const wasHidden = pop.classList.contains("hidden");
    if (openPop) openPop.classList.add("hidden");
    pop.classList.toggle("hidden", !wasHidden);
    openPop = wasHidden ? pop : null;
  } }, label);
  return h("span", { class: "menu" }, btn, pop);
}
