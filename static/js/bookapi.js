// Gọi API sách nói (giữ ở một chỗ để các màn dùng chung).
import { api, getJSON, sendJSON } from "./api.js";
import { sleep } from "./dom.js";

export const getBook = (id) => getJSON("/api/books/" + encodeURIComponent(id));
export const patchBook = (id, body) => sendJSON("/api/books/" + encodeURIComponent(id), body, "PATCH");
export const previewBook = (id, body) => sendJSON(`/api/books/${encodeURIComponent(id)}/preview`, body);
export const confirmBook = (id, body) => sendJSON(`/api/books/${encodeURIComponent(id)}/chapters`, body);
export const deleteBook = (id) => api("/api/books/" + encodeURIComponent(id), { method: "DELETE" });
export const queueOf = (id) => getJSON("/api/queue?book=" + encodeURIComponent(id));
export const runQueue = (id, body = {}) => sendJSON(`/api/books/${encodeURIComponent(id)}/queue/run`, body);
export const chaptersOf = (id) => getJSON(`/api/books/${encodeURIComponent(id)}/chapters`);

/** "Đọc thử": xếp vào hàng ưu tiên, chờ xong, trả URL âm thanh. onProgress(done, total, status). */
export async function trial(id, n, { chars = 900, offset = 0 } = {}, onProgress = () => {}, alive = () => true) {
  const t = await sendJSON(`/api/books/${encodeURIComponent(id)}/chapters/${n}/trial`, { chars, offset });
  for (;;) {
    const s = await getJSON(`/api/trials/${t.id}`);
    onProgress(s.done, s.total, s.status);
    if (s.status === "error") throw new Error(s.error || "Không tạo được bản nghe thử.");
    if (s.status === "done") return { url: `/api/trials/${t.id}/audio`, seconds: s.seconds };
    if (!alive()) throw new Error("đã huỷ");
    await sleep(600);
  }
}

/** "Tạo thử N chương": server tự dừng sau N chương và ghi book.trial = {limit, done_at}. */
export const startTrial = (id, limit = 5) => runQueue(id, { limit, trial: true });
/** "Để sau" trên banner tạo thử. */
export const dismissTrial = (id) => patchBook(id, { dismiss_trial: true });
