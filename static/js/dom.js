// Tiện ích DOM nhỏ dùng chung (không framework).
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** h("div", { class: "a", onclick: fn, dataset: {x: 1}, hidden: true }, "chữ", node, ...) → Element */
export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k in el && k !== "list" && k !== "form") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  el.append(...kids.flat().filter((c) => c != null && c !== false));
  return el;
}

export const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const fmtDate = (iso) => new Date(iso).toLocaleString("vi-VN", { hour12: false, dateStyle: "short", timeStyle: "short" });

/** 3300 giây → "55 phút", 33000 → "9 giờ 10 phút" */
export function fmtLeft(sec) {
  if (sec == null) return "";
  const m = Math.max(1, Math.round(sec / 60));
  if (m < 60) return `${m} phút`;
  const hh = Math.floor(m / 60), mm = m % 60;
  return mm ? `${hh} giờ ${mm} phút` : `${hh} giờ`;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
