# KTV OCR Renamer

Rename ~10,000 karaoke music videos to
`singer-songName-language-songCategory.ext`, e.g.
`林俊傑-江南-國語-男歌星.mkv`.

Doing this by hand means opening every video, reading the on-screen song
title and singer, listening for the language, deciding the category, and
retyping the filename — 10,000 times. This app automates the grunt work:

1. **Frames** — grabs 1 frame/sec from the first 30 s with ffmpeg.
2. **OCR** — EasyOCR (`en` / `ch_tra` / `ch_sim` / `ja` / `ko`) reads on-screen
   text; repeated text is ranked by confidence × text size so title cards beat
   watermarks.
3. **Language** — faster-whisper transcribes the first 30 s of audio and
   reports the detected language.
4. **You confirm** — the web UI shows frame thumbnails plus OCR candidates with
   one-click **歌手 / 歌名** assign buttons, a live filename preview, and then
   saves a **copy** under the new name.

## Install

```bash
# system dependency (needed for frame + audio extraction)
sudo apt install ffmpeg        # macOS: brew install ffmpeg

cd ktvocr/app
pip install -r requirements.txt
```

> First run downloads the EasyOCR and faster-whisper models (~1–2 GB).
> ffmpeg must be installed and on PATH.

## Web UI (one video at a time)

```bash
cd ktvocr/app
uvicorn main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

1. Drop a karaoke video onto the page (or choose a file) → **Analyze**.
2. Watch the preview, click candidate chips to fill the Singer / Title fields.
3. Pick language + category, check the live filename preview.
4. **Rename & Save** copies the file to `output/<new name>` (original untouched).
5. **Next song** resets for the next file.

Uploads land in `uploads/`, renamed copies in `output/`, frame thumbnails in
`static/frames/`. The UI works offline — no CDN dependencies.

## Batch mode (the 10,000-file backlog)

```bash
cd ktvocr/app

# 1) scan everything, write machine guesses for human review
python batch.py scan /path/to/videos -o guesses.csv --secs 30

# 2) open guesses.csv in Excel:
#    - fix the *_final columns (prefilled with the guesses)
#    - put "skip" in status for rows to leave alone

# 3) apply the reviewed CSV (copies files, never moves them)
python batch.py apply guesses.csv --outdir renamed/
# -> writes renamed/guesses.applied.csv with per-row results
```

`guesses.csv` columns:

```
original_path, title_guess, singer_guess, language_guess, language_note,
category_guess, title_final, singer_final, language_final, category_final,
new_name, status
```

## Filename format

`singer-songName-language-songCategory.ext`

- Languages: 英語 國語 日語 韓語 台語 粵語
- Categories: 男歌星 女歌星 團體 合唱 外國男 外國女 外國團體

Examples:

- `林俊傑-江南-國語-男歌星.mkv`
- `宇多田ヒカル-First Love-日語-女歌星.mp4`
- `BTS-Dynamite-韓語-團體.mp4`

## Language notes

- Whisper **cannot distinguish 台語 (Hokkien) from 國語 (Mandarin)** — both come
  back as `zh` → mapped to 國語. If the song is Taiwanese Hokkien, set 台語
  manually.
- Cantonese is detected as `yue` → mapped to 粵語.
- Very short intros or instrumental-only openings can misdetect; the UI always
  lets you override the guess.

## Accuracy caveats

- **OCR guesses need human confirmation.** Karaoke videos love decorative fonts,
  scrolling lyrics and watermarks — that is why every candidate chip has
  one-click assign buttons instead of auto-renaming.
- If the title card appears after 30 s, re-run with a longer window
  (`--secs 60` in batch, or edit the `secs=30` calls in `main.py`).
- The app **copies** rather than moves/renames in place, so a bad rename never
  destroys the original file.
- Filenames are sanitized (`\/:*?"<>|` and control characters removed,
  whitespace collapsed, 120-char cap per part).

## Docker

```bash
cd ktvocr/app
docker build -t ktvocr .
docker run -p 8000:8000 -v "$PWD/output:/srv/app/output" ktvocr
```
