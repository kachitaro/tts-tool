// Tương phản chữ đạt WCAG AA (≥ 4,5:1 chữ thường) cho các cặp màu chữ / nền thật sự dùng, ở cả bộ sáng và tối.
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const css = readFileSync(new URL("../../web/css/tokens.css", import.meta.url), "utf8");
const [rootBlock, darkBlock] = [css.match(/:root\s*\{([^}]*)\}/)[1], css.match(/prefers-color-scheme: dark\)\s*\{\s*:root\s*\{([^}]*)\}/)[1]];
const vars = (b) => Object.fromEntries([...b.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
const lum = (hex) => { const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// [chữ, nền]: những cặp có thật trong giao diện
const PAIRS = [["text", "bg"], ["text", "surface"], ["text", "surface-2"], ["muted", "bg"], ["muted", "surface"], ["muted", "surface-2"],
  ["accent", "surface"], ["accent", "bg"], ["accent-strong", "surface"], ["on-accent", "accent"], ["on-accent", "accent-strong"], ["text", "accent-soft"], ["accent", "accent-soft"],
  ["err", "surface"], ["text", "err-soft"], ["err", "err-soft"], ["text", "warn-soft"], ["warn", "surface"], ["ok", "surface"]];
const light = vars(rootBlock), dark = { ...light, ...vars(darkBlock) };
const bad = [];
for (const [name, v] of [["sáng", light], ["tối", dark]]) for (const [fg, bg] of PAIRS) {
  const r = ratio(v[fg], v[bg]);
  if (r < 4.5) bad.push(`${name}: ${fg} ${v[fg]} trên ${bg} ${v[bg]} = ${r.toFixed(2)}:1`);
}
assert.deepEqual(bad, [], "cặp màu chưa đạt AA:\n" + bad.join("\n"));
console.log(`ok: ${PAIRS.length * 2} cặp màu đạt ≥ 4,5:1 (sáng + tối)`);
