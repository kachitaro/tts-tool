"""Sách nói: nhập truyện, chương, dàn giọng, từ điển, đọc thử, hàng đợi tạo audio, xuất file."""

from __future__ import annotations

import json

import anyio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from giongviet import settings
from giongviet.api.common import check_lib_voice, get_engine
from giongviet.books import cast, exporter, narrate
from giongviet.books import jobs as bookq
from giongviet.books import store as books
from giongviet.engines.registry import ENGINES
from giongviet.speech import dialogue, lexicon

router = APIRouter()


def default_book_voice() -> dict:
    """Giọng kể mặc định của truyện mới: giọng mặc định người dùng đã chọn (nếu còn dùng được), không thì VieNeu (Hải Đăng), không thì edge."""
    chosen = settings.load()["default_voice"]
    if chosen:
        e = ENGINES.get(chosen["engine"])
        try:
            if e and e.installed():
                check_lib_voice(e, chosen["voice"])
                return dict(chosen)
        except HTTPException:
            pass  # giọng đã bị xoá / không còn dùng được: quay về mặc định của tool
    v = ENGINES.get("vieneu")
    if v and v.installed():
        return {"engine": "vieneu", "voice": "Hải Đăng"}
    return {"engine": "edge", "voice": "vi-VN-HoaiMyNeural"}


def book_or_404(book_id: str) -> dict:
    try:
        return books.get(book_id)
    except books.NotFound:
        raise HTTPException(404, "Không tìm thấy truyện.") from None


def busy_check(book_id: str) -> None:
    """Tách lại chương / xoá truyện xoá audio đã dựng: không làm khi chương của truyện này đang chạy; chương đang chờ thì bỏ khỏi hàng đợi."""
    if bookq.Q.running and bookq.Q.running["book"] == book_id:
        raise HTTPException(
            409,
            "Đang tạo audio cho truyện này. Hãy huỷ hàng đợi (hoặc đợi chương đang chạy xong) rồi thử lại.",
        )
    bookq.Q.forget_book(book_id)


class SplitIn(BaseModel):
    regex: str | None = None
    mode: str | None = None
    ops: list[dict] | None = None
    selector: str | None = None
    clean: dict | None = None
    exceptions: list[dict] | None = None


class BookPatch(BaseModel):
    title: str | None = None
    author: str | None = None
    voice: dict | None = None
    speed: int | None = None
    normalize: bool | None = None
    read_title: bool | None = None
    paragraph_pause_s: float | None = None
    title_pause_s: float | None = None
    split: dict | None = None
    clean: dict | None = None
    exceptions: list[dict] | None = None
    lexicon: list[dict] | None = None
    dialogue_voice: dict | None = None
    cast: dict | None = None  # dàn giọng nhân vật (cast.py): {"enabled", "roles": [...]}
    dismiss_trial: bool | None = None  # "Để sau" trên banner tạo thử: bỏ book["trial"]


async def build_book(book_id: str, book: dict, body: SplitIn) -> tuple[dict, dict]:
    """Tách chương + làm sạch với cài đặt đã lưu, ghi đè bởi body (xem trước hoặc xác nhận). Trả (built, settings)."""
    try:
        settings = books.overrides(book, body.model_dump())
        built = await anyio.to_thread.run_sync(
            lambda: books.build(
                books.load_docs(book_id, settings["split"].get("selector")), settings
            )
        )
    except books.BookError as ex:
        raise HTTPException(400, str(ex)) from ex
    return built, settings


@router.get("/api/books")
def books_list():
    return books.list_books()


@router.post("/api/books/import")
async def books_import(
    files: list[UploadFile] = File(...), title: str = Form(""), author: str = Form("")
):
    data = []
    for f in files:
        raw = await f.read(books.MAX_FILE_BYTES + 1)
        if len(raw) > books.MAX_FILE_BYTES:
            raise HTTPException(
                413, f"'{f.filename}' quá lớn (tối đa {books.MAX_FILE_BYTES // 2**20} MB)."
            )
        data.append((f.filename or "file.txt", raw))
    try:
        return await anyio.to_thread.run_sync(
            books.import_files, data, title, author, default_book_voice()
        )
    except books.BookError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.get("/api/masked-words")
