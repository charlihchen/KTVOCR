#!/usr/bin/env python3
"""Diagnose KTVOCR issues by testing ffmpeg, OCR, and file access.

This script helps identify why title/singer guesses are empty or garbage.
"""

from __future__ import annotations

import csv
import re
import subprocess
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import (
    extract_frames, ocr_frames, guess_title_singer,
    extract_audio, detect_language, ocr_diagnostics,
    _get_ocr_readers
)

# Test video path resolution
def test_path_resolution(video_path: Path) -> None:
    """Debug why a video file can't be accessed."""
    print(f"\n=== Testing path: {video_path} ===")

    # Check if file exists
    exists = video_path.exists()
    print(f"  Path exists: {exists}")

    if not exists:
        # Try to find similar files
        parent = video_path.parent
        if parent.exists():
            print(f"  Parent dir contents (first 5): {list(parent.iterdir())[:5]}")
        else:
            print(f"  Parent dir does not exist: {parent}")
            # Check if it's an SMB path issue
            if str(parent).startswith("\\\\\\\\"):
                print("  This looks like a Windows UNC path - need to map to SMB")
        return

    # Try ffmpeg directly
    print("  Trying ffmpeg to probe file...")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"  ffprobe success: duration={result.stdout.strip()}")
        else:
            print(f"  ffprobe failed: {result.stderr.strip()[:100]}")
    except FileNotFoundError:
        print("  ffprobe not found (ffmpeg may not be installed)")
    except Exception as e:
        print(f"  ffprobe error: {e}")


def test_ocr_on_local_image() -> None:
    """Test OCR with a simple local image."""
    print("\n=== Testing OCR locally ===")

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  ERROR: PIL (Pillow) not installed. Run: pip install Pillow")
        print("  Then run: python3 diagnose.py --test-ocr")
        return

    import tempfile

    # Create a test image with known text
    img = Image.new("RGB", (640, 120), "black")
    draw = ImageDraw.Draw(img)

    # Chinese text (song title)
    draw.text((30, 20), "江南", fill="white")
    # English text (song title)
    draw.text((30, 60), "Dancing Queen", fill="white")
    # Singer name
    draw.text((30, 90), "ABBA", fill="white")

    tmp = Path(tempfile.gettempdir()) / "ktvocr_diagnostic_test.jpg"
    img.save(tmp)

    print(f"  Created test image at: {tmp}")

    # Test raw OCR first (bypassing confidence filtering)
    print("  Testing raw OCR (bypassing confidence threshold)...")
    from pipeline import _read_frame, MIN_CONFIDENCE
    raw_results = _read_frame(tmp, min_conf=0.0)  # No confidence filter

    print(f"  Raw OCR results with conf=0.0: {len(raw_results)} items")
    for text, conf, area, y in raw_results[:5]:
        conf_pct = int(conf * 100)
        print(f"    [{conf_pct}%] area={area:.0f} y={y:.2f} {text[:40]}")

    # Now test with confidence threshold
    print(f"\n  Using threshold: min_conf={MIN_CONFIDENCE}")
    results = [r for r in raw_results if r[1] >= MIN_CONFIDENCE]

    print(f"  Filtered OCR results: {len(results)} items")
    for text, conf, area, y in results[:5]:
        conf_pct = int(conf * 100)
        print(f"    [{conf_pct}%] {text[:40]}")

    tmp.unlink()


def test_frame_extraction(video_path: Path, output_dir: Path) -> None:
    """Extract frames and analyze OCR candidates."""
    print(f"\n=== Extracting frames from {video_path} ===")

    frames = extract_frames(video_path, output_dir, fps=1, secs=10)
    print(f"  Extracted {len(frames)} frames")

    if not frames:
        print("  No frames extracted - check ffmpeg installation and file access")
        return

    # Run OCR on frames
    print("  Running OCR...")
    candidates = ocr_frames(frames)
    print(f"  Found {len(candidates)} unique text candidates")

    # Show top candidates
    print("  Top 10 candidates:")
    for c in candidates[:10]:
        conf_pct = int(c['score'] * 100)
        early = " (early)" if c.get('early') else ""
        print(f"    [{conf_pct}%] y={c['y_avg']:.2f} {early} {c['text'][:40]}")

    # Test guessing
    print("  Testing title/singer guess...")
    title, singer, singer2 = guess_title_singer(candidates)
    print(f"    Title: '{title}'")
    print(f"    Singer: '{singer}'")
    print(f"    Singer2: '{singer2}'")

    # Clean up
    import shutil
    shutil.rmtree(output_dir, ignore_errors=True)


def analyze_csv(csv_path: Path) -> None:
    """Analyze a guesses.csv file for patterns."""
    print(f"\n=== Analyzing CSV: {csv_path} ===")

    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
        rows = list(csv.DictReader(f))

    print(f"  Total rows: {len(rows)}")

    # Count empty guesses
    empty_titles = sum(1 for r in rows if not r.get('title_guess', '').strip())
    empty_singers = sum(1 for r in rows if not r.get('singer_guess', '').strip())

    print(f"  Empty titles: {empty_titles} ({100*empty_titles/len(rows):.1f}%)")
    print(f"  Empty singers: {empty_singers} ({100*empty_singers/len(rows):.1f}%)")

    # Show sample garbage
    garbage = [r.get('title_guess', '')[:20] for r in rows[:50]
               if r.get('title_guess', '').strip() and not r.get('title_guess', '').replace(' ', '').isalnum()]
    if garbage:
        print(f"  Sample garbage text: {garbage[:5]}")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Diagnose KTVOCR issues")
    ap.add_argument('--video', help="Test with a specific video file")
    ap.add_argument('--csv', help="Analyze an existing guesses.csv")
    ap.add_argument('--test-ocr', action='store_true', help="Test OCR with a synthetic image")
    args = ap.parse_args()

    if args.test_ocr:
        test_ocr_on_local_image()

    if args.csv:
        analyze_csv(Path(args.csv))

    if args.video:
        video_path = Path(args.video)
        test_path_resolution(video_path)
        if video_path.exists():
            output_dir = Path(tempfile.gettempdir()) / "ktvocr_diag_frames"
            test_frame_extraction(video_path, output_dir)

    if not (args.video or args.csv or args.test_ocr):
        ap.print_help()


if __name__ == "__main__":
    main()