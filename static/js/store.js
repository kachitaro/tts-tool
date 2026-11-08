// Ghi nhớ lựa chọn (localStorage) và bộ nhớ tạm danh sách giọng / engine.
import { getJSON } from "./api.js";

export const prefs = {
  get(key, fallback = null) { try { const v = localStorage.getItem("gv:" + key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem("gv:" + key, JSON.stringify(value)); } catch { /* bộ nhớ đầy / bị chặn */ } },
};

let enginesP = null, voicesP = null;
export const engines = (force = false) => (enginesP = !force && enginesP ? enginesP : getJSON("/api/engines"));
export const voices = (force = false) => (voicesP = !force && voicesP ? voicesP : getJSON("/api/voices"));
export const resetVoices = () => { voicesP = null; };

/** Các khoá localStorage giao diện còn dùng (đều có tiền tố "gv:"). "voice:" là tiền tố: một khoá cho mỗi loại giọng. */
export const KEPT_KEYS = ["engine", "voice-last", "speed", "playRate", "mix:auto"];
export const KEPT_PREFIXES = ["voice:"];

/** Khoá nào cần xoá: khoá "gv:" không còn dùng (vd. gv:trial5:*) và khoá của giao diện cũ ("engine", "voice:*" không có tiền tố). */
export function staleKeys(keys) {
  return keys.filter((k) => {
    if (!k.startsWith("gv:")) return k === "engine" || k.startsWith("voice:");
    const n = k.slice(3);
    return !(KEPT_KEYS.includes(n) || KEPT_PREFIXES.some((p) => n.startsWith(p)));
  });
}

export function cleanupStorage() {
  try { staleKeys(Object.keys(localStorage)).forEach((k) => localStorage.removeItem(k)); } catch { /* bị chặn */ }
}