def masked_words_get():
    return books.load_masked()


class MaskedIn(BaseModel):
    masked: str
    correct: str


@router.post("/api/masked-words")
def masked_words_add(body: MaskedIn):
    """Thêm từ vào từ điển từ bị che (từ màn xem trước: "từ đúng là…"). 400 nếu từ đúng không khớp từ bị che."""
    try:
        return books.add_masked_word(body.masked, body.correct)
    except books.BookError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.get("/api/books/{book_id}")
def books_get(book_id: str):
    book = book_or_404(book_id)
    return {
        **book,
        "chapters_list": books.list_chapters(book_id) if book["status"] == "ready" else [],
        "rules_catalog": [{"name": n, "label": label} for n, label in books.RULES],
        "default_regex": books.DEFAULT_SPLIT_REGEX,
    }


@router.patch("/api/books/{book_id}")
def books_patch(book_id: str, body: BookPatch):
    book = book_or_404(book_id)
    try:
        if body.title is not None:
            if not body.title.strip():
                raise books.BookError("Tên truyện không được để trống.")
            book["title"] = body.title.strip()[:200]
        if body.author is not None:
            book["author"] = body.author.strip()[:200]
        if body.voice is not None:
            e = get_engine(str(body.voice.get("engine", "")))
            check_lib_voice(e, str(body.voice.get("voice", "")))
            book["voice"] = {"engine": e.id, "voice": str(body.voice["voice"])}
        if body.speed is not None:
            book["speed"] = max(-50, min(200, body.speed))
        if body.normalize is not None:
            book["normalize"] = body.normalize
        if body.read_title is not None:
            book["read_title"] = body.read_title
        if body.paragraph_pause_s is not None:
            book["paragraph_pause_s"] = books.validate_pause(
                body.paragraph_pause_s, "Nghỉ giữa các đoạn văn", 3
            )
        if body.title_pause_s is not None:
            book["title_pause_s"] = books.validate_pause(body.title_pause_s, "Nghỉ sau tiêu đề", 5)
        if body.split is not None:
            sp = {
                **book["split"],
                **{
                    k: v for k, v in body.split.items() if k in ("regex", "mode", "ops", "selector")
                },
            }
            books.compile_split(sp["regex"])
            if "selector" in sp:
                sp["selector"] = books.validate_selector(sp["selector"])
            if sp["mode"] not in ("regex", "per_file"):
                raise books.BookError("mode phải là 'regex' hoặc 'per_file'.")
            book["split"] = sp
        if body.clean is not None:
            book["clean"] = books.validate_clean(body.clean)
        if body.exceptions is not None:
            book["exceptions"] = books.validate_exceptions(body.exceptions)
        if body.lexicon is not None:
            book["lexicon"] = lexicon.validate(body.lexicon)
        if body.dismiss_trial:
            book.pop("trial", None)
        if body.cast is not None:
            book["cast"] = checked_cast(body.cast)
        if body.dialogue_voice is not None:
            dv = body.dialogue_voice
            e = get_engine(str(dv.get("engine", "")))
            check_lib_voice(e, str(dv.get("voice", "")))
            book["dialogue_voice"] = {
                "enabled": bool(dv.get("enabled")),
                "engine": e.id,
                "voice": str(dv["voice"]),
            }
    except (books.BookError, lexicon.LexiconError, cast.CastError) as ex:
        raise HTTPException(400, str(ex)) from ex
    books.save(book)
    return book


@router.delete("/api/books/{book_id}")
def books_delete(book_id: str):
    book_or_404(book_id)
    busy_check(book_id)
    books.delete(book_id)
    return {"deleted": book_id}


