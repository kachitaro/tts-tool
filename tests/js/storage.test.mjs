// Dọn localStorage: xoá khoá cũ (gv:trial5:*, khoá của giao diện cũ), giữ mọi khoá còn dùng.
import assert from "node:assert/strict";
globalThis.localStorage = {};   // store.js chỉ chạm tới localStorage khi gọi hàm; staleKeys là hàm thuần
const { staleKeys, KEPT_KEYS } = await import("../../static/js/store.js");
const keep = [...KEPT_KEYS.map((k) => "gv:" + k), "gv:voice:vieneu", "gv:voice:edge", "other-app"];
const drop = ["gv:trial5:truyen-a", "gv:trial5:b", "engine", "voice:vieneu", "gv:khong-biet", "gv:notify"];
assert.deepEqual(staleKeys([...keep, ...drop]).sort(), drop.sort());
console.log("ok: staleKeys");
