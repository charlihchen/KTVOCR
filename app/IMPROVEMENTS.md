# KTVOCR OCR Accuracy Improvements

## Summary of Issues Found

After analyzing the codebase and existing CSV data, the main issues causing poor title/singer guessing accuracy are:

1. **CSV encoding problems** - Paths show `??` instead of Chinese characters (e.g., 國語)
2. **SMB/Windows path encoding mismatch** - Characters encoded differently than UTF-8
3. **Low OCR confidence threshold** - Garbage text like `3>%`, `##`, `???` passing through
4. **Missing validation** - No verification that guessed text looks like valid titles/singers
5. **Silent failures** - ffmpeg errors hidden, making diagnosis difficult

## Changes Made to `pipeline.py`

### 1. Enhanced Garbage Detection (`_is_junk`)
Added patterns to catch more OCR misreads:

```python
# Patterns for garbage text - single repeated chars or common OCR artifacts
_GARBAGE_RE = re.compile(r"^[?！#〝「』《》【】、：；，。！？！@%$^*()]+$")
_NUMERIC_SYMBOLIC_RE = re.compile(r"^[0-9!?#%$^*〝@]+$")

# Check for all same characters (e.g., "####", "????")
if len(set(t)) == 1:
    return True

# For short text, require at least some alphabetic content
if len(t) <= 10:
    alpha_count = sum(1 for c in t if c.isalpha())
    if alpha_count < 2:
        return True
```

### 2. Added Title/Singer Validation Functions
New validation functions that check if text looks like valid content:

```python
_EN_TITLE_RE = re.compile(r"^[a-zA-Z0-9\s\'\-\.\(\)&]+$")
_EN_SINGER_RE = re.compile(r"^[a-zA-Z0-9\s\'\-\.&]+$")

def _is_valid_title(t: str) -> bool:
    # CJK titles - must have valid CJK characters
    # English titles - must have at least 2 letters
    # Mixed language - must have some meaningful content

def _is_valid_singer(s: str) -> bool:
    # CJK singer names - valid CJK characters
    # English names - allow &, -, ', space
    # Mixed language validation
```

### 3. Updated Fallback Logic
Title and singer fallbacks now only accept validated text:

```python
candidate_title = _tidy_value(pick[1])
# IMPROVEMENT: Only accept if it looks like a valid title
if _is_valid_title(candidate_title):
    title = candidate_title
```

### 4. Added Confidence Threshold
Minimum OCR confidence of 0.65 (configurable):

```python
MIN_CONFIDENCE = 0.65
```

Low-confidence text is filtered out during `_read_frame()`.

## New Diagnostic Tool: `diagnose.py`

Created a diagnostic tool to help identify issues:

```bash
python diagnose.py --test-ocr           # Test OCR with synthetic image
python diagnose.py --video /path/video  # Test path resolution and OCR
python diagnose.py --csv guesses.csv    # Analyze CSV for patterns
```

## Additional Improvements in `audit_guesses.py`

Added garbage text detection to the audit output:

```python
print("\n== garbage text suspects (repetitive symbols, numbers) ==")
# Detect patterns like "???", "###", "37%", etc.
```

## Recommendations for Further Improvement

### 1. Fix Path Encoding (High Priority)
The fundamental issue is that Windows SMB shares often use GBK encoding for Chinese filenames. When Python reads paths, they get garbled.

**Solution**: Detect and use proper encoding:
```python
def read_smb_path(path_str: str) -> str:
    # Try UTF-8 first, then GBK fallback
    try:
        return path_str.encode('utf-8').decode('utf-8')
    except UnicodeDecodeError:
        return path_str.encode('gbk').decode('gbk')
```

### 2. Add Debug Logging for ffmpeg
Currently errors are silently swallowed. Add:

```python
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    logging.warning(f"ffmpeg failed: {result.stderr}")
```

### 3. Add File Existence Validation
Before processing, verify the file exists:

```python
if not video_path.exists():
    logging.error(f"Video not found: {video_path}")
    return []
```

### 4. Consider Song ID Integration
The `songid.py` (Shazam-style recognition) works but is opt-in. Consider:
- Running it automatically as a fallback when OCR fails
- Using it to verify guessed titles

### 5. Add Character Set Detection
Different karaoke platforms use different character sets. Detect and handle:
- Traditional vs Simplified Chinese
- Japanese (with furigana annotations)
- Korean (with hanja/kana mixed)

## Expected Improvement

With the current changes:
- **Before**: ~90% empty/garbage guesses
- **After**: Should reduce garbage significantly, though the path encoding issue may still cause frame extraction failures

To see real improvement, the path encoding issue MUST be resolved - otherwise no frames are extracted and all guesses come from fallback OCR on the video's first few frames.