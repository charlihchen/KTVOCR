#!/usr/bin/env python3
"""Simple OCR test to verify EasyOCR is working."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def test_ocr_basic():
    print("Testing EasyOCR basic functionality...")

    try:
        from easyocr import Reader
        print("  ✓ EasyOCR imported successfully")
    except ImportError as e:
        print(f"  ✗ EasyOCR import failed: {e}")
        return False

    try:
        # Create reader with minimal languages
        reader = Reader(['en'], gpu=False)
        print("  ✓ EasyOCR Reader created")
    except Exception as e:
        print(f"  ✗ EasyOCR Reader creation failed: {e}")
        return False

    try:
        # Create a test image with known text
        from PIL import Image, ImageDraw
        import tempfile

        img = Image.new("RGB", (640, 120), "black")
        draw = ImageDraw.Draw(img)
        draw.text((30, 20), "HONG KONG - ABBA - Dancing Queen", fill="white")

        tmp = Path(tempfile.gettempdir()) / "ktvocr_test_img.jpg"
        img.save(tmp)

        # Test OCR on the image
        result = reader.readtext(str(tmp))
        print(f"  ✓ OCR test successful, got {len(result)} results")

        for bbox, text, conf in result[:3]:
            print(f"    [{conf:.2f}] {text}")

        tmp.unlink()
        return True
    except Exception as e:
        print(f"  ✗ OCR test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pipeline_imports():
    print("\nTesting pipeline imports...")
    try:
        from pipeline import (
            MIN_CONFIDENCE,
            _is_junk,
            _is_valid_title,
            _is_valid_singer,
            _GARBAGE_RE,
            _NUMERIC_SYMBOLIC_RE
        )
        print("  ✓ All pipeline functions imported")
        print(f"  ✓ MIN_CONFIDENCE = {MIN_CONFIDENCE}")

        # Test garbage detection
        print("\n  Testing garbage detection:")
        test_cases = ["???", "###", "37%", "ABBA", "江南", "Dancing Queen"]
        for tc in test_cases:
            is_junk = _is_junk(tc)
            is_valid = _is_valid_title(tc) if len(tc) > 3 else _is_valid_singer(tc)
            status = "GARBAGE" if is_junk else "VALID"
            print(f"    '{tc}': {status}")

        return True
    except Exception as e:
        print(f"  ✗ Import test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = True
    success = test_ocr_basic() and success
    success = test_pipeline_imports() and success

    print(f"\n{'='*40}")
    if success:
        print("All tests passed!")
    else:
        print("Some tests failed - check output above")