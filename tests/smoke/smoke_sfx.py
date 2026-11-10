"""Smoke test thẻ hiệu ứng âm thanh (gọi từ tests/smoke/smoke_test.sh): in "PASS  tên" / "FAIL  tên — lý do".

Dùng: python tests/smoke/smoke_sfx.py <base_url>
Phần module (sinh đủ âm, tách thẻ, render với engine giả) chạy trên data tạm; phần API chạy trên server đang chạy.
"""

from __future__ import annotations

import asyncio
import atexit
import io
import os
import shutil
import sys
import tempfile

os.environ["TTS_DATA_DIR"] = tempfile.mkdtemp(prefix="smoke_sfx_")
atexit.register(shutil.rmtree, os.environ["TTS_DATA_DIR"], ignore_errors=True)
import httpx  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from giongviet.books import narrate  # noqa: E402
from giongviet.speech import dialogue, sfx  # noqa: E402

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
client = httpx.Client(timeout=60)
fails = 0


def check(name: str, fn) -> None:
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as ex:  # noqa: BLE001
        fails += 1
        print(f"FAIL  {name} — {type(ex).__name__}: {str(ex)[:200]}")


class FakeEngine:
    id, local, name = "fake", True, "Giả"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def capabilities(self) -> dict:
        return {
            "clone": False,
            "pitch": False,
            "emotion_tags": ["[cười]"],
            "mix": False,
            "normalize": False,
        }

    def cache_tag(self) -> str:
        return "t"

    async def synthesize(self, text: str, voice: str, speed: int, **kw):
        self.calls.append(text)
        buf = io.BytesIO()
        sf.write(buf, 0.3 * np.sin(2 * np.pi * 220 * np.arange(24000) / 48000), 48000, format="WAV")
        return buf.getvalue(), "audio/wav"


def wav_bytes(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    sf.write(
        buf,
        0.5 * np.sin(2 * np.pi * 440 * np.arange(int(48000 * seconds)) / 48000).astype("float32"),
        48000,
        format="WAV",
    )
    return buf.getvalue()


def t_generate_all() -> None:
    assert len(sfx.BUILTIN_IDS) == 14
    for sid in sfx.BUILTIN_IDS:
        x = sfx.generate(sid)
        assert (
            np.isfinite(x).all()
            and 0.5 <= len(x) / sfx.SR <= sfx.MAX_SECONDS
            and np.abs(x).max() <= sfx.PEAK + 1e-3
        ), sid
        assert np.array_equal(x, sfx.generate(sid)), f"{sid} không ổn định giữa hai lần sinh"


def t_split_tags() -> None:
    got = sfx.split("Trời tối. [Tiếng  sấm] Hắn [rain falling][nghỉ 1s] đi [witch voice]")
    assert [k for k, _ in got] == ["text", "sfx", "text", "sfx", "text"], got
    assert (
        got[1][1] == "sam" and got[3][1] == "mua" and got[4][1] == "[nghỉ 1s] đi [witch voice]"
    ), got
    assert not sfx.has_sfx("[witch voice] [cười]") and sfx.has_sfx("a [VỖ  TAY] b")


def t_render_fake_engine() -> None:
    e = FakeEngine()
    text = "Trời tối sầm. [tiếng sấm] Có tiếng [knocking on door] ngoài cửa. [nghỉ 1s] [witch voice] hết."
    wav = asyncio.run(dialogue.render_text(e, "v", text, 0, True, 0, None, []))
    assert [k for k, _ in dialogue.make_plan(e, text, True)] == [
        "text",
        "sfx",
        "text",
        "sfx",
        "text",
        "pause",
        "text",
    ]
    assert e.calls[-1] == "[witch voice] hết.", e.calls  # thẻ lạ vẫn tới engine, không bị xoá
    assert (
        len(wav) / sfx.SR > 1.0 + len(sfx.audio("sam")) / sfx.SR + len(sfx.audio("go-cua")) / sfx.SR
    )
    n = asyncio.run(narrate.render("Đêm tối. [rain falling] Hắn đi.", (e, "a"), None, 0, True))
    assert len(n) / sfx.SR > len(sfx.audio("mua")) / sfx.SR
    # văn bản không có thẻ mới: khoá cache không đổi
    assert dialogue.plan_key(dialogue.make_plan(e, "A [nghỉ 2s] B", True)) == "A\x1f[nghỉ 2s]\x1fB"
    assert "[sfx mua-v1]" in dialogue.plan_key(dialogue.make_plan(e, "[rain]", True))


def t_api() -> None:
    cat = client.get(f"{B}/api/sfx").json()
    assert len(cat) >= 14 and cat[0]["id"] == "mua" and cat[0]["label"] == "[tiếng mưa]", cat[:1]
    r = client.get(f"{B}/api/sfx/mua/audio")
    assert (
        r.status_code == 200
        and r.headers["content-type"] == "audio/wav"
        and r.content[:4] == b"RIFF"
    )
    assert client.get(f"{B}/api/sfx/khong-co/audio").status_code == 404
    assert client.get(f"{B}/api/sfx/..%2F..%2Fetc%2Fpasswd/audio").status_code == 404
    up = {"file": ("a.wav", wav_bytes(), "audio/wav")}
    made = client.post(f"{B}/api/sfx", data={"name": "Còi xe smoke"}, files=up)
    assert made.status_code == 200 and made.json()["source"] == "user", made.text
    sid = made.json()["id"]
    for bad in ("tiếng mưa", "cười", "RAIN", "Còi  xe smoke", "nghỉ 3s", "a[b]"):
        r = client.post(f"{B}/api/sfx", data={"name": bad}, files=up)
        assert r.status_code == 400 and r.json()["error"], (bad, r.status_code, r.text)
    r = client.post(
        f"{B}/api/sfx",
        data={"name": "File hỏng"},
        files={"file": ("x.bin", b"khong phai audio", "application/octet-stream")},
    )
    assert r.status_code == 400, r.text
    out = client.post(
        f"{B}/api/tts",
        data={"text": "[tiếng sấm] [còi xe smoke]", "engine": "vieneu", "voice": "x"},
    )
    assert out.status_code == 200 and len(out.content) > 48000 * 2 * 4, (
        out.status_code
    )  # chỉ thẻ hiệu ứng: không gọi engine
    assert client.delete(f"{B}/api/sfx/{sid}").status_code == 200
    assert client.delete(f"{B}/api/sfx/{sid}").status_code == 404
    assert client.delete(f"{B}/api/sfx/mua").status_code == 404
    assert not any(c["id"] == sid for c in client.get(f"{B}/api/sfx").json())


for name, fn in [
    (
        "sfx: sinh đủ 14 âm có sẵn (hữu hạn, 0.5–15 s, peak ≤ 0.9, lần nào cũng giống nhau)",
        t_generate_all,
    ),
    ("sfx: tách thẻ (hoa thường, co giãn khoảng trắng, bí danh); thẻ lạ vẫn là chữ", t_split_tags),
    (
        "sfx: render_text / narrate với engine giả; khoá cache văn bản cũ không đổi",
        t_render_fake_engine,
    ),
    (
        "API: /api/sfx (danh sách, nghe, thêm, trùng tên → 400, id lạ / ../ → 404, xoá, /api/tts chỉ có thẻ)",
        t_api,
    ),
]:
    check(name, fn)

sys.exit(1 if fails else 0)
