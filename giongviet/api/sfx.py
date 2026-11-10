"""Hiệu ứng âm thanh cho thẻ [tiếng mưa]…: /api/sfx."""

from __future__ import annotations

import anyio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from giongviet.api.common import read_upload
from giongviet.engines.registry import ENGINES
from giongviet.speech import sfx

router = APIRouter()


@router.get("/api/sfx")
def sfx_catalog() -> list[dict]:
    return sfx.catalog()


@router.get("/api/sfx/{sfx_id}/audio")
def sfx_audio(sfx_id: str) -> FileResponse:
    try:
        return FileResponse(sfx.path_of(sfx_id), media_type="audio/wav")
    except sfx.SfxNotFound as ex:
        raise HTTPException(404, str(ex)) from ex


@router.post("/api/sfx")
async def sfx_add(name: str = Form(...), file: UploadFile = File(...)) -> dict:
    reserved = [t for e in ENGINES.values() for t in e.capabilities()["emotion_tags"]]
    raw = await read_upload(file)
    try:
        return await anyio.to_thread.run_sync(sfx.add, name, raw, reserved)
    except sfx.SfxError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.delete("/api/sfx/{sfx_id}")
def sfx_delete(sfx_id: str) -> dict:
    try:
        sfx.delete(sfx_id)
    except sfx.SfxNotFound as ex:
        raise HTTPException(404, str(ex)) from ex
    return {"ok": True}
