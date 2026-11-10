"""Đọc văn bản: POST /api/tts."""

from __future__ import annotations

from pathlib import Path

import anyio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from giongviet import history, library
from giongviet.api.common import (
    MAX_CHARS,
    add_to_library,
    check_lib_voice,
    get_engine,
    log,
    read_upload,
    voice_label,
    warning_headers,
)
from giongviet.speech import dialogue, text_normalize

router = APIRouter()


@router.post("/api/tts")
async def tts(
    text: str = Form(""),
    engine: str = Form("edge"),
    voice: str = Form(""),
    speed: int = Form(0),  # % : 0 = 1x, 100 = 2x, 200 = 3x
    pitch: int = Form(0),  # Hz: chỉ engine có capabilities.pitch
    save_as: str = Form(""),  # có ref_audio + save_as: lưu giọng vào thư viện (cần consent=true)
    consent: bool = Form(False),
    normalize: bool = Form(
        True
    ),  # chuẩn hoá văn bản (chỉ engine có capabilities.normalize, tức VieNeu)
    ref_audio: UploadFile | None = File(None),
):
    text = text.strip()
    if not text:
        raise HTTPException(400, "Văn bản trống.")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Văn bản quá dài (tối đa {MAX_CHARS} ký tự).")
    speed = max(-50, min(200, speed))
    pitch = max(-50, min(50, pitch))
    e = get_engine(engine)
    check_lib_voice(e, voice)
    synth_text = (
        text_normalize.normalize(text) if normalize and e.capabilities().get("normalize") else text
    )
    pausey = text_normalize.has_pause(
        text
    )  # có thẻ [nghỉ Ns]: đi qua pipeline hội thoại (mọi engine)
    if pausey:
        try:
            text_normalize.split_pauses(text)
        except ValueError as ex:
            raise HTTPException(400, str(ex)) from ex

    warnings: list[str] = []
    extra_files: dict[str, bytes] = {}
    tmp_path = None
    try:
        if e.capabilities()["clone"] and ref_audio is not None and ref_audio.filename:
            raw = await read_upload(ref_audio)
            if save_as.strip():
                voice = (
                    library.LIB_PREFIX + (await add_to_library(e, raw, consent, name=save_as))["id"]
                )
            else:
                import tempfile

                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=Path(ref_audio.filename).suffix or ".wav"
                ) as f:
                    f.write(raw)
                    tmp_path = f.name
        if pausey:
            wav = await dialogue.render_text(
                e, voice, text, speed, normalize, pitch, tmp_path, warnings
            )
            data, mp3 = await anyio.to_thread.run_sync(dialogue.encode_outputs, wav)
            mime = "audio/wav"
            if mp3:
                extra_files["mp3"] = mp3
            await anyio.to_thread.run_sync(dialogue.prune_cache)
        else:
            data, mime = await e.synthesize(
                synth_text, voice, speed, pitch=pitch, ref_audio=tmp_path, warnings=warnings
            )
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(e.error_status, f"{e.name} lỗi: {ex}") from ex
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    ext = "mp3" if mime == "audio/mpeg" else "wav"
    headers = {
        "Content-Disposition": f'attachment; filename="giong-noi.{ext}"',
        **warning_headers(warnings),
    }
    try:  # lịch sử chỉ là tiện ích: lỗi ghi đĩa không được làm hỏng bản vừa tạo
        headers["X-History-Id"] = history.save(
            "tts",
            {
                "text": text,
                "engine": e.id,
                "voice": voice,
                "voice_label": await voice_label(e, voice) if voice else "",
                "speed": speed,
                "pitch": pitch,
                "normalize": normalize,
                "cloned_ref": bool(tmp_path),
                "has_mp3": "mp3" in extra_files,
            },
            data,
            ext,
            extra_files,
        )
    except OSError as ex:
        log.warning("Không lưu được lịch sử: %s", ex)
    return Response(data, media_type=mime, headers=headers)
