"""Smoke test giao diện bằng Chrome headless (giao thức DevTools qua aiohttp, không cần cài thêm gì).
Với server đang chạy ở BASE (tham số 1), mở từng route ở 390 / 768 / 1280 px và kiểm tra:
  - không có lỗi JS (exception, console.error, lỗi tải tệp; bỏ qua ERR_ABORTED do huỷ yêu cầu cũ),
  - trang không tràn ngang,
  - mọi nút chỉ có biểu tượng đều có aria-label,
  - không có từ cấm (quy tắc 4 của PROMPTS-UX.md) xuất hiện ngoài khối "Nâng cao" — cả trên trang lẫn trong
    Cài đặt chung, Lịch sử, phím tắt, hộp thoại thêm giọng, các tab của trang truyện, công cụ sửa chương,
  - phím tắt: "?" mở bảng phím tắt, Esc đóng.
In "PASS  tên" / "FAIL  tên — lý do"; thoát mã 1 nếu có FAIL; in SKIP và thoát 0 nếu máy không có Chrome.
Chạy: python scripts/smoke_ui.py http://127.0.0.1:8765
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

import aiohttp

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765").rstrip("/")
BANNED = [
    "engine",
    "precision",
    "int8",
    "fp32",
    "alpha",
    "slider",
    "cache",
    "regex",
    "selector",
    "seed",
    "RTF",
    "embedding",
    "mode",
    "job",
    "queue",
]
BANNED_RX = re.compile(r"\b(" + "|".join(BANNED) + r")\b", re.I)
fails = 0

# Gom chữ nhìn thấy (nội dung chữ + aria-label / placeholder / title) bỏ phần "Nâng cao", mã, phím.
JS_TEXT = r"""(() => {
  const skip = (n) => n.closest && n.closest('details.adv, script, style, code, kbd');
  const out = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) if (!skip(n.parentElement) && n.nodeValue.trim()) out.push(n.nodeValue.trim());
  document.querySelectorAll('[aria-label],[placeholder],[title]').forEach((e) => { if (!skip(e)) for (const a of ['aria-label', 'placeholder', 'title']) { const v = e.getAttribute(a); if (v) out.push(v); } });
  return out.join(' \n ');
})()"""
JS_ICON_BUTTONS = r"""(() => [...document.querySelectorAll('button,a.btn,[role=button]')].filter((b) => b.getClientRects().length && !b.textContent.trim().replace(/[\p{P}\p{S}\s]/gu, '') && !b.getAttribute('aria-label') && !b.getAttribute('title')).map((b) => b.outerHTML.slice(0, 80)))()"""


def report(name: str, err: str | None = None) -> None:
    global fails
    if err:
        fails += 1
        print(f"FAIL  {name} — {err[:400]}", flush=True)
    else:
        print(f"PASS  {name}", flush=True)


class Page:
    def __init__(self, ws):
        self.ws, self.n, self.pending, self.errors = ws, 0, {}, []
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        async for m in self.ws:
            if m.type != aiohttp.WSMsgType.TEXT:
                continue
            d = json.loads(m.data)
            if "id" in d and d["id"] in self.pending:
                self.pending.pop(d["id"]).set_result(d)
                continue
            p, meth = d.get("params", {}), d.get("method")
            if meth == "Runtime.exceptionThrown":
                x = p["exceptionDetails"]
                self.errors.append(
                    "exception: "
                    + (x.get("exception", {}).get("description") or x.get("text", ""))[:200]
                )
            elif meth == "Runtime.consoleAPICalled" and p["type"] == "error":
                self.errors.append(
                    "console.error: "
                    + " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"])[
                        :200
                    ]
                )
            elif meth == "Log.entryAdded" and p["entry"]["level"] == "error":
                e = p["entry"]
                if "ERR_ABORTED" not in e.get("text", "") and "ERR_ABORTED" not in e.get("url", ""):
                    self.errors.append("log: " + e.get("text", "") + " " + e.get("url", ""))

    async def call(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send_str(json.dumps({"id": self.n, "method": method, "params": params}))
        r = await asyncio.wait_for(fut, 30)
        if "error" in r:
            raise RuntimeError(f"{method}: {r['error']}")
        return r["result"]

    async def ev(self, expr: str):
        r = await self.call(
            "Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True
        )
        if "exceptionDetails" in r:
            raise RuntimeError("JS: " + json.dumps(r["exceptionDetails"], ensure_ascii=False)[:300])
        return r["result"].get("value")

    async def until(self, expr: str, what: str, timeout: float = 20):
        t = time.time()
        while time.time() - t < timeout:
            if await self.ev(expr):
                return
            await asyncio.sleep(0.15)
        raise TimeoutError(f"quá {timeout}s chờ {what}")

    async def size(self, w: int, h: int = 900):
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            width=w,
            height=h,
            deviceScaleFactor=1,
            mobile=w < 600,
        )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def banned_in(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in BANNED_RX.finditer(text)})


async def main() -> None:
    import httpx

    chrome = (
        shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if not chrome:
        print("SKIP  không có Chrome / Chromium: bỏ qua smoke giao diện")
        return
    api = httpx.Client(base_url=BASE, timeout=60)
    story = "\n".join(
        f"Chương {i}: Tiêu đề {i}\n"
        + "\n".join(
            f"Ánh trăng chiếu xuống mặt hồ yên ả ở cảnh số {i}-{j}, gió đêm thổi nhẹ qua hàng cây."
            for j in range(1, 7)
        )
        for i in range(1, 8)
    )
    bid = api.post(
        "/api/books/import",
        files=[("files", ("ui.txt", story.encode(), "text/plain"))],
        data={"title": "Truyện thử giao diện"},
    ).json()["id"]
    r = api.post(f"/api/books/{bid}/chapters", json={})
    assert r.status_code == 200, r.text
    port, prof = free_port(), tempfile.mkdtemp(prefix="smoke_ui_")
    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={prof}",
            "--no-first-run",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        async with aiohttp.ClientSession() as http:
            for _ in range(60):
                try:
                    async with http.get(f"http://127.0.0.1:{port}/json/version") as r:
                        if r.status == 200:
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.25)
            async with http.put(f"http://127.0.0.1:{port}/json/new?about:blank") as r:
                target = await r.json()
            async with http.ws_connect(target["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                pg = Page(ws)
                for d in ("Runtime", "Log", "Page"):
                    await pg.call(d + ".enable")
                await pg.call("Page.navigate", url=BASE + "/")
                await pg.until(
                    "!!document.querySelector('#view') && document.querySelector('#view').children.length > 0",
                    "trang chủ",
                )
                await run(pg, bid)
    finally:
        os.killpg(
            proc.pid, signal.SIGKILL
        )  # Chrome có nhiều tiến trình con: giết cả nhóm rồi mới xoá hồ sơ tạm
        proc.wait()
        for _ in range(20):
            shutil.rmtree(prof, ignore_errors=True)
            if not os.path.exists(prof):
                break
            time.sleep(0.25)
        for _ in range(
            240
        ):  # đoạn đang dựng dở phải xong mới dừng; lần đầu nạp model có thể mất hơn 20 giây
            if api.delete(f"/api/books/{bid}").status_code in (200, 404):
                break
            time.sleep(0.5)
        else:
            report("dọn truyện thử của smoke_ui", f"không xoá được {bid} sau 120 giây")


async def run(pg: Page, bid: str) -> None:
    routes = [
        "/",
        "/sach",
        "/sach/them",
        f"/sach/{bid}",
        f"/sach/{bid}/kiem-tra",
        f"/sach/{bid}/giong",
        "/doc",
        "/giong",
        "/giong/pha",
    ]
    texts: dict[str, str] = {}

    async def open_route(r: str) -> None:
        if (
            await pg.ev("location.hash") == "#" + r
        ):  # cùng route: đi chỗ khác rồi quay lại để dựng lại màn hình
            await pg.ev("location.hash = '#/sach'" if r != "/sach" else "location.hash = '#/'")
            await asyncio.sleep(0.4)
        await pg.ev(f"location.hash = '#{r}'")
        await asyncio.sleep(0.3)
        await pg.until(
            "document.querySelector('#view').children.length > 0 && !document.querySelector('#view .skel')",
            f"route {r}",
        )
        await asyncio.sleep(0.5)

    # 1. mọi route × 3 cỡ màn hình: không lỗi JS, không tràn ngang, nút biểu tượng có nhãn
    for w in (1280, 768, 390):
        await pg.size(w)
        for r in routes:
            name = f"UI {w}px {r.replace(bid, '<truyện>')}: mở được, không lỗi JS, không tràn ngang, nút biểu tượng có aria-label"
            pg.errors.clear()
            try:
                await open_route(r)
                sw = await pg.ev("document.documentElement.scrollWidth")
                assert sw <= w, f"trang rộng {sw}px > {w}px"
                icons = await pg.ev(JS_ICON_BUTTONS)
                assert not icons, f"nút không có nhãn: {icons[:3]}"
                assert not pg.errors, pg.errors[:3]
                if w == 1280:
                    texts[r] = await pg.ev(JS_TEXT)
                report(name)
            except Exception as ex:  # noqa: BLE001
                report(name, f"{type(ex).__name__}: {ex}")

    # 2. thao tác mở thêm các khối chữ: tab, công cụ sửa, hộp thoại, ngăn kéo
    await pg.size(1280)
    steps = [
        (
            "Cài đặt chung",
            "/",
            "document.querySelector('#btnSettings').click()",
            "document.querySelector('.modal')",
            "Escape",
        ),
        (
            "Lịch sử",
            "/",
            "document.querySelector('#btnHistory').click()",
            "document.querySelector('#drawer .body, #drawer h3')",
            "Escape",
        ),
        (
            "bảng phím tắt (?)",
            "/",
            "document.dispatchEvent(new KeyboardEvent('keydown', {key: '?', bubbles: true}))",
            "document.querySelector('.modal kbd')",
            "Escape",
        ),
        (
            "hộp thoại thêm giọng",
            "/giong",
            "document.querySelector('#addVoice').click()",
            "document.querySelector('.modal')",
            "Escape",
        ),
        (
            "tab Cách đọc tên riêng",
            f"/sach/{bid}",
            "[...document.querySelectorAll('.tabs button')][1].click()",
            "document.querySelector('#view .card.flat')",
            None,
        ),
        (
            "tab Cài đặt của truyện",
            f"/sach/{bid}",
            "[...document.querySelectorAll('.tabs button')][2].click()",
            "document.querySelector('#view input')",
            None,
        ),
        (
            "hộp Tạo một khoảng chương",
            f"/sach/{bid}",
            "document.querySelectorAll('.tabs button')[0].click(); [...document.querySelectorAll('.btn')].find(b => b.textContent.includes('Tạo nhiều chương')).click(); document.querySelector('.menu .pop:not(.hidden) button').click()",
            "document.querySelector('.modal')",
            "Escape",
        ),
        (
            "công cụ sửa chương",
            f"/sach/{bid}/kiem-tra",
            "[...document.querySelectorAll('.btn')].find(b => b.textContent.startsWith('Có chỗ sai')).click()",
            "document.querySelector('.fixpanel')",
            None,
        ),
        (
            "chọn giọng trong Pha giọng",
            "/giong/pha",
            "document.querySelectorAll('.mixcard .btn')[0].click()",
            "document.querySelector('.modal .vrow')",
            "Escape",
        ),
    ]
    for label, route, action, ready, close in steps:
        name = f"UI: mở “{label}”: không lỗi JS, nút biểu tượng có nhãn"
        pg.errors.clear()
        try:
            await open_route(route)
            await pg.ev(action)
            await pg.until(f"!!({ready})", label)
            await asyncio.sleep(0.4)
            texts[label] = await pg.ev(JS_TEXT)
            icons = await pg.ev(JS_ICON_BUTTONS)
            assert not icons, f"nút không có nhãn: {icons[:3]}"
            assert not pg.errors, pg.errors[:3]
            if close:
                await pg.call(
                    "Input.dispatchKeyEvent",
                    type="keyDown",
                    key=close,
                    code=close,
                    windowsVirtualKeyCode=27,
                )
                await pg.call(
                    "Input.dispatchKeyEvent",
                    type="keyUp",
                    key=close,
                    code=close,
                    windowsVirtualKeyCode=27,
                )
                await pg.until(
                    "!document.querySelector('#modalHost .modal') && !document.querySelector('#drawer.open')",
                    f"Esc đóng {label}",
                    5,
                )
            report(name)
        except Exception as ex:  # noqa: BLE001
            report(name, f"{type(ex).__name__}: {ex}")

    # 3. luồng chính của trình 3 bước: bước 3 → "Tạo thử 5 chương trước" → server ghi trial {limit: 5}
    name = "UI: bước 3 bấm “Bắt đầu tạo sách nói” với “Tạo thử 5 chương trước” → server ghi trial (limit 5), mở trang truyện"
    pg.errors.clear()
    try:
        await open_route(f"/sach/{bid}/giong")
        await pg.ev(
            "(() => { const c = document.querySelector('.stickyfoot input[type=checkbox]'); if (!c.checked) c.click(); })()"
        )
        await pg.ev("document.querySelector('#start').click()")
        await pg.until(
            f"location.hash === '#/sach/{bid}' && !!document.querySelector('.dash')",
            "trang truyện sau khi bắt đầu",
            30,
        )
        import httpx as _h

        q = _h.get(f"{BASE}/api/queue", params={"book": bid}, timeout=30).json()
        assert q["trial"] and q["trial"]["limit"] == 5, q["trial"]
        _h.post(f"{BASE}/api/queue/cancel", json={}, timeout=60)
        assert not pg.errors, pg.errors[:3]
        report(name)
    except Exception as ex:  # noqa: BLE001
        report(name, f"{type(ex).__name__}: {ex}")

    # 4. từ cấm ngoài khối "Nâng cao"
    bad = {k: banned_in(v) for k, v in texts.items() if banned_in(v)}
    report(
        f"không có từ kỹ thuật bị cấm ngoài “Nâng cao” ({len(texts)} màn / hộp thoại đã quét)",
        None if not bad else f"{bad}",
    )
    # 5. quét ngược: trong khối Nâng cao vẫn được phép có từ kỹ thuật, nhưng khối phải đóng sẵn
    await open_route(f"/sach/{bid}/kiem-tra")
    opened = await pg.ev("document.querySelectorAll('details.adv[open]').length")
    report(
        "khối “Nâng cao” đóng sẵn khi mở màn hình",
        None if opened == 0 else f"{opened} khối đang mở",
    )


try:
    asyncio.run(main())
except Exception as ex:  # noqa: BLE001
    report("smoke giao diện chạy được", f"{type(ex).__name__}: {ex}")
sys.exit(1 if fails else 0)
