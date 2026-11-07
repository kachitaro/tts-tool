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
