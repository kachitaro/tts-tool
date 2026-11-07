// Ghi âm bằng micro và xem thời lượng file mẫu. Ghi âm được giải mã ngay trong trình duyệt rồi gửi dạng WAV
// để tool không phụ thuộc codec của từng trình duyệt.
export const SAMPLE_MIN = 3, SAMPLE_MAX = 30, SAMPLE_GOOD = 10;

/** Thời lượng (giây) của file âm thanh; null nếu trình duyệt không giải mã được (để tool kiểm tra khi lưu). */
export async function audioDuration(file) {
  try {
    const ctx = new AudioContext();
    const buf = await ctx.decodeAudioData(await file.arrayBuffer());
    ctx.close();
    return buf.duration;
  } catch { return null; }
}

/** Đánh giá thời lượng mẫu → { level: "ok" | "warn" | "bad" | "unknown", text } bằng lời thường. */
export function judgeDuration(d) {
  if (d === null) return { level: "unknown", text: "Không xem được thời lượng. Tool sẽ kiểm tra khi bạn lưu." };
  const s = d.toFixed(1).replace(".", ",");
  if (d < SAMPLE_MIN) return { level: "bad", text: `Mẫu quá ngắn (${s} giây). Cần từ ${SAMPLE_MIN} đến ${SAMPLE_MAX} giây.` };
  if (d > SAMPLE_MAX) return { level: "bad", text: `Mẫu quá dài (${s} giây). Cần từ ${SAMPLE_MIN} đến ${SAMPLE_MAX} giây.` };
  if (d > SAMPLE_GOOD) return { level: "warn", text: `Mẫu dài ${s} giây. Dùng được, nhưng 3–10 giây thường cho giọng giống hơn.` };
  return { level: "ok", text: `Mẫu dài ${s} giây. Tốt.` };
}

export function encodeWav(buf) {
  const n = buf.length, ch = buf.numberOfChannels, pcm = new Int16Array(n);
  const data = Array.from({ length: ch }, (_, c) => buf.getChannelData(c));
  for (let i = 0; i < n; i++) {
    let s = 0;
    for (let c = 0; c < ch; c++) s += data[c][i];
    pcm[i] = Math.max(-1, Math.min(1, s / ch)) * 0x7fff;
  }
  const dv = new DataView(new ArrayBuffer(44 + n * 2));
  const str = (o, t) => [...t].forEach((c, i) => dv.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); dv.setUint32(4, 36 + n * 2, true); str(8, "WAVEfmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, buf.sampleRate, true); dv.setUint32(28, buf.sampleRate * 2, true);
  dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); str(36, "data"); dv.setUint32(40, n * 2, true);
  new Int16Array(dv.buffer, 44).set(pcm);
  return new File([dv.buffer], "ghi-am.wav", { type: "audio/wav" });
}

async function recordedToFile(blob) {
  try {
    const ctx = new AudioContext();
    const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
    ctx.close();
    return encodeWav(buf);
  } catch { return new File([blob], "ghi-am." + (blob.type.includes("ogg") ? "ogg" : "webm"), { type: blob.type }); }
}

export const MIC_DENIED = "Không dùng được micro. Hãy cho phép trang này dùng micro (bấm biểu tượng ổ khoá cạnh địa chỉ), hoặc chọn file ghi âm có sẵn.";

/**
 * Bắt đầu ghi âm. onTick(giây) mỗi 250 ms; tự dừng ở SAMPLE_MAX giây.
 * Trả { stop(), done: Promise<File|null> }. Ném Error(MIC_DENIED) nếu không mở được micro.
 */
export async function recordMic(onTick = () => {}) {
  if (!navigator.mediaDevices || !window.MediaRecorder) throw new Error(MIC_DENIED);
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { throw new Error(MIC_DENIED); }
  const rec = new MediaRecorder(stream), chunks = [], t0 = Date.now();
  rec.ondataavailable = (e) => chunks.push(e.data);
  const tick = setInterval(() => { const s = (Date.now() - t0) / 1000; onTick(s); if (s >= SAMPLE_MAX) rec.stop(); }, 250);
  const done = new Promise((resolve) => {
    rec.onstop = async () => {
      clearInterval(tick);
      stream.getTracks().forEach((t) => t.stop());
      resolve(chunks.length ? await recordedToFile(new Blob(chunks, { type: rec.mimeType })) : null);
    };
  });
  rec.start();
  return { stop: () => { if (rec.state !== "inactive") rec.stop(); }, done };
}
