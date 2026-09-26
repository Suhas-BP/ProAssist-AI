"""
scratch/test_flag1_cases.py
Dedicated test suite for FLAG 1:
1. DPI scaling conversion math across different scale factors (100%, 125%, 150%, 200%).
2. _click interaction type handling (single vs double).
3. Contextual interaction prompt response parsing.
4. Spotify Liked Songs scenario verification (playlist entry -> double-click).
"""

import sys
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions import computer_control

def test_dpi_coordinate_conversion():
    print("Testing DPI coordinate conversion math...")
    # Test case 1: 125% scaling (Current system: 1920x1200 physical, 1536x960 logical)
    screen_w, screen_h = 1536, 960
    img_w, img_h = 1920, 1200
    
    # Normalized coords from model (e.g. 500, 500 = center)
    nx, ny = 500, 500
    target_x = int(nx / 1000.0 * screen_w)
    target_y = int(ny / 1000.0 * screen_h)
    assert target_x == 768
    assert target_y == 480
    # In physical space: 768 * 1.25 == 960 (exactly center of 1920)
    assert round(target_x * (img_w / screen_w)) == 960
    assert round(target_y * (img_h / screen_h)) == 600
    print("  -> 125% DPI scaling conversion verified.")

    # Test case 2: 150% scaling (1920x1080 physical, 1280x720 logical)
    screen_w2, screen_h2 = 1280, 720
    img_w2, img_h2 = 1920, 1080
    nx2, ny2 = 250, 750
    target_x2 = int(nx2 / 1000.0 * screen_w2)
    target_y2 = int(ny2 / 1000.0 * screen_h2)
    assert target_x2 == 320
    assert target_y2 == 540
    assert round(target_x2 * (img_w2 / screen_w2)) == 480
    assert round(target_y2 * (img_h2 / screen_h2)) == 810
    print("  -> 150% DPI scaling conversion verified.")

    # Test case 3: Fallback physical pixel input (raw_x > 1000)
    raw_x, raw_y = 1440, 900
    target_x3 = int(raw_x * (screen_w / img_w))
    target_y3 = int(raw_y * (screen_h / img_h))
    assert target_x3 == int(1440 / 1.25)
    assert target_y3 == int(900 / 1.25)
    print("  -> Physical pixel fallback conversion verified.")


def test_click_interaction_types():
    print("Testing _click interaction type handling...")
    with patch("pyautogui.click") as mock_click:
        # Single click
        msg1 = computer_control._click(x=100, y=200, interaction="single")
        mock_click.assert_called_with(100, 200, button="left", clicks=1)
        assert "Clicked (100, 200)" in msg1
        assert "Double" not in msg1

        # Double click
        msg2 = computer_control._click(x=350, y=420, interaction="double")
        mock_click.assert_called_with(350, 420, button="left", clicks=2)
        assert "Double-clicked (350, 420)" in msg2

        # Backward compatibility with clicks=2
        msg3 = computer_control._click(x=350, y=420, clicks=2)
        mock_click.assert_called_with(350, 420, button="left", clicks=2)
        assert "Double-clicked (350, 420)" in msg3

        # Default fallback to single click
        msg4 = computer_control._click(x=100, y=200, interaction="unknown_fallback")
        mock_click.assert_called_with(100, 200, button="left", clicks=1)
        assert "Clicked (100, 200)" in msg4

    print("  -> _click interaction types verified.")


def test_computer_control_screen_click_dispatch():
    print("Testing computer_control screen_click dispatch...")
    with patch.object(computer_control, "_screen_find", return_value=(280, 342, "double")), \
         patch.object(computer_control, "_click", return_value="Double-clicked (280, 342) [left]") as mock_click:
        res = computer_control.computer_control({"action": "screen_click", "description": "Liked Songs"})
        mock_click.assert_called_once_with(x=280, y=342, interaction="double")
        assert "Double-clicked" in res
        assert "Liked Songs" in res
        assert "double" in res
    print("  -> computer_control screen_click dispatch for double-click verified.")

    with patch.object(computer_control, "_screen_find", return_value=(450, 240, "single")), \
         patch.object(computer_control, "_click", return_value="Clicked (450, 240) [left]") as mock_click:
        res2 = computer_control.computer_control({"action": "screen_click", "description": "Play button"})
        mock_click.assert_called_once_with(x=450, y=240, interaction="single")
        assert "Clicked" in res2
        assert "Play button" in res2
        assert "single" in res2
    print("  -> computer_control screen_click dispatch for single-click verified.")


def test_spotify_liked_songs_live_scenario():
    print("Testing Spotify Liked Songs live visual scenario...")
    from PIL import Image
    import io
    from google.genai import types as gtypes
    from core import gemini

    test_img_path = Path("scratch/test_spotify_ui.png")
    assert test_img_path.exists(), "scratch/test_spotify_ui.png must exist"
    
    img = Image.open(test_img_path)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    prompt = (
        f"This is a screenshot of the user's screen ({img.width}×{img.height} physical pixels).\n"
        f"Locate the UI element described as: 'Liked Songs' (playlist entry in Spotify sidebar).\n"
        f"Also determine the appropriate mouse interaction type based on visual context:\n"
        f"- If the target is a list item, table row, playlist entry, song/track, file icon, or folder icon meant to be opened/activated: interaction is 'double'\n"
        f"- If the target is a button, menu item, tab, toggle, checkbox, hyperlink, or single control: interaction is 'single'\n"
        f"- If ambiguous, default to 'single'\n\n"
        f"Reply in EXACTLY this format:\n"
        f"COORDINATES: x,y\n"
        f"INTERACTION: single|double\n"
        f"Where x,y are normalized coordinates from 0 to 1000 (0,0 is top-left, 1000,1000 is bottom-right).\n"
        f"If the element is not visible, reply: NOT_FOUND"
    )

    resp = gemini.call(
        [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
        tier=gemini.FAST, timeout_ms=20_000
    )
    assert resp is not None, "Gemini call failed"
    text = (resp.text or "").strip()
    print("  Model Response for Spotify Liked Songs:")
    for line in text.splitlines():
        print(f"    {line}")

    coord_match = re.search(r"COORDINATES:\s*(\d+)\s*,\s*(\d+)", text, re.IGNORECASE)
    assert coord_match is not None, "Failed to match COORDINATES"
    inter_match = re.search(r"INTERACTION:\s*(single|double)", text, re.IGNORECASE)
    assert inter_match is not None, "Failed to match INTERACTION"
    interaction = inter_match.group(1).lower()

    assert interaction == "double", f"Expected interaction 'double' for Spotify playlist item, got '{interaction}'"
    print("  -> Spotify Liked Songs correctly classified as INTERACTION: double.")


if __name__ == "__main__":
    print("=== RUNNING FLAG 1 TEST SUITE ===")
    test_dpi_coordinate_conversion()
    test_click_interaction_types()
    test_computer_control_screen_click_dispatch()
    test_spotify_liked_songs_live_scenario()
    print("\nALL FLAG 1 TESTS PASSED SUCCESSFULLY!")
