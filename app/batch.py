#!/usr/bin/env python3
"""Batch CLI for the KTV OCR Renamer.

Run from inside the ``app/`` directory::

    python batch.py check                              # verify the environment
    python batch.py scan /path/to/videos -o guesses.csv [--secs 30]
    python batch.py apply guesses.csv --outdir renamed/
"""

from __future__ import annotations

import argparse
import csv
import locale
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import (  # noqa: E402
    CATEGORIES,
    LANGUAGES,
    build_filename,
    detect_language,
    extract_audio,
    extract_frames,
    guess_title_singer,
    ocr_diagnostics,
    ocr_frames,
)

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".wmv", ".flv", ".webm"}

COLUMNS = [
    "original_path",
    "title_guess",
    "singer_guess",
    "language_guess",
    "language_note",
    "category_guess",
    "title_final",
    "singer_final",
    "language_final",
    "category_final",
    "new_name",
    "status",
]


def iter_videos(video_dir: Path) -> list[Path]:
    return sorted(
        p for p in video_dir.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    )


def preflight() -> int:
    """Verify ffmpeg + OCR engine before scanning; print actionable fixes.

    Returns 0 when the environment can actually produce results, 2 otherwise.
    """
    ok = True
    if shutil.which("ffmpeg") is None:
        ok = False
        print("error: ffmpeg not found on PATH.", file=sys.stderr)
        print("  macOS:   brew install ffmpeg", file=sys.stderr)
        print("  Windows: winget install Gyan.FFmpeg  (then reopen the terminal)", file=sys.stderr)
        print("  Ubuntu:  sudo apt install ffmpeg", file=sys.stderr)
    else:
        print("ffmpeg ok")
    print("checking OCR engine (first run downloads ~1-2 GB of models, please wait)...")
    diag = ocr_diagnostics()
    if not diag.get("ok"):
        ok = False
        print(
            f"error: OCR engine failed [{diag.get('stage')}]: {diag.get('detail')}",
            file=sys.stderr,
        )
        print("  fix: pip install -r requirements.txt, then delete the EasyOCR", file=sys.stderr)
        print("  model folder and rerun to re-download cleanly:", file=sys.stderr)
        print("    macOS/Linux: rm -rf ~/.EasyOCR/model", file=sys.stderr)
        print(r"    Windows:     rmdir /s %USERPROFILE%\.EasyOCR\model", file=sys.stderr)
        if "numpy" in (diag.get("detail") or "").lower():
            print("  this looks like the NumPy 1.x/2.x binary clash; try:", file=sys.stderr)
            print('    pip install "numpy<2"', file=sys.stderr)
    else:
        print(f"ocr engine ok: {diag.get('detail')}")
    try:
        import faster_whisper  # noqa: F401

        print("whisper ok: language detection available")
    except Exception:
        print("warning: faster-whisper not installed; language_guess will stay empty")
        print("  fix: pip install -r requirements.txt")
    return 0 if ok else 2


