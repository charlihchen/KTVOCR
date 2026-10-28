#!/usr/bin/env python3
"""Song ID pass over the rows whose title is still missing — titles only.

Why this exists: Shazam identifies the *song* reliably (5/5 titles on the
Oct 2026 sample), but karaoke videos are usually covers, so the artist it
returns is the original singer, not the singer in the video. Titles from
Song ID are therefore trustworthy; singers from Song ID are not, and this
script never fills a singer from them.

What it does: reads a guesses CSV, takes every row whose ``title_final`` is
empty (317 rows in the Oct 2026 國語 set), fingerprints a 60 s audio slice
(starting at 15 s, skipping silent intros/logos) with Shazam, and writes
one result row per video to a *separate* results CSV. It never edits the
input CSV. Merging happens afterwards in the cloud: ``songid_title`` fills
an empty ``title_final``; ``songid_artist`` is recorded for reference only.

Resume: results are appended and flushed after every video, and a re-run
skips every ``original_path`` already in the results file, so Ctrl+C, a
reboot, or PC sleep just picks up where it left off. (The 6,649-video scan
taught us that lesson: never let an interrupted run wipe finished work.)
Only definitive rows are skipped: a title was found, or Shazam was asked
and said no match. Rows that failed with an error (e.g. ``no_audio``
because ffmpeg or the drive was unavailable) are retried on the next run,
not skipped forever.

Run from inside the ``app/`` directory, e.g. on Windows::

    py -3.11 songid_batch.py 國語_cleaned.csv -o songid_titles.csv
    py -3.11 songid_batch.py 國語_cleaned.csv -o songid_titles.csv --limit 5

``--limit N`` only does the first N missing-title rows: a smoke test
before the overnight run. Expect roughly 10-60 s per video for the
Shazam lookup, so 317 videos is a few hours — an overnight run.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import extract_audio  # noqa: E402
from songid import recognize_song  # noqa: E402

OUT_FIELDS = ["original_path", "title_final_before", "songid_title",
              "songid_artist", "error"]


def _read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", help="guesses CSV, e.g. 國語_cleaned.csv")
    ap.add_argument("-o", "--output", required=True,
                    help="results CSV, e.g. songid_titles.csv")
    ap.add_argument("--limit", type=int, default=0,
                    help="only do the first N missing-title rows (0 = all)")
    args = ap.parse_args()

    # Fail fast when ShazamAPI is missing instead of failing per video.
    try:
        import ShazamAPI  # noqa: F401
    except Exception:
        print("error: ShazamAPI is not installed.", file=sys.stderr)
        print("  fix: py -3.11 -m pip install ShazamAPI", file=sys.stderr)
        return 2

    src_csv = Path(args.csv)
    out_csv = Path(args.output)
    rows = _read_rows(src_csv)
    todo = [r for r in rows if not (r.get("title_final") or "").strip()]
    if args.limit:
        todo = todo[: args.limit]
    print(f"rows with empty title_final: {len(todo)}")

    done: set[str] = set()
    if out_csv.exists() and out_csv.stat().st_size > 0:
        raw = out_csv.read_bytes()
        if not raw.startswith(codecs.BOM_UTF8):
            print(f"error: {out_csv.name} is not this script's output "
                  "(no UTF-8 BOM); refusing to append to it.",
                  file=sys.stderr)
            return 2
        if not raw.endswith(b"\n"):
            raw = raw[: raw.rfind(b"\n") + 1]  # drop a torn final line
            out_csv.write_bytes(raw)
        # Resume skips only definitive rows: a title was found, or Shazam
        # was asked and said no match (empty title, no error). Rows that
        # failed with an error (e.g. no_audio because ffmpeg or the drive
        # was unavailable) are dropped here so the next run retries them
        # instead of skipping them forever.
        kept: list[dict] = []
        dropped = 0
        for r in _read_rows(out_csv):
            p = (r.get("original_path") or "").strip()
            if p and (r.get("error") or "").strip():
                dropped += 1
                continue
            if p:
                done.add(p)
            kept.append(r)
        if dropped:
            with out_csv.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
                writer.writeheader()
                writer.writerows(kept)
            print(f"resuming: skipping {len(done)} already-done videos, "
                  f"retrying {dropped} errored videos")
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.gettempdir()) / "ktvocr_songid"
    tmp.mkdir(parents=True, exist_ok=True)
    matched = 0
    with out_csv.open("a" if done else "w", newline="",
                      encoding="utf-8-sig" if not done else "utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        if not done:
            writer.writeheader()
        for i, r in enumerate(todo, 1):
            path = (r.get("original_path") or "").strip()
            if path in done:
                continue
            print(f"[{i}/{len(todo)}] {path}", flush=True)
            title, artist, error = "", "", ""
            seg = tmp / "songid_slice.wav"
            try:
                if extract_audio(Path(path), seg, secs=60, start=15):
                    res = recognize_song(seg)
                    if res.get("error"):
                        error = res["error"]
                    else:
                        title = res.get("title", "")
                        artist = res.get("artist", "")
                        if title:
                            matched += 1
                else:
                    error = "no_audio"
            except Exception as exc:  # never let one video kill the run
                error = f"{type(exc).__name__}: {exc}"[:160]
            finally:
                seg.unlink(missing_ok=True)
            writer.writerow({
                "original_path": path,
                "title_final_before": r.get("title_final") or "",
                "songid_title": title,
                "songid_artist": artist,
                "error": error,
            })
            fh.flush()
            print(f"  -> {title!r} / {artist!r} {error}", flush=True)
            time.sleep(2)  # be polite to the unofficial Shazam endpoint
    print(f"done: matched {matched}/{len(todo)} titles -> {out_csv}")
    print("Singers were NOT filled from Song ID: karaoke covers are sung by")
    print("other singers, so songid_artist is reference only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
