"""Hội thoại nhiều người đọc và dự án đã lưu: /api/dialogue*, /api/projects*."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from giongviet.api.common import MAX_CHARS, check_lib_voice, get_engine, voice_label
from giongviet.speech import dialogue

router = APIRouter()


class ScriptIn(BaseModel):
    script: str


class DialogueIn(BaseModel):
    script: str
    cast: dict[str, dict] = {}  # {"Lan": {"engine": "vieneu", "voice": "lib:giong-a"}, ...}
    speed: int = 0
    gap_ms: int = 350
    paragraph_gap_ms: int = 800
    normalize: bool = True


class LineRegenIn(BaseModel):
    seed: int | None = None


def parse_or_400(script: str) -> list:
    try:
        return dialogue.parse_script(script, MAX_CHARS)
    except dialogue.ScriptError as ex:
        raise HTTPException(400, str(ex)) from ex


def job_or_404(job_id: str):
    try:
        return dialogue.get_job(job_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy job (đã hết hạn hoặc sai id).") from None


@router.post("/api/dialogue/parse")
def dialogue_parse(req: ScriptIn):
    lines = parse_or_400(req.script)
    return {
        "speakers": dialogue.speakers_of(lines),
        "chars": len(req.script),
        "lines": [
            {"i": ln.i, "speaker": ln.speaker, "text": ln.text, "pause": ln.pause} for ln in lines
        ],
    }


@router.post("/api/dialogue")
async def dialogue_create(req: DialogueIn):
    lines = parse_or_400(req.script)
    if not lines:
        raise HTTPException(400, "Kịch bản trống.")
    cast = {dialogue.norm_name(k): v for k, v in req.cast.items()}
    names = dialogue.speakers_of(lines)
    missing = [
        n
        for n in names
        if not (cast.get(n) or {}).get("engine") or not (cast.get(n) or {}).get("voice")
    ]
    if missing:
        return JSONResponse(
            {"error": "Chưa gán giọng cho: " + ", ".join(missing), "missing": missing},
            status_code=400,
        )
    resolved, labels = {}, {}
    for n in names:
        e = get_engine(cast[n]["engine"])
        check_lib_voice(e, cast[n]["voice"])
        resolved[n] = (e, cast[n]["voice"])
        labels[n] = await voice_label(e, cast[n]["voice"])
    meta = {
        "script": req.script,
        "cast": {n: {**cast[n], "label": labels[n]} for n in names},
        "speed": req.speed,
        "gap_ms": req.gap_ms,
        "paragraph_gap_ms": req.paragraph_gap_ms,
        "normalize": req.normalize,
    }
    job = dialogue.create_job(
        lines,
        resolved,
        max(-50, min(200, req.speed)),
        max(0, min(5000, req.gap_ms)),
        max(0, min(10000, req.paragraph_gap_ms)),
        normalize=req.normalize,
        meta=meta,
    )
    return {"job_id": job.id, "total": len(lines)}


@router.get("/api/dialogue/{job_id}")
def dialogue_status(job_id: str):
    dialogue.purge()
    return dialogue.job_info(job_or_404(job_id))


@router.get("/api/dialogue/{job_id}/audio")
def dialogue_audio(job_id: str, fmt: str = "wav"):
    job = job_or_404(job_id)
    if job.status != "done":
        raise HTTPException(409, "Audio chưa sẵn sàng.")
    if fmt not in ("wav", "mp3") or (fmt == "mp3" and not job.has_mp3):
        raise HTTPException(404, "Không có định dạng này (MP3 cần ffmpeg).")
    return FileResponse(
        job.dir / f"out.{fmt}",
        media_type="audio/mpeg" if fmt == "mp3" else "audio/wav",
        filename=f"hoi-thoai.{fmt}",
    )


@router.get("/api/dialogue/{job_id}/line/{i}/audio")
def dialogue_line_audio(job_id: str, i: int):
    job = job_or_404(job_id)
    if not 0 <= i < len(job.lines) or job.states[i].status != "done":
        raise HTTPException(404, "Dòng này chưa có audio.")
    return FileResponse(dialogue.line_path(job, i), media_type="audio/wav")


@router.post("/api/dialogue/{job_id}/line/{i}")
async def dialogue_regen(job_id: str, i: int, req: LineRegenIn | None = None):
    job = job_or_404(job_id)
    if not 0 <= i < len(job.lines):
        raise HTTPException(404, "Không có dòng này.")
    try:
        await dialogue.regen_line(job, i, req.seed if req else None)
    except dialogue.Busy as ex:
        raise HTTPException(409, str(ex)) from ex
    return dialogue.job_info(job)


@router.get("/api/projects")
def projects_list():
    return dialogue.list_projects()


@router.post("/api/projects")
def projects_save(data: dict):
    try:
        return dialogue.save_project(data)
    except (dialogue.ProjectError, ValueError, TypeError) as ex:
        raise HTTPException(400, str(ex)) from ex


@router.get("/api/projects/{project_id}")
def projects_get(project_id: str):
    try:
        return dialogue.get_project(project_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy dự án.") from None


@router.delete("/api/projects/{project_id}")
def projects_delete(project_id: str):
    try:
        dialogue.delete_project(project_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy dự án.") from None
    return {"deleted": project_id}
