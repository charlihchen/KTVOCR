#!/usr/bin/env python3
"""Audit a KTVOCR batch guesses.csv for systematic guess-quality problems.

The scan writes rows incrementally, so this can run on a partial file as an
early quality gate: catch a systematic misfire (logos as singers, lyrics as
titles, missed labels) at video ~200 instead of video 6649.

Usage:
    python audit_guesses.py guesses.csv

Reads with utf-8-sig (batch.py writes a BOM on fresh runs; resume appends
plain UTF-8 after the existing BOM, which utf-8-sig also tolerates).
Stdlib only. Prints a plain-text report.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path


def load(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def main() -> None:
    # Windows CMD defaults stdout to cp1252, which cannot print the CJK
    # titles/singers in the report (UnicodeEncodeError). Force UTF-8 so
    # the script works with a plain `python audit_guesses.py ...` call.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) != 2:
        print("usage: python audit_guesses.py guesses.csv", file=sys.stderr)
        sys.exit(2)
    rows = load(Path(sys.argv[1]))
    n = len(rows)
    print(f"rows: {n}")
    if not n:
        print("empty file (or only a header) - nothing to audit yet")
        return

    def col(name: str) -> list[str]:
        return [(r.get(name) or "").strip() for r in rows]

    titles = col("title_guess")
    s1 = col("singer_guess")
    s2 = col("singer2_guess")
    lang = col("language_guess")
    songid_t = col("songid_title") if "songid_title" in rows[0] else [""] * n

    print("\n== coverage ==")
    print(f"title empty:      {sum(not t for t in titles)} ({pct(sum(not t for t in titles), n)})")
    print(f"singer empty:     {sum(not s for s in s1)} ({pct(sum(not s for s in s1), n)})")
    print(f"singer2 filled:   {sum(bool(s) for s in s2)} ({pct(sum(bool(s) for s in s2), n)})")
    print(f"language empty:   {sum(not l for l in lang)} ({pct(sum(not l for l in lang), n)})")
    if "songid_title" in rows[0]:
        n_songid = sum(bool(t) for t in songid_t)
        tag = "--songid was used" if n_songid else "--songid not used (or no hits yet)"
        print(f"songid present:   {n_songid} ({tag})")

    print("\n== singer == title (misassignment suspect) ==")
    bad = [t for t, s in zip(titles, s1) if t and s and t == s]
    print(f"count: {len(bad)}")
    for t in bad[:10]:
        print(f"  {t}")

    print("\n== most common title_guess (repeated values can be lyrics/logos) ==")
    for t, c in Counter(t for t in titles if t).most_common(12):
        print(f"  {c:4d}x  {t}")

    print("\n== most common singer_guess (repeated values can be logos/credits) ==")
    for s, c in Counter(s for s in s1 if s).most_common(12):
        print(f"  {c:4d}x  {s}")

    print("\n== long title suspects (song titles are short; lyrics are long) ==")
    long_t = [(t, len(t)) for t in titles if len(t) > 12]
    print(f"titles longer than 12 chars: {len(long_t)} ({pct(len(long_t), n)})")
    for t, _ in long_t[:10]:
        print(f"  {t}")

    print("\n== duplicate (title, singer) pairs (rename collisions) ==")
    pairs = Counter((t, s) for t, s in zip(titles, s1) if t and s)
    dupes = {p: c for p, c in pairs.items() if c > 1}
    print(f"pairs appearing more than once: {len(dupes)}")
    for (t, s), c in sorted(dupes.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {c:4d}x  {s} - {t}")

    print("\n== language values ==")
    for l, c in Counter(l for l in lang if l).most_common():
        print(f"  {c:4d}x  {l}")


if __name__ == "__main__":
    main()
