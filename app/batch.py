#!/usr/bin/env python3
"""Batch CLI for the KTV OCR Renamer.

Two subcommands (run from inside the ``app/`` directory)::

    python batch.py scan /path/to/videos -o guesses.csv [--secs 30]
    python batch.py apply guesses.csv --outdir renamed/
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
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


def cmd_scan(args: argparse.Namespace) -> int:
    video_dir = Path(args.video_dir)
    out_csv = Path(args.o)
    if not video_dir.is_dir():
        print(f"error: not a directory: {video_dir}", file=sys.stderr)
        return 2

    files = iter_videos(video_dir)
    print(f"found {len(files)} video files")
    tmp = Path("/tmp/ktvocr_batch")
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


def cmd_apply(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    with csv_path.open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
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

    s = sub.add_parser("scan", help="scan videos and write a guesses CSV for review")
    s.add_argument("video_dir", help="directory with karaoke videos (searched recursively)")
    s.add_argument("-o", required=True, help="output CSV path, e.g. guesses.csv")
    s.add_argument("--secs", type=int, default=30, help="seconds of video to scan (default 30)")

    a = sub.add_parser("apply", help="copy/rename files listed in a reviewed guesses CSV")
    a.add_argument("csv", help="guesses CSV with edited *_final columns")
    a.add_argument("--outdir", required=True, help="destination dir for renamed copies")

    args = ap.parse_args()
    if args.cmd == "scan":
        return cmd_scan(args)
    return cmd_apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
