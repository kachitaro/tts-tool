// Trình phát dính đáy màn hình: phát mọi thứ (nghe thử, lịch sử, kết quả), có tua và tốc độ phát.
import { $, fmtTime } from "./dom.js";
import { prefs } from "./store.js";
import { showError } from "./ui.js";

const audio = new Audio();
audio.preload = "auto";
const SPEEDS = [1, 1.25, 1.5, 2];
let rate = prefs.get("playRate", 1);
let seeking = false;

function paint() {
  const bar = $("#player");
  bar.classList.remove("idle");
  $("#pPlay").textContent = audio.paused ? "▶" : "❚❚";
  $("#pPlay").setAttribute("aria-label", audio.paused ? "Phát" : "Tạm dừng");
  const dur = isFinite(audio.duration) ? audio.duration : 0;
  $("#pDur").textContent = fmtTime(dur);
  if (!seeking) { $("#pCur").textContent = fmtTime(audio.currentTime); $("#pSeek").max = dur || 1; $("#pSeek").value = audio.currentTime; }
  $("#pSpeed").textContent = rate + "×";
}

/** Phát một nguồn âm thanh. src: URL (kể cả blob:). */
export async function play({ src, title, sub = "" }) {
  $("#pTitle").textContent = title;
  $("#pSub").textContent = sub;
  audio.src = src;
  audio.playbackRate = rate;
  try { await audio.play(); } catch (e) { if (e.name !== "AbortError") showError(e); }
  paint();
}

export function stop() { audio.pause(); }
export const isPlaying = () => !audio.paused;

export function initPlayer() {
  audio.addEventListener("timeupdate", paint);
  audio.addEventListener("loadedmetadata", paint);
  audio.addEventListener("play", paint);
  audio.addEventListener("pause", paint);
  audio.addEventListener("ended", paint);
  audio.addEventListener("error", () => { if (audio.src) showError(new Error("Không phát được âm thanh này.")); });
  $("#pPlay").onclick = () => { if (!audio.src) return; audio.paused ? audio.play() : audio.pause(); };
  $("#pBack").onclick = () => { audio.currentTime = Math.max(0, audio.currentTime - 10); };
  $("#pFwd").onclick = () => { audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 10); };
  $("#pSeek").addEventListener("input", (e) => { seeking = true; $("#pCur").textContent = fmtTime(+e.target.value); });
  $("#pSeek").addEventListener("change", (e) => { audio.currentTime = +e.target.value; seeking = false; });
  $("#pSpeed").onclick = () => {
    rate = SPEEDS[(SPEEDS.indexOf(rate) + 1) % SPEEDS.length];
    audio.playbackRate = rate; prefs.set("playRate", rate); paint();
  };
  $("#pSpeed").textContent = rate + "×";
}
