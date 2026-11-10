// Môi trường "app cửa sổ riêng" (pywebview, xem desktop/app.py). Trong trình duyệt thường mọi thứ ở đây là no-op.
// Cách phát hiện: pywebview luôn tạo window.pywebview; các hàm Python (js_api) chỉ có sau sự kiện "pywebviewready".

export const inApp = () => !!window.pywebview;

let apiP = null;
/** js_api của desktop/app.py ({ info, save_dialog, save_url, dropped_files, … }) hoặc null nếu không ở trong app. */
export function appApi() {
  if (!inApp()) return Promise.resolve(null);
  return (apiP ||= new Promise((resolve) => {
    const ok = () => (window.pywebview.api && window.pywebview.api.info ? resolve(window.pywebview.api) : false);
    if (!ok()) { window.addEventListener("pywebviewready", ok, { once: true }); setTimeout(() => resolve(window.pywebview.api || null), 5000); }
  }));
}

/** Nút "Tải về" dùng chung. Trong app: hộp thoại "Lưu thành…" gốc; ngoài app: <a download> như thường.
 *  src: đường dẫn trên server ("/api/…"), URL blob:, hoặc Blob. Trả true nếu đã lưu (trong app) / đã bấm tải (trình duyệt). */
export async function saveAs(src, name, { onStart, onDone } = {}) {
  const api = await appApi();
  if (!api) {
    const a = document.createElement("a");
    a.download = name; a.href = typeof src === "string" ? src : URL.createObjectURL(src);
    document.body.append(a); a.click(); a.remove();
    return true;
  }
  if (typeof src === "string" && src.startsWith(location.origin + "/")) src = src.slice(location.origin.length);   // URL tuyệt đối cùng nơi → đường dẫn
  const t = await api.save_dialog(name);
  if (!t || !t.ok) return false;              // bấm Huỷ
  onStart && onStart(t);
  let r;
  if (typeof src === "string" && !src.startsWith("blob:")) r = await api.save_url(t.token, src);
  else {                                      // dữ liệu nằm trong trình duyệt (blob): đẩy nguyên khối sang Python qua route riêng của app
    const blob = typeof src === "string" ? await (await fetch(src)).blob() : src;
    const res = await fetch("/_app/save/" + t.token, { method: "PUT", body: blob });
    r = res.ok ? await res.json() : { ok: false, error: "Không ghi được file." };
  }
  if (!r || !r.ok) throw new Error((r && r.error) || "Không lưu được file.");
  onDone && onDone({ ...t, ...r });
  return true;
}

/** Gắn vào mọi liên kết tải: trong app thì chặn <a download> mặc định rồi lưu qua hộp thoại gốc. Gọi một lần ở app.js. */
export function interceptDownloads(onSaved, onError) {
  if (!inApp()) return;
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[download]");
    if (!a || e.defaultPrevented) return;
    e.preventDefault();
    saveAs(a.getAttribute("href"), a.getAttribute("download") || "tai-ve", { onDone: onSaved }).catch(onError);
  }, true);
}

/** Micro dùng được trong trình duyệt/backend này? (Không → ẩn nút Ghi âm, chỉ còn chọn file.) */
export const canRecord = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
