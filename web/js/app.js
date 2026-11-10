// Khởi động giao diện: khung (thanh trên cùng, trình phát, ngăn kéo lịch sử), điều hướng, trạng thái chung.
import { $, h, fmtLeft } from "./dom.js";
import { route, startRouter, go } from "./router.js";
import { initPlayer } from "./player.js";
import { initShortcuts } from "./shortcuts.js";
import { interceptDownloads } from "./appenv.js";
import { installAppClose } from "./appclose.js";
import { guardStrayDrops } from "./dropfiles.js";
import { savedToast, showError } from "./ui.js";
import { cleanupStorage } from "./store.js";
import { overview, refreshOverview } from "./overview.js";
import { openHistory, closeHistory } from "./history.js";
import { openSettings } from "./settings.js";
import { mountHome } from "./views/home.js";
import { mountBooks } from "./views/books.js";
import { mountWizardStart, mountWizardCheck, mountWizardVoice } from "./views/wizard.js";
import { mountBook } from "./views/book.js";
import { mountRead } from "./views/read.js";
import { mountVoices } from "./views/voices.js";
import { mountMix } from "./views/mix.js";

route("/", mountHome);
route("/sach", mountBooks);
route("/sach/them", mountWizardStart);
route("/sach/:id", mountBook);
route("/sach/:id/kiem-tra", mountWizardCheck);
route("/sach/:id/giong", mountWizardVoice);
route("/doc", mountRead);
route("/giong", mountVoices);
route("/giong/pha", mountMix);

/** Chỉ báo "Đang tạo: Truyện X, chương 12/171, còn ~9 giờ" — bấm vào để tới truyện. */
function paintRunning() {
  const el = $("#running"), c = overview.data && overview.data.current;
  el.classList.toggle("hidden", !c);
  if (!c) return;
  const left = c.paused ? "đang tạm dừng" : c.estimate_seconds != null ? `còn ~${fmtLeft(c.estimate_seconds)}` : "đang tính thời gian";
  const n = c.chapter ? `chương ${c.chapter}/${c.chapters}` : `${c.done}/${c.chapters} chương`;
  $("#runningText").textContent = `Đang tạo: ${c.title}, ${n}, ${left}`;
  el.dataset.book = c.book;
}

$("#running").addEventListener("click", () => go("/sach/" + encodeURIComponent($("#running").dataset.book)));
$("#btnHistory").addEventListener("click", openHistory);
$("#btnSettings").addEventListener("click", openSettings);
$("#scrim").addEventListener("click", closeHistory);
$("#logo").addEventListener("click", () => go("/"));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeHistory(); });
document.addEventListener("gv:overview", paintRunning);

cleanupStorage();
initShortcuts();
guardStrayDrops();
interceptDownloads(savedToast, showError);
installAppClose();
initPlayer();
startRouter();
refreshOverview();