@router.post("/api/books/{book_id}/preview")
async def books_preview(book_id: str, body: SplitIn | None = None):
    """Xem trước danh sách chương với cài đặt hiện tại (có thể ghi đè bằng body); không ghi gì ra đĩa."""
    built, _ = await build_book(book_id, book_or_404(book_id), body or SplitIn())
    chapters = books.summarize(built)
    return {
        "chapters": chapters,
        "stats": built["stats"],
        "rules": built["rules"],
        "dropped": built["dropped"],
        "masked_unknown": built["masked_unknown"],
        "warnings": built["warnings"],
        "total_chars": sum(c["chars"] for c in chapters),
    }


@router.post("/api/books/{book_id}/chapters")
async def books_confirm(book_id: str, body: SplitIn | None = None):
    """Xác nhận tách chương: ghi chapters/ (thay chương cũ) và lưu cài đặt tách/làm sạch."""
    book = book_or_404(book_id)
    built, settings = await build_book(book_id, book, body or SplitIn())
    busy_check(book_id)
    try:
        return books.confirm(book_id, built, settings)
    except books.BookError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.get("/api/books/{book_id}/chapters")
def books_chapters(book_id: str):
    book = book_or_404(book_id)
    chs = books.list_chapters(book_id)
    try:  # audio đã dựng bằng cấu hình cũ (đổi giọng, tốc độ, từ điển…) → stale
        narr, dlg = book_voices(book)
        sig = bookq.signature(book, narr, dlg, lexicon.load_global())
    except HTTPException:
        sig = None
    for c in chs:
        c["stale"] = bool(sig and c.get("status") == "done" and c.get("sig") != sig)
    return chs


@router.get("/api/books/{book_id}/chapters/{n}")
def books_chapter(book_id: str, n: int):
    book = book_or_404(book_id)
    try:
        meta, body = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.") from None
    return {**meta, "text": body, "reading_text": books.reading_text(book, meta, body)}


def _one_voice(v: dict) -> tuple:
    e = get_engine(v["engine"])
    check_lib_voice(e, v["voice"])
    return e, v["voice"]


def checked_cast(spec: dict) -> dict:
    """Chuẩn hoá dàn giọng + kiểm tra từng giọng (engine đã cài, giọng thư viện còn tồn tại). Raise HTTPException / CastError."""
    c = cast.validate(spec)
    for r in c["roles"]:
        for v in r["voices"]:
            e = get_engine(v["engine"])
            check_lib_voice(e, v["voice"])
            v["engine"] = e.id
    return c


def book_voices(book: dict):
    """(giọng kể, giọng lời thoại hoặc None) dạng (engine, voice); kiểm tra engine + giọng thư viện.
    Truyện bật dàn giọng nhân vật (book["cast"]) thì phần thứ hai là một cast.Cast: thoại nhận ra vai dùng giọng của vai,
    còn lại dùng giọng lời thoại chung (nếu bật) hoặc giọng kể."""
    dv = book.get("dialogue_voice") or {}
    narr = _one_voice(book["voice"])
    default = _one_voice(dv) if dv.get("enabled") else None
    c = book.get("cast") or {}
    if c.get("enabled") and c.get("roles"):
        voices = {r["id"]: [_one_voice(v) for v in r["voices"]] for r in c["roles"]}
        return narr, cast.Cast(cast.effective_roles(c)[0], voices, default)
    return narr, default


async def speak_book(book: dict, text: str, use_lexicon: bool = True) -> tuple[bytes, float]:
    narr, dlg = book_voices(book)
    try:
        wav = await narrate.render(
            text,
            narr,
            dlg,
            book["speed"],
            book["normalize"],
            book.get("lexicon") if use_lexicon else None,
            lexicon.load_global() if use_lexicon else None,
        )
        data, _ = await anyio.to_thread.run_sync(dialogue.encode_outputs, wav, False)
    except Exception as ex:
        raise HTTPException(narr[0].error_status, f"{narr[0].name} lỗi: {ex}") from ex
    return data, len(wav) / dialogue.SR


