"""FastAPI web app for the KTV OCR Renamer.

Run from inside the ``app/`` directory::

    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline import (
    CATEGORIES,
    LANGUAGES,
    build_filename,
    detect_language,
    extract_audio,
    extract_frames,
    guess_title_singer,
    ocr_frames,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
FRAMES_DIR = STATIC_DIR / "frames"

for _d in (STATIC_DIR, UPLOAD_DIR, OUTPUT_DIR, FRAMES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".wmv", ".flv", ".webm"}
_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

app = FastAPI(title="KTV OCR Renamer")


class RenameRequest(BaseModel):
    file_id: str
    singer: str
    title: str
    language: str
    category: str


@app.post("/api/analyze")
async def analyze(video: UploadFile = File(...)):
    original_name = Path(video.filename or "upload").name
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext or '(none)'}")

    file_id = uuid.uuid4().hex
    saved_path = UPLOAD_DIR / f"{file_id}_{original_name}"
    try:
        with saved_path.open("wb") as fh:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not save upload: {exc}")

    # 1) frames -----------------------------------------------------------
    frames: list[Path] = []
    try:
        frames = extract_frames(saved_path, UPLOAD_DIR / f"{file_id}_frames", fps=1, secs=30)
    except Exception:
        frames = []

    # 2) OCR ---------------------------------------------------------------
    candidates: list[dict] = []
    try:
        raw = ocr_frames(frames)
        candidates = [{"text": c["text"], "score": round(float(c["score"]), 2)} for c in raw[:12]]
    except Exception:
        candidates = []

    # 3) title / singer guesses --------------------------------------------
    title_guess, singer_guess = "", ""
    try:
        title_guess, singer_guess = guess_title_singer(candidates)
    except Exception:
        title_guess, singer_guess = "", ""

    # 4) audio language ------------------------------------------------------
    language_guess, language_note = "", ""
    try:
        audio_path = UPLOAD_DIR / f"{file_id}.wav"
        if extract_audio(saved_path, audio_path, secs=30):
            try:
                language_guess, language_note = detect_language(audio_path)
            except Exception:
                language_guess, language_note = "", "detection failed"
    except Exception:
        language_guess, language_note = "", ""

    # 5) copy up to 6 frames for the UI --------------------------------------
    frame_urls: list[str] = []
    try:
        picked = frames
        if len(picked) > 6:
            step = len(picked) / 6
            picked = [picked[int(i * step)] for i in range(6)]
        dest_dir = FRAMES_DIR / file_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        for p in picked:
            try:
                shutil.copy2(p, dest_dir / p.name)
                frame_urls.append(f"/frames/{file_id}/{p.name}")
            except Exception:
                continue
    except Exception:
        frame_urls = []
    finally:
        shutil.rmtree(UPLOAD_DIR / f"{file_id}_frames", ignore_errors=True)

    return {
        "file_id": file_id,
        "original_name": original_name,
        "ext": ext,
        "candidates": candidates,
        "title_guess": title_guess,
        "singer_guess": singer_guess,
        "language_guess": language_guess,
        "language_note": language_note,
        "frames": frame_urls,
    }


@app.post("/api/rename")
async def rename(req: RenameRequest):
    if not _FILE_ID_RE.match(req.file_id or ""):
        raise HTTPException(status_code=400, detail="Invalid file_id")
    singer = (req.singer or "").strip()
    title = (req.title or "").strip()
    language = (req.language or "").strip()
    category = (req.category or "").strip()
    if not (singer and title and language and category):
        raise HTTPException(
            status_code=400,
            detail="singer, title, language and category are all required",
        )
    if language not in LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unknown language: {language}")
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    src: Path | None = None
    for p in UPLOAD_DIR.glob(f"{req.file_id}_*"):
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTS:
            src = p
            break
    if src is None:
        raise HTTPException(status_code=404, detail="Uploaded file not found (it may have been cleaned up)")

    new_name = build_filename(singer, title, language, category, src.suffix.lower())
    if not new_name or new_name == src.suffix.lower():
        raise HTTPException(status_code=400, detail="Could not build a filename from the given fields")
    dst = OUTPUT_DIR / new_name
    n = 1
    while dst.exists():
        dst = OUTPUT_DIR / f"{dst.stem}_{n}{dst.suffix}"
        n += 1
    try:
        shutil.copy2(src, dst)  # copy, never move — keep the original
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not save renamed file: {exc}")
    return {"new_name": dst.name}


# Serve the UI last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
