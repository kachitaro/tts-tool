// In ra JSON {dòng mẫu: mẫu suy ra} để smoke test Python kiểm tra mẫu đó với server thật. Chạy: node tests/js/print_patterns.mjs
import { inferTitlePattern } from "../../web/js/titlepattern.js";
const ex = ["Chương 5: Gặp gỡ", "Hồi 5. Gặp gỡ", "Chapter 5", "第5章 开始", "5. Cuối cùng", "Mở đầu"];
console.log(JSON.stringify(Object.fromEntries(ex.map((e) => [e, inferTitlePattern(e)]))));