@router.get("/api/books/{book_id}/chapters/{n}/sample")
async def books_sample(book_id: str, n: int, use_lexicon: bool = True):
    """Nghe thử đầu chương (~300 ký tự, có đọc tiêu đề) bằng giọng + từ điển + giọng lời thoại của truyện. Chạy ngay
    (không qua hàng đợi) nhưng vào khoá model trước việc nền. Bản dài hơn: POST …/trial."""
    book = book_or_404(book_id)
    try:
        meta, body = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.") from None
    text = narrate.join_paras(books.excerpt_paras(books.paragraphs(book, meta, body), 300))
    data, seconds = await speak_book(book, text, use_lexicon)
    return Response(
        data,
        media_type="audio/wav",
        headers={"X-Sample-Seconds": f"{seconds:.1f}", "X-Sample-Chars": str(len(text))},
    )


class ParseCharactersIn(BaseModel):
    text: str


@router.post("/api/cast/parse-characters")
def cast_parse_characters(body: ParseCharactersIn):
    """Đọc nhiều dòng "Tên - giới tính - tuổi" → {characters, errors}; lỗi theo từng dòng (thiếu giới tính / tuổi không được đoán).
    Không lưu gì: giao diện cho người dùng xem rồi mới lưu cùng dàn giọng (PATCH cast)."""
    if len(body.text) > 50_000:
        raise HTTPException(400, "Danh sách quá dài.")
    try:
        chars, errors = cast.parse_characters(body.text)
    except cast.CastError as ex:
        raise HTTPException(400, str(ex)) from ex
    return {"characters": chars, "errors": errors}


class CastPreviewIn(BaseModel):
    cast: dict | None = None  # bản đang sửa (chưa lưu); không gửi = dàn giọng đã lưu của truyện
    chapters: list[int] | None = None  # mặc định 5 chương đầu


@router.post("/api/books/{book_id}/cast/preview")
async def books_cast_preview(book_id: str, body: CastPreviewIn | None = None):
    """Xem thử luật gán vai trên một vài chương: mỗi vai có bao nhiêu câu thoại + vài ví dụ (kèm phần dẫn), và số câu thoại chưa nhận ra
    vai. Chạy đúng như lúc dựng audio (từ điển trước, rồi tách thoại), không tạo audio, không cần giọng còn dùng được."""
    body = body or CastPreviewIn()
    book = book_or_404(book_id)
    if book["status"] != "ready":
        raise HTTPException(400, "Hãy tách chương trước.")
    try:
        spec = cast.validate(
            body.cast if body.cast is not None else (book.get("cast") or {"roles": []})
        )
    except cast.CastError as ex:
        raise HTTPException(400, str(ex)) from ex
    roles, lost = cast.effective_roles(spec)
    ns = body.chapters or [c["n"] for c in books.list_chapters(book_id)[:5]]
    if len(ns) > 30:
        raise HTTPException(400, "Xem thử tối đa 30 chương một lần.")
    glex = lexicon.load_global()

    def work() -> dict:
        per: dict[str | None, dict] = {
            r["id"]: {"id": r["id"], "name": r["name"], "lines": 0, "samples": []}
            for r in spec["roles"]
        }
        per[None] = {"id": None, "name": "Chưa nhận ra vai", "lines": 0, "samples": []}
        for n in ns:
            try:
                meta, text = books.chapter_text(book_id, n)
            except books.NotFound:
                raise HTTPException(404, f"Không có chương {n}.") from None
            txt = lexicon.apply(
                narrate.join_paras(books.paragraphs(book, meta, text)), book.get("lexicon"), glex
            )
            for rid, line, ctx in cast.analyze(narrate.split_text(txt), roles):
                e = per[rid]
                e["lines"] += 1
                if len(e["samples"]) < 3:
                    e["samples"].append({"chapter": n, "text": line[:160], "tag": ctx[:160]})
        return {
            "chapters": ns,
            "roles": [per[r["id"]] for r in spec["roles"]],
            "unmatched": per[None],
            "dialogue_lines": sum(e["lines"] for e in per.values()),
            "unassigned_characters": [c["name"] for c in lost],
        }

    return await anyio.to_thread.run_sync(work)