def cmd_scan(args: argparse.Namespace) -> int:
    video_dir = Path(args.video_dir)
    out_csv = Path(args.o)
    if not video_dir.is_dir():
        print(f"error: not a directory: {video_dir}", file=sys.stderr)
        return 2

    rc = preflight()
    if rc != 0:
        return rc

    files = iter_videos(video_dir)
    print(f"found {len(files)} video files")
    # tempfile.gettempdir() is cross-platform: /tmp on macOS/Linux,
    # %LOCALAPPDATA%/Temp on Windows (writing to C:\tmp needs admin rights).
    tmp = Path(tempfile.gettempdir()) / "ktvocr_batch"
    tmp.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for i, vf in enumerate(files, 1):
            print(f"[{i}/{len(files)}] {vf}")
            title_guess = singer_guess = language_guess = language_note = ""
            try:
                frame_dir = tmp / f"frames_{i}"
                frames = extract_frames(vf, frame_dir, fps=1, secs=args.secs)
                title_guess, singer_guess = guess_title_singer(ocr_frames(frames))
            except Exception as exc:
                print(f"  ocr failed: {exc}")
            finally:
                shutil.rmtree(tmp / f"frames_{i}", ignore_errors=True)
            try:
                audio_path = tmp / f"audio_{i}.wav"
                if extract_audio(vf, audio_path, secs=args.secs):
                    language_guess, language_note = detect_language(audio_path)
                audio_path.unlink(missing_ok=True)
            except Exception as exc:
                print(f"  audio failed: {exc}")
            writer.writerow(
                {
                    "original_path": str(vf),
                    "title_guess": title_guess,
                    "singer_guess": singer_guess,
                    "language_guess": language_guess,
                    "language_note": language_note,
                    "category_guess": "",
                    "title_final": title_guess,
                    "singer_final": singer_guess,
                    "language_final": language_guess,
                    "category_final": "",
                    "new_name": "",
                    "status": "",
                }
            )
            fh.flush()
    print(f"wrote {out_csv}")
    return 0


def _read_rows(csv_path: Path) -> list[dict]:
    """Read a reviewed guesses CSV, tolerating Excel-on-Windows saves.

    We write UTF-8-with-BOM so Excel opens it correctly, but when Excel
    saves a CSV on a Traditional Chinese Windows machine it rewrites it
    in the system ANSI code page (e.g. CP950) without the BOM. Falling
    back to the system encoding keeps `apply` working on those files
    instead of dying with a UnicodeDecodeError.
    """
    try:
        with csv_path.open(encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    except UnicodeDecodeError:
        with csv_path.open(encoding=locale.getpreferredencoding(False)) as fh:
            return list(csv.DictReader(fh))


def cmd_apply(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = _read_rows(csv_path)
    if not rows:
        print("nothing to do: empty csv")
        return 0

    done = skipped = 0
    for r in rows:
        if (r.get("status") or "").strip().lower() == "skip":
            skipped += 1
            continue
        title = (r.get("title_final") or "").strip()
        singer = (r.get("singer_final") or "").strip()
        language = (r.get("language_final") or "").strip()
        category = (r.get("category_final") or "").strip()
        if not (title and singer and language and category):
            continue  # leave status empty for the user to finish later
        if language not in LANGUAGES or category not in CATEGORIES:
            r["status"] = "invalid language/category"
            continue
        src = Path(r.get("original_path") or "")
        if not src.is_file():
            r["status"] = "source missing"
            continue
        new_name = build_filename(singer, title, language, category, src.suffix)
        dst = outdir / new_name
        n = 1
        while dst.exists():
            dst = outdir / f"{dst.stem}_{n}{dst.suffix}"
            n += 1
        try:
            shutil.copy2(src, dst)  # copy, never move
            r["new_name"] = dst.name
            r["status"] = "done"
            done += 1
        except Exception as exc:
            r["status"] = f"error: {exc}"

    out_csv = csv_path.with_name(csv_path.stem + ".applied.csv")
    with out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"done={done} skipped={skipped} -> {out_csv}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="KTV OCR Renamer batch tool")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="verify ffmpeg / OCR / whisper are working")

    s = sub.add_parser("scan", help="scan videos and write a guesses CSV for review")
    s.add_argument("video_dir", help="directory with karaoke videos (searched recursively)")
    s.add_argument("-o", required=True, help="output CSV path, e.g. guesses.csv")
    s.add_argument("--secs", type=int, default=30, help="seconds of video to scan (default 30)")

    a = sub.add_parser("apply", help="copy/rename files listed in a reviewed guesses CSV")
    a.add_argument("csv", help="guesses CSV with edited *_final columns")
    a.add_argument("--outdir", required=True, help="destination dir for renamed copies")

    args = ap.parse_args()
    if args.cmd == "check":
        return preflight()
    if args.cmd == "scan":
        return cmd_scan(args)
    return cmd_apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
