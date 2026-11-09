"""Dàn giọng nhân vật: gán từng câu thoại cho một vai theo tên nhân vật / từ khoá trong phần dẫn.

Mỗi truyện có `book["cast"] = {"enabled": bool, "roles": [Vai]}`, Vai = {"id", "name", "voices": [{"engine","voice"}],
"names": [tên nhân vật], "keywords": [từ khoá chỉ loại người: "lão giả", "thiếu nữ"…]}.

Cách gán (narrate.split_line đã tách sẵn từng dòng thành đoạn kể "narr" / thoại "dlg"): với mỗi câu thoại, xét phần dẫn kề nó
trong cùng dòng, mỗi bên chỉ lấy MỘT câu của phần dẫn (bên trước: sau dấu kết câu cuối cùng; bên sau: tới dấu kết câu đầu tiên):
  – dẫn đứng trước ("Trần Bình An nói: “…”") hoặc đứng sau ("– Đi đâu? – lão giả hỏi.");
  – nếu cả hai bên đều khớp thì lấy bên trước khi nó kết thúc bằng ":" hoặc ",", ngược lại lấy bên sau;
  – cùng một phần dẫn khớp nhiều vai: tên nhân vật thắng từ khoá, cụm dài thắng cụm ngắn, trùng thì vai đứng trước thắng.
Không nhận ra vai thì câu thoại thuộc "thoại chung" (giọng lời thoại của truyện, hoặc giọng kể nếu không bật).
Vai có nhiều giọng: mỗi TÊN nhân vật cố định một giọng, xoay vòng theo thứ tự tên trong danh sách; khớp bằng từ khoá thì dùng giọng đầu.
Không nhớ người nói giữa các dòng: dòng thoại không có phần dẫn nhận ra được sẽ về thoại chung.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_ROLES = 20
MAX_VOICES = 4
MAX_WORDS = 60  # số tên / từ khoá mỗi vai
MAX_WORD_LEN = 60
TAIL_CHARS = 80  # phần dẫn quá dài thì chỉ xét phần sát câu thoại
_END = re.compile(r"[.!?…]")
KIND_DEFAULT = (
    "dlg"  # kind của đoạn thoại không có vai; thoại có vai: "dlg:<role_id>:<chỉ số giọng>"
)


class CastError(ValueError):
    pass


def _words(raw: Any, what: str, role: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CastError(f"{what} của vai “{role}” phải là một danh sách.")
    out: list[str] = []
    for w in raw:
        w = " ".join(str(w).split())
        if not w:
            continue
        if len(w) > MAX_WORD_LEN:
            raise CastError(f"“{w[:20]}…” quá dài (tối đa {MAX_WORD_LEN} ký tự).")
        if w.lower() not in (x.lower() for x in out):
            out.append(w)
    if len(out) > MAX_WORDS:
        raise CastError(f"Vai “{role}” có quá nhiều {what.lower()} (tối đa {MAX_WORDS}).")
    return out


def validate(spec: Any) -> dict:
    """Chuẩn hoá + kiểm tra cấu trúc (chưa kiểm giọng có tồn tại: server làm). Raise CastError."""
    if not isinstance(spec, dict):
        raise CastError("Dàn giọng không hợp lệ.")
    roles_in = spec.get("roles") or []
    if not isinstance(roles_in, list):
        raise CastError("Danh sách vai không hợp lệ.")
    if len(roles_in) > MAX_ROLES:
        raise CastError(f"Tối đa {MAX_ROLES} vai.")
    roles: list[dict] = []
    used: set[str] = set()
    for i, r in enumerate(roles_in, 1):
        if not isinstance(r, dict):
            raise CastError("Vai không hợp lệ.")
        name = " ".join(str(r.get("name", "")).split())
        if not name:
            raise CastError(f"Vai số {i} chưa có tên.")
        if len(name) > MAX_WORD_LEN:
            raise CastError(f"Tên vai “{name[:20]}…” quá dài.")
        rid = str(r.get("id") or "")
        if not re.fullmatch(r"[a-z0-9]{1,12}", rid) or rid in used:
            rid = next(f"v{k}" for k in range(1, 1000) if f"v{k}" not in used)
        used.add(rid)
        voices = r.get("voices") or []
        if not isinstance(voices, list) or not 1 <= len(voices) <= MAX_VOICES:
            raise CastError(f"Vai “{name}” cần từ 1 đến {MAX_VOICES} giọng.")
        vs = []
        for v in voices:
            if (
                not isinstance(v, dict)
                or not str(v.get("engine", ""))
                or not str(v.get("voice", ""))
            ):
                raise CastError(f"Giọng của vai “{name}” không hợp lệ.")
            vs.append({"engine": str(v["engine"]), "voice": str(v["voice"])})
        roles.append(
            {
                "id": rid,
                "name": name,
                "voices": vs,
                "names": _words(r.get("names"), "Tên nhân vật", name),
                "keywords": _words(r.get("keywords"), "Từ khoá", name),
            }
        )
    return {"enabled": bool(spec.get("enabled")), "roles": roles}


@dataclass(frozen=True)
class _Pat:
    role: str
    is_name: bool
    idx: int  # vị trí của tên trong danh sách tên của vai (chọn giọng); 0 với từ khoá
    length: int
    rx: re.Pattern[str]


def _compile(word: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(p) for p in word.split())
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def compile_roles(roles: list[dict]) -> list[_Pat]:
    pats: list[_Pat] = []
    for r in roles:
        for i, w in enumerate(r.get("names") or []):
            pats.append(_Pat(r["id"], True, i, len(w), _compile(w)))
        for w in r.get("keywords") or []:
            pats.append(_Pat(r["id"], False, 0, len(w), _compile(w)))
    return pats


def _best(text: str, pats: list[_Pat]) -> tuple[str, int] | None:
    """(role id, chỉ số tên) của mẫu tốt nhất khớp trong text, hoặc None."""
    best: tuple[tuple[int, int], _Pat] | None = None
    for p in pats:
        if p.rx.search(text):
            key = (1 if p.is_name else 0, p.length)
            if best is None or key > best[0]:
                best = (key, p)
    return (best[1].role, best[1].idx) if best else None


def _before(text: str) -> str:
    t = text.rstrip()
    m = list(_END.finditer(t))
    return (t[m[-1].end() :] if m else t)[-TAIL_CHARS:]


def _after(text: str) -> str:
    t = text.lstrip()
    m = _END.search(t)
    return t[: m.start()][:TAIL_CHARS] if m else t[:TAIL_CHARS]


def tag_line(
    segs: list[tuple[str, str]], pats: list[_Pat], roles_voices: dict[str, int]
) -> list[tuple[str, str]]:
    """Đổi kind "dlg" thành "dlg:<vai>:<giọng>" cho các câu thoại nhận ra được vai. roles_voices: id vai → số giọng."""
    out = list(segs)
    for i, (kind, _text) in enumerate(segs):
        if kind != "dlg":
            continue
        pre = segs[i - 1][1] if i > 0 and segs[i - 1][0] == "narr" else ""
        post = segs[i + 1][1] if i + 1 < len(segs) and segs[i + 1][0] == "narr" else ""
        mb, ma = (
            _best(_before(pre), pats) if pre else None,
            _best(_after(post), pats) if post else None,
        )
        if mb and ma:
            hit = mb if pre.rstrip().endswith((":", ",")) else ma
        else:
            hit = mb or ma
        if hit:
            rid, idx = hit
            n = max(1, roles_voices.get(rid, 1))
            out[i] = (f"{KIND_DEFAULT}:{rid}:{idx % n}", segs[i][1])
    return out


def role_of(kind: str) -> str | None:
    return kind.split(":")[1] if kind.startswith(KIND_DEFAULT + ":") else None


@dataclass
class Cast:
    """Dàn giọng đã giải quyết giọng thật, dùng khi dựng audio. `default` = (engine, voice) của thoại chung (None → giọng kể)."""

    roles: list[dict]
    voices: dict[str, list[tuple]]
    default: tuple | None = None
    _pats: list[_Pat] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._pats = compile_roles(self.roles)

    def tag(self, lines: list[list[tuple[str, str]]]) -> list[list[tuple[str, str]]]:
        counts = {rid: len(v) for rid, v in self.voices.items()}
        return [tag_line(segs, self._pats, counts) for segs in lines]

    def voice_for(self, kind: str, narr: tuple) -> tuple:
        if kind == "narr":
            return narr
        rid = role_of(kind)
        if rid is None or rid not in self.voices:
            return self.default or narr
        return self.voices[rid][int(kind.rsplit(":", 1)[1]) % len(self.voices[rid])]


def analyze(
    lines: list[list[tuple[str, str]]], roles: list[dict]
) -> list[tuple[str | None, str, str]]:
    """Dùng cho xem thử: mỗi câu thoại → (id vai hoặc None, câu thoại, phần dẫn kề nó)."""
    pats = compile_roles(roles)
    counts = {r["id"]: max(1, len(r.get("voices") or [1])) for r in roles}
    out: list[tuple[str | None, str, str]] = []
    for segs in lines:
        tagged = tag_line(segs, pats, counts)
        for i, (kind, text) in enumerate(tagged):
            if not kind.startswith(KIND_DEFAULT):
                continue
            ctx = " … ".join(
                t.strip() for j, (k, t) in enumerate(segs) if abs(j - i) == 1 and k == "narr"
            )
            out.append((role_of(kind), text, ctx))
    return out
