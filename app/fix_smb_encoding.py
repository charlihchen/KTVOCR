#!/usr/bin/env python3
"""Helper for SMB path encoding on macOS.

This module provides utilities to handle GBK/UTF-8 encoding issues when
accessing Chinese filenames on SMB shares from macOS.

The problem:
- Windows SMB shares often store filenames in GBK (Chinese encoding)
- macOS mounts with UTF-8 by default
- This causes 國語 to appear as ?? in filenames

Solutions:
1. Remount with proper charset: mount -t smbfs -o nobrl,noatime,soft,vers=3.0 //server/share /Volumes/mnt
2. Use Python to decode GBK filenames after mounting
3. Store files with ASCII-safe names (pinyin transliteration)
"""

import os
import re
from pathlib import Path
from typing import Optional


def decode_gbk_filename(filename: str) -> str:
    """Attempt to decode a GBK-encoded filename that appears as garbage in UTF-8.

    Some SMB mounts show Chinese as ??? which cannot be decoded.
    This function helps identify and work around such issues.
    """
    # Check if filename contains replacement characters or ?
    if "??" in filename:
        return f"[UNREADABLE:{filename}]"

    # Check if it's actually valid UTF-8
    try:
        filename.encode('utf-8').decode('utf-8')
        return filename
    except UnicodeDecodeError:
        pass

    return filename


def get_video_files_ktv(folder: Path) -> list[Path]:
    """Get all video files from a KTV folder, handling encoding issues.

    Returns video files sorted by filename number (the 6-digit ID).
    """
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m2ts", ".wmv", ".flv", ".webm"}

    if not folder.exists():
        print(f"Warning: Folder does not exist: {folder}")
        print(f"  Please check if the SMB share is mounted correctly.")
        print(f"  Try: df -h | grep /Volumes")

        # On macOS, check common mount points
        if not folder.is_absolute():
            print(f"\n  Did you mean one of these?")
            for mount_point in Path("/Volumes").iterdir() if Path("/Volumes").exists() else []:
                if mount_point.is_dir():
                    print(f"    {mount_point}")

        return []

    files = []
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in video_exts:
            files.append(p)

    # Sort by the 6-digit number in the filename
    def get_id(p: Path) -> int:
        m = re.search(r'(\d{6})\.', p.name)
        return int(m.group(1)) if m else 0

    return sorted(files, key=get_id)


def diagnose_path(p: Path) -> dict:
    """Diagnose path issues and encoding problems."""
    result = {
        "path": str(p),
        "exists": p.exists(),
        "parent_exists": p.parent.exists() if p.parent else False,
    }

    if p.exists():
        result["is_file"] = p.is_file()
        result["size"] = p.stat().st_size if p.is_file() else None

    if not p.parent.exists():
        # Check common macOS mount points
        mounts = ["/Volumes/ktv", "/Volumes/SMB", "/Volumes/Music"]
        for mp in mounts:
            if Path(mp).exists():
                result["suggested_path"] = str(list(Path(mp).rglob(p.name))[0]) if any(Path(mp).rglob(p.name)) else None
                break

    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Diagnose SMB/encoding issues")
    ap.add_argument("path", help="Path to check")
    args = ap.parse_args()

    result = diagnose_path(Path(args.path))
    for k, v in result.items():
        print(f"  {k}: {v}")