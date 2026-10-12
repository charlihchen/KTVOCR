"""Core media-analysis pipeline for the KTV OCR Renamer.

Every external call (ffmpeg, EasyOCR, faster-whisper) is wrapped in
try/except so a single failure degrades gracefully instead of crashing
the caller. Heavy models are lazy-loaded as module-level singletons.
"""

from __future__ import annotations

import re
import subprocess
from math import log1p
from pathlib import Path

# ------------------------------------------------------------------ constants

LANGUAGES = ["英語", "國語", "日語", "韓語", "台語", "粵語"]
CATEGORIES = ["男歌星", "女歌星", "團體", "合唱", "外國男", "外國女", "外國團體"]

_WHISPER_LANG_MAP = {
    "en": "英語",
    "zh": "國語",
    "ja": "日語",
    "ko": "韓語",
    "yue": "粵語",
}

# Lazy singletons so that `import pipeline` stays cheap.
_ocr_reader = None
_whisper_model = None


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        from easyocr import Reader

        _ocr_reader = Reader(["en", "ch_tra", "ch_sim", "ja", "ko"], gpu=False)
    return _ocr_reader


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model


# --------------------------------------------------------------------- frames

def extract_frames(video_path: Path, out_dir: Path, fps: int = 1, secs: int = 30) -> list[Path]:
    """Extract ``fps`` frames/sec from the first ``secs`` seconds via ffmpeg.

    Returns the sorted list of written frame paths, or [] on any failure
    (missing ffmpeg, unreadable file, ...).
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-ss", "0", "-t", str(secs),
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            str(out_dir / "frame_%03d.jpg"),
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return sorted(out_dir.glob("frame_*.jpg"))
    except Exception:
        return []


# ------------------------------------------------------------------------ OCR

def _bbox_area(bbox) -> float:
    try:
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        return max(0.0, max(xs) - min(xs)) * max(0.0, max(ys) - min(ys))
    except Exception:
        return 0.0


# ------------------------------------------------------- text classification

# Lyricist/composer/production credits — never the performing singer.
_CREDIT_RE = re.compile(
    r"(作詞|作曲|編曲|作词|作曲|编曲|監製|监制|導演|导演|製作|制作|出品|發行|发行|版權|版权)"
)
# Channel logos / quality badges that repeat on every frame.
_WATERMARK_WORDS = {
    "ktv", "k歌", "伴奏", "原版", "高清", "超清", "蓝光", "藍光",
    "hd", "1080p", "4k", "mv", "dvd", "vcd",
}
# Pure numbers / timestamps / punctuation-only strings.
_JUNK_RE = re.compile(r"^[\d\s:：\-_/\\.,，。！？?!;；()（）\[\]【】「」『』《》\"'“”‘’♪♫·•–—]+$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
_WRAP_PAIRS = {"《": "》", "『": "』", "「": "」", "【": "】", "(": ")"}


def _clean_text(t: str) -> str:
    """Strip decorative wrappers (《title》) and stray music symbols."""
    t = (t or "").strip()
    for _ in range(3):
        nt = t.strip()
        if len(nt) >= 2 and nt[0] in _WRAP_PAIRS and _WRAP_PAIRS[nt[0]] == nt[-1]:
            t = nt[1:-1].strip()
            continue
        break
    return t.strip("♪♫·•-–— ")


def _is_junk(t: str) -> bool:
    if not t or len(t) < 2:
        return True
    if _TIME_RE.match(t):
        return True
    if _JUNK_RE.match(t):
        return True
    if t.lower() in _WATERMARK_WORDS:
        return True
    return False


def _is_credit(t: str) -> bool:
    return bool(_CREDIT_RE.search(t))


def _frame_size(fp: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(fp) as im:
            return im.size
    except Exception:
        return (0, 0)


def _read_frame(
    reader, fp: Path, img_h: int = 0
) -> list[tuple[str, float, float, float]]:
    """OCR one image. Returns [(text, conf, box_area, y_center_0to1)]. Never raises."""
    try:
        results = reader.readtext(str(fp))
    except Exception:
        return []
    out: list[tuple[str, float, float, float]] = []
    for bbox, text, conf in results:
        t = _clean_text(text)
        if not t or _is_junk(t) or _is_credit(t):
            continue
        try:
            c = float(conf)
        except Exception:
            c = 0.0
        area = _bbox_area(bbox)
        y = 0.5
        if img_h:
            try:
                ys = [p[1] for p in bbox]
                y = (min(ys) + max(ys)) / 2.0 / img_h
            except Exception:
                pass
        out.append((t, c, area, y))
    return out


def ocr_image(image_path: Path) -> list[dict]:
    """OCR a single image file.

    Returns [{"text": ..., "conf": ...}] sorted by confidence desc,
    or [] on any failure (model missing, unreadable file, ...).
    """
    try:
        reader = _get_ocr_reader()
    except Exception:
        return []
    items = _read_frame(reader, image_path)
    items.sort(key=lambda it: it[1], reverse=True)
    return [{"text": t, "conf": c} for t, c, _, _ in items]


def ocr_frames(frame_paths: list[Path]) -> list[dict]:
    """Run EasyOCR over frames and aggregate repeated text.

    Texts are cleaned (《》 wrappers stripped), lyricist/composer credits,
    watermarks and junk are dropped, and spacing variants ("江 南"/"江南")
    are merged. Each text scores ``sum(conf * (1 + log1p(area)))`` with two
    karaoke-specific adjustments: text stuck on screen for most of the clip
    (logos) is downweighted, and text in the upper two-thirds of the frame
    (where title cards live; lyrics scroll along the bottom) is upweighted.

    Returns the top 15 as ``[{"text": ..., "score": ...}]`` sorted by score
    desc, or [] on any failure.
    """
    try:
        reader = _get_ocr_reader()
    except Exception:
        return []

    agg: dict[str, dict] = {}
    total = 0
    for fp in frame_paths:
        total += 1
        _, h = _frame_size(fp)
        seen: set[str] = set()
        for t, conf, area, y in _read_frame(reader, fp, h):
            key = re.sub(r"\s+", "", t)
            d = agg.setdefault(
                key,
                {"text": t, "score": 0.0, "nframes": 0,
                 "max_area": 0.0, "y_sum": 0.0},
            )
            try:
                d["score"] += float(conf) * (1.0 + log1p(area))
            except Exception:
                pass
            if key not in seen:
                seen.add(key)
                d["nframes"] += 1
                d["y_sum"] += y
            if area > d["max_area"]:
                d["max_area"] = area
                d["text"] = t  # keep the surface form with the biggest box

    ranked = []
    for d in agg.values():
        s = d["score"]
        if d["nframes"] > max(8, 0.4 * total):
            s *= 0.25  # persistent overlay: watermark / logo
        y_avg = d["y_sum"] / max(1, d["nframes"])
        s *= 1.35 if y_avg <= 0.68 else 0.75  # title cards live up top
        ranked.append(
            {
                "text": d["text"],
                "score": s,
                "nframes": d["nframes"],
                "max_area": d["max_area"],
            }
        )
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked[:15]


# ------------------------------------------------------- title / singer guess

_TITLE_RE = re.compile(r"(?:歌名|曲名|曲目|歌曲|TITLE|Title|SONG|Song)\s*[:：]\s*(.+)")
_SINGER_RE = re.compile(
    r"(?:歌手|歌星|演唱|主唱|原唱|演唱者|ARTIST|Artist|SINGER|Singer)\s*[:：]\s*(.+)"
)


def guess_title_singer(candidates: list[dict]) -> tuple[str, str]:
    """Guess (title, singer) from ranked OCR candidates.

    Labeled patterns (``歌名: ...`` / ``歌手: ...``) win when present;
    otherwise the top-scoring candidate is the title guess and the next
    distinct one is the singer guess. Returns ("", "") when empty.
    """
    if not candidates:
        return ("", "")

    title = ""
    for c in candidates:
        m = _TITLE_RE.search(c.get("text", ""))
        if m:
            title = m.group(1).strip()
            break

    singer = ""
    for c in candidates:
        m = _SINGER_RE.search(c.get("text", ""))
        if m:
            singer = m.group(1).strip()
            break

    if not title:
        title = candidates[0].get("text", "").strip()
    if not singer:
        for c in candidates[1:]:
            t = c.get("text", "").strip()
            if t and t != title:
                singer = t
                break
    return (title, singer)


# ---------------------------------------------------------------------- audio

def extract_frame_at(video_path: Path, seconds: float, out_path: Path) -> bool:
    """Grab a single frame at ``seconds`` via ffmpeg. Returns True on success."""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(max(0.0, float(seconds))),
            "-i", str(video_path),
            "-frames:v", "1",
            str(out_path),
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return out_path.exists()
    except Exception:
        return False


def extract_audio(video_path: Path, out_path: Path, secs: int = 30) -> bool:
    """Extract the first ``secs`` seconds of audio as 16 kHz mono WAV."""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-ss", "0", "-t", str(secs),
            "-i", str(video_path),
            "-ac", "1", "-ar", "16000", "-vn",
            str(out_path),
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return out_path.exists()
    except Exception:
        return False


def detect_language(audio_path: Path) -> tuple[str, str]:
    """Detect the sung language with faster-whisper.

    Returns (label, note) e.g. ("國語", "whisper=zh"),
    ("", "detection failed") when the language is unknown, or ("", "error")
    when transcription itself fails.
    """
    try:
        model = _get_whisper_model()
        segments, info = model.transcribe(str(audio_path))
        for _ in segments:  # consume so language detection completes
            pass
        code = (getattr(info, "language", "") or "").lower()
        label = _WHISPER_LANG_MAP.get(code, "")
        if label:
            return (label, f"whisper={code}")
        return ("", "detection failed")
    except Exception:
        return ("", "error")


# ------------------------------------------------------------------- filename

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize(part: str) -> str:
    """Strip filesystem-hostile characters, collapse whitespace, cap length."""
    s = _INVALID_CHARS.sub("", part or "")
    s = _CONTROL_CHARS.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def build_filename(singer: str, title: str, language: str, category: str, ext: str) -> str:
    """Build ``singer-title-language-category.ext`` from sanitized parts."""
    parts = [sanitize(singer), sanitize(title), sanitize(language), sanitize(category)]
    if not ext.startswith("."):
        ext = "." + ext
    return "-".join(parts) + ext
