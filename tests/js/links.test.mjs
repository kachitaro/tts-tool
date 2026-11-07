// Quét mã giao diện mới: mọi đích go("/…") / href="#/…" phải khớp một route đã đăng ký trong app.js,
// và không nơi nào được trỏ tới giao diện cũ (/legacy). Chạy: node tests/js/links.test.mjs
import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

const root = new URL("../../static/", import.meta.url);
const files = ["index.html", ...readdirSync(new URL("js/", root)).filter((f) => f.endsWith(".js")).map((f) => "js/" + f),
  ...readdirSync(new URL("js/views/", root)).map((f) => "js/views/" + f)];
const src = Object.fromEntries(files.map((f) => [f, readFileSync(new URL(f, root), "utf8")]));

const routes = [...src["js/app.js"].matchAll(/route\("([^"]+)"/g)].map((m) => m[1]);
assert.ok(routes.length >= 9, routes);
const rx = routes.map((r) => new RegExp("^" + r.replace(/:[a-z]+/g, "[^/]+") + "$"));
const known = (p) => rx.some((r) => r.test(p));

let n = 0;
for (const [f, text] of Object.entries(src)) {
  assert.ok(!/legacy/i.test(text), `${f} còn nhắc tới giao diện cũ (legacy)`);
  for (const m of text.matchAll(/(?:go\(|href: |href=)[`"'](#?\/[^"'`]*)[`"']/g)) {
    const p = m[1].replace(/^#/, "").replace(/\$\{[^}]*\}/g, "x").replace(/(.)\/$/, "$1");
    if (p.startsWith("/api/") || p.startsWith("/css/") || p.startsWith("/js/")) continue;
    assert.ok(known(p), `${f}: đích "${m[1]}" không khớp route nào (${routes.join(", ")})`);
    n++;
  }
}
assert.ok(n >= 15, "quét được quá ít liên kết: " + n);
console.log(`ok: ${n} liên kết/điều hướng đều khớp ${routes.length} route, không có liên kết tới /legacy`);
