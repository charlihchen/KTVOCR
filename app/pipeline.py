"""Core media-analysis pipeline for the KTV OCR Renamer.

Every external call (ffmpeg, EasyOCR, faster-whisper) is wrapped in
try/except so a single failure degrades gracefully instead of crashing
the caller. Heavy models are lazy-loaded as module-level singletons.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
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
_whisper_model = None

# EasyOCR allows only ONE CJK script model per Reader (each is bundled with
# English): ch_tra, ch_sim, ja, ko each need their own Reader. The text
# DETECTOR is script-independent, so we detect once and run RECOGNITION with
# every loaded script model, then merge the results.
_OCR_GROUPS = [
    ("ch_tra", ["ch_tra", "en"]),
    ("ch_sim", ["ch_sim", "en"]),
    ("ja", ["ja", "en"]),
    ("ko", ["ko", "en"]),
]
_ocr_readers: dict[str, object] = {}
_ocr_reader_errors: dict[str, str] = {}


def _get_ocr_readers() -> dict[str, object]:
    """Lazy-load one EasyOCR Reader (CPU) per script group.

    Returns {group: Reader} for every group that loaded. Failures are
    recorded in _ocr_reader_errors and not retried. Never raises.
    """
    if not _ocr_readers and not _ocr_reader_errors:
        try:
            from easyocr import Reader
        except Exception as exc:
            _ocr_reader_errors["import"] = f"{type(exc).__name__}: {exc}"[:200]
        else:
            for group, langs in _OCR_GROUPS:
                try:
                    _ocr_readers[group] = Reader(langs, gpu=False)
                except Exception as exc:
                    _ocr_reader_errors[group] = f"{type(exc).__name__}: {exc}"[:200]
    return dict(_ocr_readers)


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
def _ws_word(word: str) -> str:
    """Render a CJK word whitespace-tolerant (OCR reads 作詞 as 作 詞)."""
    return r"\s*".join(word)


_CREDIT_WORDS = [
    "作詞", "作曲", "編曲", "作词", "编曲", "词曲", "詞曲",
    "監製", "监制", "導演", "导演", "製作", "制作",
    "出品", "發行", "发行", "版權", "版权",
]
_CREDIT_RE = re.compile("(" + "|".join(_ws_word(w) for w in _CREDIT_WORDS) + ")")
# "作詞：石國人" -> the credited name, so it's never picked as the singer.
# The value pattern tolerates OCR noise ("作 曲6石國人" — colon misread).
_CREDIT_VAL_RE = re.compile(
    "(?:" + "|".join(_ws_word(w) for w in _CREDIT_WORDS) + r")\s*[:：]?\s*(.+)$"
)
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def _credit_names(surface: str) -> set[str]:
    """Names credited on the card (作詞：石國人 -> {石國人})."""
    names: set[str] = set()
    m = _CREDIT_VAL_RE.search(surface)
    if m:
        # Trailing CJK run survives colon misreads ("作 曲6石國人").
        m2 = _CJK_RUN_RE.search(m.group(1))
        if m2:
            names.add(re.sub(r"\s+", "", m2.group(0)))
    return names
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


_LYRIC_PART_RE = re.compile(r"^(男|女)\s*[:：]")


def _is_lyric_part(t: str) -> bool:
    """Duet lyric-part marker (男:/女:) — a lyric line, never title/singer."""
    return bool(_LYRIC_PART_RE.match(t))


def _frame_size(fp: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(fp) as im:
            return im.size
    except Exception:
        return (0, 0)


def _read_frame(fp: Path, img_h: int = 0) -> list[tuple[str, float, float, float]]:
    """OCR one image with every loaded script model.

    Text detection runs once (it is script-independent); recognition runs
    once per script group and the results are merged. Returns
    [(text, conf, box_area, y_center_0to1)]. Never raises.
    """
    readers = _get_ocr_readers()
    if not readers:
        return []
    try:
        from easyocr.utils import reformat_input

        img, img_cv_grey = reformat_input(str(fp))
        primary = next(iter(readers.values()))
        horizontal_list, free_list = primary.detect(img, reformat=False)
        horizontal_list, free_list = horizontal_list[0], free_list[0]
    except Exception:
        return []
    out: list[tuple[str, float, float, float]] = []
    lyric_frame = False
    for reader in readers.values():
        try:
            results = reader.recognize(
                img_cv_grey, horizontal_list, free_list, reformat=False
            )
        except Exception:
            continue
        for bbox, text, conf in results:
            t = _clean_text(text)
            if _is_lyric_part(t):
                # Duet lyric-part marker (男:/女:): this frame is showing
                # lyrics, not the title card. The marker itself is dropped
                # below; its continuation lines are dropped afterwards.
                lyric_frame = True
                continue
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
    if lyric_frame:
        # In a lyric frame the bottom text is lyric lines (e.g. the
        # continuation under "女：…"), never title/singer.
        out = [(t, c, a, y) for (t, c, a, y) in out if y <= 0.68]
    return out


def ocr_image(image_path: Path) -> list[dict]:
    """OCR a single image file.

    Returns [{"text": ..., "conf": ...}] sorted by confidence desc,
    or [] on any failure (model missing, unreadable file, ...).
    """
    items = _read_frame(image_path)
    items.sort(key=lambda it: it[1], reverse=True)
    return [{"text": t, "conf": c} for t, c, _, _ in items]


def ocr_frames(frame_paths: list[Path]) -> list[dict]:
    """Run EasyOCR over frames and aggregate repeated text.

    Texts are cleaned (《》 wrappers stripped); lyricist/composer credits,
    duet lyric-part markers (男:/女:), watermarks and junk are dropped; and
    spacing variants ("江 南"/"江南") are merged. Each frame contributes at
    most one score per text (the best reader's — the script models must not
    multiply a score), and each text keeps only its 3 best frames, so a lyric
    line visible for 20 frames can't outrank a title card visible for 5.
    Persistent on-screen logos are downweighted, and text in the upper
    two-thirds of the frame (where title cards live; lyrics scroll along the
    bottom) is upweighted.

    Returns the top 15 as ``[{"text": ..., "score": ...}]`` sorted by score
    desc, or [] on any failure. Each entry also carries ``nframes``,
    ``max_area``, ``first_seen`` (0-based frame index), ``early`` (first seen
    in the first third of the scan — karaoke title cards live at the start)
    and ``overlay`` (visible in >80% of frames: a persistent logo, never
    title/singer content).
    """
    agg: dict[str, dict] = {}
    total = 0
    for fp in frame_paths:
        idx = total
        total += 1
        _, h = _frame_size(fp)
        best: dict[str, tuple[float, str, float, float]] = {}
        for t, conf, area, y in _read_frame(fp, h):
            key = re.sub(r"\s+", "", t)
            try:
                s = float(conf) * (1.0 + log1p(area))
            except Exception:
                s = 0.0
            prev = best.get(key)
            if prev is None or s > prev[0]:
                best[key] = (s, t, area, y)
        for key, (s, t, area, y) in best.items():
            d = agg.setdefault(
                key,
                {"text": t, "scores": [], "nframes": 0,
                 "max_area": 0.0, "y_sum": 0.0, "first_seen": idx},
            )
            d["scores"].append(s)
            d["nframes"] += 1
            d["y_sum"] += y
            if area > d["max_area"]:
                d["max_area"] = area
                d["text"] = t  # keep the surface form with the biggest box

    ranked = []
    for d in agg.values():
        s = sum(sorted(d["scores"], reverse=True)[:3])
        overlay = d["nframes"] > max(10, 0.8 * total)
        if overlay:
            s *= 0.25  # persistent overlay: watermark / logo
        y_avg = d["y_sum"] / max(1, d["nframes"])
        s *= 1.35 if y_avg <= 0.68 else 0.75  # title cards live up top
        ranked.append(
            {
                "text": d["text"],
                "score": s,
                "nframes": d["nframes"],
                "max_area": d["max_area"],
                "first_seen": d["first_seen"],
                "early": d["first_seen"] < total / 3.0,
                "overlay": overlay,
                "y_avg": y_avg,
            }
        )
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked[:15]


_ocr_diag_cache = None


def ocr_diagnostics() -> dict:
    """Self-test the OCR engine: load it, then OCR synthetic known text.

    Returns {"ok": bool, "stage": "load"|"selftest", "detail": str}.
    Result is cached per process. Never raises.
    """
    global _ocr_diag_cache
    if _ocr_diag_cache is not None:
        return _ocr_diag_cache
    readers = _get_ocr_readers()
    if not readers:
        detail = "; ".join(
            f"{g}: {e}" for g, e in _ocr_reader_errors.items()
        )[:300]
        _ocr_diag_cache = {
            "ok": False,
            "stage": "load",
            "detail": detail or "no OCR reader loaded",
        }
        return _ocr_diag_cache
    failed = "; ".join(
        f"{g}: {_ocr_reader_errors[g]}" for g in _ocr_reader_errors
    )[:200]
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (480, 140), "black")
        draw = ImageDraw.Draw(img)
        draw.text((30, 35), "Test 123 ABC", fill="white")
        tmp = Path(tempfile.gettempdir()) / "ktvocr_selftest.png"
        img.save(tmp)
        texts = [t for t, _, _, _ in _read_frame(tmp)]
        if any("Test" in t for t in texts):
            detail = (
                f"synthetic text detected "
                f"({len(readers)}/{len(_OCR_GROUPS)} script models loaded)"
            )
            if failed:
                detail += f"; failed: {failed}"
            _ocr_diag_cache = {"ok": True, "stage": "selftest", "detail": detail}
        else:
            _ocr_diag_cache = {
                "ok": False,
                "stage": "selftest",
                "detail": "engines loaded but detected nothing on synthetic text",
            }
    except Exception as exc:
        _ocr_diag_cache = {
            "ok": False,
            "stage": "selftest",
            "detail": f"{type(exc).__name__}: {exc}"[:300],
        }
    return _ocr_diag_cache


# ------------------------------------------------------- title / singer guess

# Whitespace-tolerant label matcher: "演唱：X", "演 唱 ： X", "SINGER: X" ...
_LABEL_RE_WS = re.compile(
    r"\s*(歌\s*手|歌\s*星|演\s*唱\s*者|演\s*唱|主\s*唱|原\s*唱"
    r"|歌\s*名|曲\s*名|曲\s*目|歌\s*曲"
    r"|artist|singer|title|song)\s*[:：]\s*(.+)",
    re.IGNORECASE,
)
_TITLE_LABELS = {"歌名", "曲名", "曲目", "歌曲", "title", "song"}
_SINGER_LABELS = {"歌手", "歌星", "演唱", "主唱", "原唱", "演唱者", "artist", "singer"}
# A bare label with no value ("演唱：" / "TITLE:") — never a guess.
_LABEL_ONLY_RE = re.compile(
    r"^(?:歌\s*手|歌\s*星|演\s*唱\s*者|演\s*唱|主\s*唱|原\s*唱"
    r"|歌\s*名|曲\s*名|曲\s*目|歌\s*曲"
    r"|artist|singer|title|song)\s*[:：]?\s*$",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _tidy_value(v: str) -> str:
    """Clean a guessed value: OCR-inserted spaces are noise inside CJK text."""
    v = (v or "").strip().strip("♪♫·•-–— ")
    if _CJK_RE.search(v):
        v = re.sub(r"\s+", "", v)
    else:
        v = re.sub(r"\s+", " ", v)
    return v.strip()


def guess_title_singer(candidates: list[dict]) -> tuple[str, str, str]:
    """Guess (title, singer, singer2) from ranked OCR candidates.

    1. Labeled lines (``歌名：X`` / ``歌手：Y``, whitespace-tolerant) win outright.
    2. Otherwise the title is the biggest text among the top-scoring
       candidates (karaoke title cards dominate the frame), preferring text
       first seen early (title cards live at the start; lyrics come later),
       and the singer is the next strongest distinct text.
    3. Singer 2 is an unlabeled second name on the card (duet
       "主唱：莊振凱" with "向蕙玲" on the next line): the strongest
       name-like (2-6 chars), early, distinct text in the singer zone.
    Credited names (作詞/作曲：…) are never picked as singers. Fallbacks
    never take persistent overlays (channel logos), and singers must sit
    near/below the title — never far above it where logos live. A wrong
    guess is worse than an empty one, so the fallbacks stay empty when
    nothing qualifies. Returns ("", "", "") when empty.
    """
    title = singer = ""
    pool: list[tuple[str, str, dict]] = []  # (spaceless key, surface, cand)
    seen: set[str] = set()
    credit_names: set[str] = set()
    for c in candidates or []:
        surface = (c.get("text") or "").strip()
        if not surface:
            continue
        key = re.sub(r"\s+", "", surface)
        if not key or key in seen:
            continue
        seen.add(key)
        if _is_credit(surface):
            # The credited person (作詞：石國人) is not the singer.
            credit_names |= _credit_names(surface)
            continue
        m = _LABEL_RE_WS.match(surface)
        if m:
            lbl = re.sub(r"\s+", "", m.group(1)).lower()
            val = _tidy_value(m.group(2))
            if val:
                if lbl in _TITLE_LABELS and not title:
                    title = val
                elif lbl in _SINGER_LABELS and not singer:
                    singer = val
                continue
        if _LABEL_ONLY_RE.match(key):
            continue
        pool.append((key, surface, c))

    def _key_of(v: str) -> str:
        return re.sub(r"\s+", "", v)

    def _usable(pool_entries):
        # Fallback picks never take persistent overlays (channel logos).
        return [e for e in pool_entries if not e[2].get("overlay")]

    def _title_y():
        # Vertical position of the title on the card, if known.
        if not title:
            return None
        tkey = _key_of(title)
        for key, _s, c in pool:
            if key == tkey and c.get("y_avg") is not None:
                return c["y_avg"]
        return None

    def _singer_zone(pool_entries, ty):
        # On a title card the singer sits near/below the title, never far
        # above it where channel logos live. Strict: a logo or lyric is
        # worse than leaving the guess empty.
        min_y = (ty - 0.1) if ty is not None else 0.35
        return [e for e in pool_entries if e[2].get("y_avg", 0.5) >= min_y]

    if not title or not singer:
        ranked = sorted(_usable(pool), key=lambda e: e[2].get("score", 0),
                        reverse=True)
        title_key, singer_key = _key_of(title), _key_of(singer)
        if not title and ranked:
            # The song title is the biggest text on a karaoke title card.
            # Prefer text first seen early: cards live at the start, lyrics
            # come later.
            top = ranked[:8]
            early = [e for e in top if e[2].get("early")]
            pick = max(early or top, key=lambda e: e[2].get("max_area", 0))
            title = _tidy_value(pick[1])
            title_key = _key_of(title)
        if not singer:
            ty = _title_y()
            cands = [e for e in ranked
                     if e[0] != title_key and e[0] not in credit_names]
            early = [e for e in cands if e[2].get("early")]
            zone = _singer_zone(early or cands, ty)
            if zone:
                singer = _tidy_value(zone[0][1])
    # Singer 2: unlabeled second name on the card (duet "主唱：莊振凱" with
    # "向蕙玲" on the next line). Name-like only (2-6 chars), on the card
    # (early), in the singer zone, never a credited name — so a lyric line
    # or logo can never be picked. Empty when nothing qualifies.
    singer2 = ""
    if singer:
        ty = _title_y()
        title_key, singer_key = _key_of(title), _key_of(singer)
        by_score = sorted(_usable(pool), key=lambda e: e[2].get("score", 0),
                          reverse=True)
        cands = [e for e in by_score
                 if e[0] not in (title_key, singer_key)
                 and e[0] not in credit_names
                 and 2 <= len(e[0]) <= 6
                 and e[2].get("early")]
        zone = _singer_zone(cands, ty)
        if zone:
            singer2 = _tidy_value(zone[0][1])
    return (title, singer, singer2)


# Duet markers: "A feat. B", "A ft B", "A vs B", "A & B", "A、B", "A+B" ...
# The word markers use (?<![a-zA-Z]) instead of \b on the left: _tidy_value
# strips spaces inside CJK text ("王菲 feat. 那英" -> "王菲feat.那英"), and
# there is no \b between a CJK char and "f". Still won't match inside English
# words ("defeat").
_DUET_SPLIT_RE = re.compile(
    r"(?<![a-zA-Z])(?:feat|ft|featuring|vs)\b\.?\s*|\s*(?:\+|＋|&|、)\s*",
    re.IGNORECASE,
)


def split_duet_singers(singer_text: str) -> tuple[str, str]:
    """Split a duet singer string into (singer1, singer2).

    Returns ``(text, "")`` when no duet marker is found.
    """
    parts = _DUET_SPLIT_RE.split((singer_text or "").strip(), maxsplit=1)
    if len(parts) == 2:
        a, b = _tidy_value(parts[0]), _tidy_value(parts[1])
        if a and b:
            return (a, b)
    return ((singer_text or "").strip(), "")


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


def extract_audio(video_path: Path, out_path: Path, secs: int = 30, start: int = 0) -> bool:
    """Extract ``secs`` seconds of audio (starting at ``start``) as 16 kHz mono WAV."""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(secs),
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
    ("", "detection failed") when the language is unknown, or
    ("", "error: <ExceptionType>: <message>") when transcription itself fails.
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
    except Exception as exc:
        return ("", f"error: {type(exc).__name__}: {exc}"[:120])


# ------------------------------------------------------------------- filename

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize(part: str) -> str:
    """Strip filesystem-hostile characters, collapse whitespace, cap length."""
    s = _INVALID_CHARS.sub("", part or "")
    s = _CONTROL_CHARS.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def build_filename(
    singer: str, title: str, language: str, category: str, ext: str, singer2: str = ""
) -> str:
    """Build ``singer-title-language-category.ext`` from sanitized parts.

    Duets become ``singer1&singer2-title-language-category.ext``.
    """
    singer_part = f"{singer}&{singer2}" if (singer2 or "").strip() else singer
    parts = [sanitize(singer_part), sanitize(title), sanitize(language), sanitize(category)]
    if not ext.startswith("."):
        ext = "." + ext
    return "-".join(parts) + ext
