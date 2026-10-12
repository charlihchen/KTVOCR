"""Opt-in Shazam-style song recognition via audio fingerprinting.

Uses the ``ShazamAPI`` package (unofficial Shazam endpoint — needs internet).
Best-effort by design: karaoke re-recordings and backing tracks usually do
*not* match Shazam's fingerprints, so a miss just means "no match", not an
error. Never raises.
"""

from __future__ import annotations

import time
from pathlib import Path


def recognize_song(audio_path: Path, time_budget: float = 150.0) -> dict:
    """Fingerprint ``audio_path`` and ask Shazam what it is.

    Returns ``{"title": ..., "artist": ...}`` on a match, ``{}`` when nothing
    matched, or ``{"error": <code>}`` with one of ``not_installed``,
    ``unreadable``, ``no_audio``, ``no_match``-style failures. The ``error``
    value is a short machine-readable code (a human message is added by the
    caller). Never raises.
    """
    try:
        from ShazamAPI import Shazam
    except Exception:
        return {"error": "not_installed"}
    try:
        import requests
        from unittest import mock
    except Exception:
        return {"error": "not_installed"}

    try:
        blob = Path(audio_path).read_bytes()
    except Exception:
        return {"error": "unreadable"}
    if not blob:
        return {"error": "no_audio"}

    votes: dict[tuple[str, str], int] = {}
    deadline = time.monotonic() + time_budget
    try:
        shazam = Shazam(blob)
        _orig_post = requests.post

        def _post(*args, **kwargs):
            kwargs.setdefault("timeout", 25)
            return _orig_post(*args, **kwargs)

        with mock.patch.object(requests, "post", _post):
            for _offset, res in shazam.recognizeSong():
                track = (res or {}).get("track") or {}
                title = (track.get("title") or "").strip()
                artist = (track.get("subtitle") or "").strip()
                if title and artist:
                    key = (title, artist)
                    votes[key] = votes.get(key, 0) + 1
                    if votes[key] >= 2:
                        break  # two chunks agree — good enough
                if time.monotonic() >= deadline:
                    break
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:160]}

    if not votes:
        return {}
    (title, artist), _n = max(votes.items(), key=lambda kv: kv[1])
    return {"title": title, "artist": artist}
