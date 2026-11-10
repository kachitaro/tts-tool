// Đổi lỗi kỹ thuật thành lời thường, kèm cách khắc phục. Chi tiết gốc để trong "Xem chi tiết".
// Hàm thuần (không đụng DOM) để thử bằng node: tests/js/errors.test.mjs.

/** @returns {{title: string, tip: string, detail: string}} */
export function explain(err) {
  const status = err && typeof err.status === "number" ? err.status : -1;
  const msg = String((err && err.message) || err || "");
  const out = (title, tip = "", detail = msg) => ({ title, tip, detail });

  if (status === 0 || /Failed to fetch|NetworkError|Load failed/i.test(msg)) {
    return out("Không kết nối được với tool.", "Kiểm tra tool còn đang chạy không, rồi tải lại trang.");
  }
  if (/No audio was received|edge-tts lỗi|Không nạp được edge|Cannot connect to host|timed? ?out/i.test(msg)) {
    return out("Giọng online đang bận, đã thử lại 3 lần.", "Thử lại sau ít phút, hoặc chọn một giọng trên máy (không cần mạng).");
  }
  if (/Chưa cài/i.test(msg)) {
    return out("Giọng này chưa được cài trên máy.", "Chọn giọng khác, hoặc mở Cài đặt → Nâng cao để xem cách cài.");
  }
  if (/VieNeu.*lỗi|Không nạp được VieNeu/i.test(msg)) {
    return out("Giọng trên máy gặp trục trặc.", "Thử lại. Nếu vẫn lỗi, tắt tool rồi mở lại, hoặc tạm dùng giọng online.");
  }
  if (/lỗi thời|cần tạo lại/i.test(msg)) return out(msg, "");
  if (status === 413) return out("File quá lớn.", "Chọn file nhỏ hơn hoặc chia thành nhiều file.");
  if (status === 404) return out("Không tìm thấy mục này.", "Có thể nó đã bị xoá. Tải lại trang để cập nhật.");
  if (status === 409) return out(msg || "Việc này đang bận.", "Đợi việc đang chạy xong rồi thử lại.", "");
  if (status === 422) return out("Dữ liệu chưa hợp lệ.", "Kiểm tra lại các ô vừa nhập.");
  if (status >= 500 || status === -1) return out("Tool gặp lỗi bất ngờ.", "Thử lại sau ít phút. Nếu lặp lại, tắt tool rồi mở lại.");
  // 400…: server đã viết sẵn câu tiếng Việt dễ hiểu ("Hãy nhập văn bản.", "Thẻ nghỉ phải từ 0.1 đến 5 giây…")
  return out(msg || "Có lỗi xảy ra.", "", "");
}
