// Ngưỡng thời lượng mẫu giọng: dưới 3 giây hoặc trên 30 giây thì không cho tiếp; 10–30 giây chỉ cảnh báo.
import { judgeDuration } from "../../web/js/recorder.js";
import assert from "node:assert/strict";

const lvl = (d) => judgeDuration(d).level;
assert.equal(lvl(2.9), "bad");
assert.equal(lvl(3), "ok");
assert.equal(lvl(10), "ok");
assert.equal(lvl(10.1), "warn");
assert.equal(lvl(30), "warn");
assert.equal(lvl(30.1), "bad");
assert.equal(lvl(null), "unknown");     // trình duyệt không giải mã được: để server quyết định
assert.match(judgeDuration(1.5).text, /1,5 giây/);
console.log("ok: judgeDuration");