class SpeakIn(BaseModel):
    text: str
    use_lexicon: bool = True


@router.post("/api/books/{book_id}/speak")
async def books_speak(book_id: str, body: SpeakIn):
    """Đọc một đoạn văn bản bất kỳ bằng giọng của truyện (nghe thử câu ví dụ của gợi ý từ điển)."""
    text = body.text.strip()
    if not text or len(text) > 2000:
        raise HTTPException(400, "Văn bản phải từ 1 đến 2000 ký tự.")
    data, seconds = await speak_book(book_or_404(book_id), text, body.use_lexicon)
    return Response(data, media_type="audio/wav", headers={"X-Sample-Seconds": f"{seconds:.1f}"})


@router.post("/api/books/{book_id}/lexicon/apply")
def books_lexicon_apply(book_id: str, body: SpeakIn):
    """Văn bản sau khi qua từ điển của truyện + toàn cục (để kiểm tra; chưa qua chuẩn hoá và tách lời thoại)."""
    book = book_or_404(book_id)
    return {"text": lexicon.apply(body.text, book.get("lexicon"), lexicon.load_global())}


@router.get("/api/books/{book_id}/suggest")
async def books_suggest(book_id: str, min_count: int = 3, limit: int = 200):
    """Gợi ý tên riêng: cụm viết hoa 2–4 tiếng KHÔNG đứng đầu câu, lặp ≥ min_count lần (bỏ cụm đã có trong từ điển)."""
    book = book_or_404(book_id)
    if book["status"] != "ready":
        raise HTTPException(400, "Hãy tách chương trước.")
    known = {e["match"] for e in (book.get("lexicon") or []) + lexicon.load_global()}
    terms = await anyio.to_thread.run_sync(
        lambda: lexicon.suggest_terms(
            books.iter_chapters(book_id), known, max(1, min_count), max(1, min(limit, 1000))
        )
    )
    return {
        "terms": [
            {
                "phrase": t.phrase,
                "count": t.count,
                "chapter": t.chapter,
                "example": t.example,
                "parent": t.parent,
            }
            for t in terms
        ]
    }


@router.get("/api/lexicon")
def lexicon_get():
    return lexicon.load_global()


@router.put("/api/lexicon")
def lexicon_put(entries: list[dict]):
    try:
        return lexicon.save_global(entries)
    except lexicon.LexiconError as ex:
        raise HTTPException(400, str(ex)) from ex


class TrialIn(BaseModel):
    chars: int = 900
    offset: float = 0.0


@router.post("/api/books/{book_id}/chapters/{n}/trial")
async def books_trial(book_id: str, n: int, body: TrialIn | None = None):
    """ "Đọc thử 1 phút": xếp một đoạn ~900 ký tự vào hàng đợi ưu tiên cao nhất (chen vào giữa hai mảnh của chương đang chạy).
    offset 0..1 là vị trí bắt đầu trong chương (0 = đầu chương, có đọc tiêu đề). Hỏi tiến độ: GET /api/trials/{id}."""
    body = body or TrialIn()
    book = book_or_404(book_id)
    if not 50 <= body.chars <= 3000 or not 0 <= body.offset <= 1:
        raise HTTPException(400, "chars phải từ 50 đến 3000 và offset từ 0 đến 1.")
    try:
        meta, text = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.") from None
    narr, dlg = book_voices(book)
    excerpt = narrate.join_paras(
        books.excerpt_paras(
            books.paragraphs(book, meta, text, title=body.offset == 0), body.chars, body.offset
        )
    )
    try:
        t = bookq.Q.submit_trial(book, n, excerpt, narr, dlg)
    except (bookq.QueueError, ValueError) as ex:
        raise HTTPException(400, str(ex)) from ex
    return {"id": t.id, "total": t.total, "chars": len(excerpt)}


def trial_or_404(tid: str) -> bookq.Trial:
    t = bookq.Q.trials.get(tid)
    if t is None:
        raise HTTPException(404, "Không tìm thấy bản đọc thử (đã hết hạn?).")
    return t


