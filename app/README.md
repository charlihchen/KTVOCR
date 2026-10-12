# KTV OCR Renamer

Rename ~10,000 karaoke music videos to
`singer-songName-language-songCategory.ext`, e.g.
`林俊傑-江南-國語-男歌星.mkv`.

Doing this by hand means opening every video, reading the on-screen song
title and singer, listening for the language, deciding the category, and
retyping the filename — 10,000 times. This app automates the grunt work:

1. **Frames** — grabs 1 frame/sec from the first 30 s with ffmpeg.
2. **OCR** — EasyOCR reads on-screen text with one model each for Traditional
   Chinese, Simplified Chinese, Japanese and Korean (each paired with English;
   EasyOCR allows only one CJK script per reader, so detection runs once per
   frame and every script model reads the same boxes, results merged)
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

### macOS

```bash
# ffmpeg (needs Homebrew: https://brew.sh)
brew install ffmpeg

cd ktvocr/app
python3 -m pip install -r requirements.txt
python3 batch.py check     # verifies ffmpeg + OCR engine + whisper
```

> Apple Silicon Macs: `pip` installs the right torch build automatically and
> EasyOCR always runs on CPU — no extra setup. If `batch.py scan` ever gives
> you empty guesses, run `python3 batch.py check` first: it tells you exactly
> which piece is broken and how to fix it.

### Windows

```bat
:: ffmpeg (needs admin for winget; otherwise get a build from gyan.dev/ffmpeg/builds
:: and add its bin folder to PATH)
winget install Gyan.FFmpeg

cd ktvocr\app
py -m pip install -r requirements.txt
py -m uvicorn main:app --host 127.0.0.1 --port 8000
:: open http://127.0.0.1:8000 in your browser
```

If `uvicorn` is "not recognized", you skipped the install step or your
terminal doesn't see Python's Scripts folder — the `py -m` prefix above
bypasses the PATH problem entirely. (Use `python` instead of `py` if that
is what works on your machine.)

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

# 0) sanity check first (tells you exactly what is broken, if anything)
python batch.py check

# 1) scan everything, write machine guesses for human review
python batch.py scan /path/to/videos -o guesses.csv --secs 30

# 2) open guesses.csv in Excel:
#    - fix the *_final columns (prefilled with the guesses)
#    - put "skip" in status for rows to leave alone
#    - save via "CSV UTF-8 (Comma delimited)" if offered, so CJK text
#      survives the round trip (`apply` also tolerates plain Excel saves)

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
- The guesser ignores lyricist/composer credits (作詞/作曲), channel watermarks
  and junk text, merges spacing variants ("江 南"/"江南"), downweights text
  stuck on screen the whole clip, and prefers large text in the upper
  two-thirds of the frame where title cards live (lyrics scroll at the
  bottom). Labeled cards (`歌名：…` / `歌手：…`, whitespace-tolerant) always
  win when found; otherwise the title is the biggest text among the top
  candidates and the singer the next strongest — bare labels like `演唱：`
  are never used as guesses.
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

## Web UI tips

- **Language and category start empty.** They are only pre-selected when the
  automatic detection actually found something; otherwise you choose them —
  nothing silently defaults to 英語/男歌星.
- **Sampled frames are clickable.** Click any frame thumbnail to see the OCR
  text found in that specific frame, with the same one-click Singer/Title
  assign buttons.
- **Title card appears later in the video?** Pause the video on the title card
  and press **"OCR frame at current video position"** — the app grabs that
  exact frame and OCRs it. Useful when the intro runs long.
- **Warnings appear under the results heading** when something failed, e.g.
  frames could not be extracted (ffmpeg missing) or no text was found — so a
  silent empty result is always explained.
- **If OCR finds nothing on any frame**, the app self-tests the OCR engine on
  synthetic text and tells you whether the engine itself is broken (with the
  exact error and a fix: delete `%USERPROFILE%\.EasyOCR\model` and restart to
  re-download) or whether it simply saw no text in your video.
