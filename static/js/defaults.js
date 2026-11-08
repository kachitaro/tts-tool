// Cài đặt chung (data/settings.json qua /api/settings) và cách chọn giọng mặc định.
import { getJSON, sendJSON } from "./api.js";
import { keyOf } from "./voicepicker.js";

let cache = null;
export const getSettings = async (force = false) => (cache = !force && cache ? cache : await getJSON("/api/settings"));
export async function saveDefaultVoice(v) {
  cache = await sendJSON("/api/settings", { default_voice: v ? { engine: v.engine, voice: v.id } : null }, "PUT");
  return cache;
}

export async function saveNotify(on) {
  cache = await sendJSON("/api/settings", { notify: !!on }, "PUT");
  return cache;
}

const usable = (v) => v.usable !== false && (!v.lang || v.lang.startsWith("vi"));

/** Giọng mặc định: người dùng đã chọn (nếu còn dùng được) → giọng có sẵn đánh dấu ★ đầu tiên của "Giọng trên máy"
 *  → giọng trên máy đầu tiên → giọng đầu danh sách. */
export function effectiveDefault(voices, engines, settings) {
  const ok = voices.filter(usable);
  const chosen = settings && settings.default_voice;
  const mine = chosen && ok.find((v) => v.engine === chosen.engine && v.id === chosen.voice);
  if (mine) return { voice: mine, source: "chosen" };
  const local = ok.filter((v) => engines[v.engine] && engines[v.engine].local);
  const star = local.find((v) => v.source === "preset" && v.favorite);
  if (star) return { voice: star, source: "star" };
  const first = local[0] || ok[0] || null;
  return { voice: first, source: "first" };
}

export { keyOf };