@router.get("/api/trials/{tid}")
def trial_status(tid: str):
    t = trial_or_404(tid)
    return {
        "id": t.id,
        "status": t.status,
        "done": t.done,
        "total": t.total,
        "seconds": round(t.seconds, 1),
        "error": t.error,
    }


@router.get("/api/trials/{tid}/audio")
def trial_audio(tid: str):
    t = trial_or_404(tid)
    if t.status != "done":
        raise HTTPException(409, "Bản đọc thử chưa xong.")
    return Response(t.wav, media_type="audio/wav")


def queue_state(book_id: str | None = None) -> dict:
    if book_id is None:
        return bookq.Q.status()
    book = book_or_404(book_id)
    out = bookq.Q.book_status(book_id, book["voice"]["engine"])
    out["exports"] = exporter.list_files(book_id)
    out["trial"] = book.get(
        "trial"
    )  # {limit, done_at} khi truyện đang ở giai đoạn "tạo thử N chương"
    n, size = books.purgeable(book_id)
    out["purgeable"] = {"chapters": n, "bytes": size}
    try:
        out["bench"] = json.loads(bookq.BENCH_PATH.read_text(encoding="utf-8")).get("vieneu")
    except OSError, ValueError:
        out["bench"] = None
    return out


@router.get("/api/queue")
def queue_get(book: str | None = None):
    return queue_state(book)


class RunIn(BaseModel):
    chapters: list[int] | None = None  # None = mọi chương chưa xong của truyện
    limit: int | None = None  # chỉ lấy N chương đầu trong danh sách trên ("Chạy thử 5 chương đầu")
    regenerate: bool = False  # xoá audio cũ và dựng lại bằng model (bỏ qua cache)
    stale_only: bool = False  # chỉ chương đã dựng bằng cấu hình cũ (kèm regenerate)
    trial: bool = (
        False  # "tạo thử N chương" (N = limit): ghi book["trial"], xong thì banner "Tạo tiếp"
    )


@router.post("/api/books/{book_id}/queue/run")
def queue_run(book_id: str, body: RunIn | None = None):
    body = body or RunIn()
    book = book_or_404(book_id)
    if book["status"] != "ready":
        raise HTTPException(400, "Hãy tách chương trước.")
    book_voices(book)  # báo lỗi giọng (thiếu engine / giọng đã xoá) ngay thay vì làm mọi chương lỗi
    chs = books.list_chapters(book_id)
    if body.chapters is not None:
        ns = body.chapters
    elif body.stale_only:
        stale = {c["n"] for c in books_chapters(book_id) if c["stale"]}
        ns = [c["n"] for c in chs if c["n"] in stale]
    else:  # mặc định: chương chưa xong; regenerate không kèm danh sách: dựng lại tất cả
        ns = [c["n"] for c in chs if body.regenerate or c.get("status") not in ("done", "exported")]
    if body.limit is not None:
        ns = ns[: max(0, body.limit)]
    if not ns:
        raise HTTPException(400, "Không có chương nào cần tạo.")
    if body.trial and body.limit is None:
        raise HTTPException(400, "Tạo thử cần số chương (limit).")
    try:
        res = bookq.Q.enqueue(book_id, ns, regenerate=body.regenerate)
    except bookq.QueueError as ex:
        raise HTTPException(400, str(ex)) from ex
    if body.trial:
        book["trial"] = {"limit": len(ns), "done_at": None}
    elif (
        body.chapters is None and not body.stale_only
    ):  # "Tạo tiếp" / tạo cả truyện: hết giai đoạn thử
        book.pop("trial", None)
    books.save(book)
    return {**res, **queue_state(book_id)}


class FocusIn(BaseModel):
    n: int


@router.post("/api/books/{book_id}/queue/focus")
def queue_focus(book_id: str, body: FocusIn):
    """Chương đang mở trên giao diện: nếu đang chờ trong hàng đợi thì chạy trước."""
    book_or_404(book_id)
    return {"moved": bookq.Q.focus(book_id, body.n)}


@router.post("/api/queue/pause")
def queue_pause():
    bookq.Q.pause()
    return bookq.Q.status()


@router.post("/api/queue/resume")
def queue_resume():
    bookq.Q.resume()
    return bookq.Q.status()


class CancelIn(BaseModel):
    book: str | None = None


@router.post("/api/queue/cancel")
def queue_cancel(body: CancelIn | None = None):
    n = bookq.Q.cancel(body.book if body else None)
    return {"cancelled": n, **bookq.Q.status()}


class QueueSettings(BaseModel):
    inhibit_sleep: bool


@router.post("/api/queue/settings")
def queue_settings(body: QueueSettings):
    bookq.Q.set_inhibit(body.inhibit_sleep)
    return bookq.Q.status()


@router.get("/api/books/{book_id}/disk")
def books_disk(book_id: str):
    """Dung lượng đã dùng của truyện (byte): tổng, audio gốc (FLAC + đoạn dở), file xuất, còn lại."""
    book_or_404(book_id)
    return books.disk_usage(book_id)


@router.post("/api/books/{book_id}/audio/purge-exported")
def books_purge_exported(book_id: str):
    """Xoá FLAC của chương đã xuất. Chương chuyển sang "exported": không nghe lại / xuất lại được nữa cho tới khi Tạo lại."""
    book_or_404(book_id)
    n, freed = books.purge_exported(book_id)
    return {"deleted": n, "freed": freed, **books.disk_usage(book_id)}


@router.get("/api/books/{book_id}/chapters/{n}/audio.mp3")
async def books_chapter_audio(book_id: str, n: int, kbps: int = 64):
    """MP3 của chương đã dựng (nghe lại trong trình duyệt / tải về)."""
    book = book_or_404(book_id)
    try:
        meta, _ = books.chapter_text(book_id, n)
    except books.NotFound:
        raise HTTPException(404, "Không có chương này.") from None
    if meta.get("status") != "done" or not books.chapter_audio(book_id, n).is_file():
        raise HTTPException(409, "Chương này chưa được tạo audio.")
    try:
        path = await anyio.to_thread.run_sync(
            exporter.chapter_mp3, book, meta, kbps, book["chapters"]["count"]
        )
    except exporter.ExportError as ex:
        raise HTTPException(400, str(ex)) from ex
    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename=f"{n:04d} - {exporter.safe_name(meta.get('title') or str(n))}.mp3",
    )


class ExportIn(BaseModel):
    kind: str = "mp3zip"  # mp3zip | m4b
    chapters: list[int] | None = None  # None = mọi chương đã xong
    kbps: int = 64  # MP3: 64 / 80 / 96 (m4b luôn AAC 64k)


@router.post("/api/books/{book_id}/export")
async def books_export(book_id: str, body: ExportIn):
    book = book_or_404(book_id)
    try:
        j = exporter.start(book, body.kind, body.chapters, body.kbps)
    except exporter.ExportError as ex:
        raise HTTPException(400, str(ex)) from ex
    return {"id": j.id, "total": j.total}


@router.get("/api/exports/{jid}")
def export_status(jid: str):
    j = exporter.JOBS.get(jid)
    if j is None:
        raise HTTPException(404, "Không tìm thấy việc xuất (đã hết hạn?).")
    return {
        "id": j.id,
        "book": j.book,
        "kind": j.kind,
        "status": j.status,
        "done": j.done,
        "total": j.total,
        "chapters": j.chapters,
        "file": j.file,
        "size": j.size,
        "error": j.error,
    }


@router.get("/api/books/{book_id}/export/{name}")
def books_export_file(book_id: str, name: str):
    book_or_404(book_id)
    try:
        path = exporter.file_path(book_id, name)
    except exporter.ExportError as ex:
        raise HTTPException(404, str(ex)) from ex
    return FileResponse(
        path,
        filename=path.name,
        media_type="audio/mp4" if path.suffix == ".m4b" else "application/zip",
    )
