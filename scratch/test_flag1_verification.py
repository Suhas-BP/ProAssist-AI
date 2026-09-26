"""
scratch/test_flag1_verification.py
Verification suite for Flag 1:
1. Full end-to-end trace of Spotify "Liked Songs" test:
   - Live Gemini Vision call on scratch/test_spotify_ui.png (1920x1200)
   - Raw model response text
   - Regex extraction of raw_x, raw_y, interaction
   - Branch condition evaluation (normalized vs fallback)
   - Exact conversion arithmetic:
       Logical 125% scale (1536x960):
         target_x = int(raw_x / 1000.0 * 1536)
         target_y = int(raw_y / 1000.0 * 960)
   - Final pyautogui.click() call
   - Explicit reconciliation of (182, 357) -> (279, 342)
2. Dedicated test for physical-pixel-fallback branch:
   - Simulated Gemini response returning large physical pixel values (e.g. 1450, 820)
   - Confirms fallback branch is taken (1450 > 1000)
   - Exact conversion arithmetic:
         target_x = int(1450 * (1536 / 1920)) = 1160
         target_y = int(820 * (960 / 1200)) = 656
   - Final pyautogui.click(1160, 656, button='left', clicks=1)
"""

import sys
import io
import re
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions import computer_control
from core import gemini
from google.genai import types as gtypes


def run_spotify_liked_songs_full_trace():
    print("=" * 70)
    print("TASK 1: FULL END-TO-END TRACE — SPOTIFY 'LIKED SONGS'")
    print("=" * 70)

    # 1. Load test image
    img_path = Path("scratch/test_spotify_ui.png")
    assert img_path.exists(), f"Missing test image: {img_path}"
    test_img = Image.open(img_path)
    img_w, img_h = test_img.size
    print(f"[1] Test image loaded: {img_path} ({img_w}×{img_h} physical pixels)")

    # 2. Call live Gemini Vision with exact prompt from _screen_find
    buf = io.BytesIO()
    test_img.save(buf, format="PNG")
    image_bytes = buf.getvalue()

    description = "Liked Songs (playlist entry in Spotify sidebar)"
    prompt = (
        f"This is a screenshot of the user's screen ({img_w}×{img_h} physical pixels).\n"
        f"Locate the UI element described as: '{description}'.\n"
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

    print("\n[2] Sending live request to Gemini model ladder (FAST tier)...")
    resp = gemini.call(
        [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
        tier=gemini.FAST, timeout_ms=20_000,
    )
    assert resp is not None, "Gemini API call failed!"
    raw_response_text = (resp.text or "").strip()
    print("\n--- RAW GEMINI RESPONSE TEXT ---")
    print(raw_response_text)
    print("--------------------------------")

    # 3. Parse coordinates and interaction type
    coord_match = re.search(r"COORDINATES:\s*(\d+)\s*,\s*(\d+)", raw_response_text, re.IGNORECASE)
    if not coord_match:
        coord_match = re.search(r"(\d+)\s*,\s*(\d+)", raw_response_text)
    assert coord_match is not None, f"Failed to parse coordinates from: {raw_response_text}"
    raw_x = int(coord_match.group(1))
    raw_y = int(coord_match.group(2))

    interaction = "single"
    inter_match = re.search(r"INTERACTION:\s*(single|double)", raw_response_text, re.IGNORECASE)
    if inter_match:
        interaction = inter_match.group(1).lower()

    print(f"\n[3] Parsed model outputs:")
    print(f"    raw_x: {raw_x}")
    print(f"    raw_y: {raw_y}")
    print(f"    interaction: '{interaction}'")

    # 4. Branch evaluation & Coordinate conversion math under 125% DPI scaling
    # Logical resolution at 125% scaling on 1920x1200 physical display:
    screen_w, screen_h = 1536, 960
    print(f"\n[4] Display parameters:")
    print(f"    Physical screenshot: {img_w}×{img_h}")
    print(f"    Logical desktop (125% DPI scale): {screen_w}×{screen_h}")

    condition_normalized = (raw_x <= 1000 and raw_y <= 1000 and (img_w > 1000 or img_h > 1000))
    print(f"    Condition check: raw_x <= 1000 ({raw_x <= 1000}) and raw_y <= 1000 ({raw_y <= 1000}) and img > 1000 ({img_w > 1000}) -> {condition_normalized}")

    if condition_normalized:
        branch_taken = "NORMALIZED (0..1000)"
        target_x = int(raw_x / 1000.0 * screen_w)
        target_y = int(raw_y / 1000.0 * screen_h)
        calc_str_x = f"int({raw_x} / 1000.0 * {screen_w}) = int({raw_x / 1000.0 * screen_w}) = {target_x}"
        calc_str_y = f"int({raw_y} / 1000.0 * {screen_h}) = int({raw_y / 1000.0 * screen_h}) = {target_y}"
    else:
        branch_taken = "PHYSICAL-PIXEL FALLBACK"
        target_x = int(raw_x * (screen_w / img_w))
        target_y = int(raw_y * (screen_h / img_h))
        calc_str_x = f"int({raw_x} * ({screen_w} / {img_w})) = {target_x}"
        calc_str_y = f"int({raw_y} * ({screen_h} / {img_h})) = {target_y}"

    print(f"\n[5] Conversion branch taken: {branch_taken}")
    print(f"    target_x arithmetic: {calc_str_x}")
    print(f"    target_y arithmetic: {calc_str_y}")
    print(f"    Computed target logical coordinates: ({target_x}, {target_y})")

    # 5. Execute via computer_control & intercept pyautogui.click()
    print(f"\n[6] Testing final execution via computer_control screen_click dispatch...")
    with patch("pyautogui.size", return_value=(screen_w, screen_h)), \
         patch("pyautogui.screenshot", return_value=test_img), \
         patch("core.gemini.call", return_value=resp), \
         patch("pyautogui.click") as mock_click:
        
        result_msg = computer_control.computer_control({
            "action": "screen_click",
            "description": "Liked Songs (playlist entry in Spotify sidebar)"
        })

        print(f"    computer_control return message: '{result_msg}'")
        print(f"    pyautogui.click call: {mock_click.call_args_list}")
        
        # Verify exact call
        mock_click.assert_called_once_with(target_x, target_y, button="left", clicks=2 if interaction == "double" else 1)
        print(f"    VERIFIED: pyautogui.click called with ({target_x}, {target_y}, button='left', clicks={2 if interaction == 'double' else 1})")

    # 6. Explicit Reconciliation
    print("\n[7] EXPLICIT RECONCILIATION:")
    print(f"    - Raw model normalized coordinate: raw_x={raw_x}, raw_y={raw_y}")
    print(f"    - System logical display dimensions: screen_w={screen_w}, screen_h={screen_h}")
    print(f"    - Arithmetic for target_x: {raw_x} / 1000 * {screen_w} = {raw_x / 1000.0 * screen_w:.3f} -> int = {target_x}")
    print(f"    - Arithmetic for target_y: {raw_y} / 1000 * {screen_h} = {raw_y / 1000.0 * screen_h:.3f} -> int = {target_y}")
    if raw_x == 182 and raw_y == 357:
        print(f"    - RECONCILIATION MATCH: raw (182, 357) yields exactly ({target_x}, {target_y}) = (279, 342)!")
    else:
        print(f"    - Note: Live model returned raw ({raw_x}, {raw_y}) on this run, yielding exactly ({target_x}, {target_y}).")
        print(f"      If the model returned (182, 357):")
        print(f"        target_x = int(182 / 1000.0 * 1536) = int(279.552) = 279")
        print(f"        target_y = int(357 / 1000.0 * 960)  = int(342.720) = 342")
        print(f"      The mathematical connection between (182, 357) and (279, 342) is 100% exact.")


def run_physical_pixel_fallback_dedicated_test():
    print("\n" + "=" * 70)
    print("TASK 2: DEDICATED TEST — PHYSICAL-PIXEL FALLBACK BRANCH")
    print("=" * 70)

    # 1. Setup mock response with large pixel values (ignoring 0..1000 normalized instruction)
    simulated_raw_x = 1450
    simulated_raw_y = 820
    simulated_response_text = f"COORDINATES: {simulated_raw_x},{simulated_raw_y}\nINTERACTION: single"
    
    mock_resp = MagicMock()
    mock_resp.text = simulated_response_text

    screen_w, screen_h = 1536, 960
    img_w, img_h = 1920, 1200
    mock_img = Image.new("RGB", (img_w, img_h), color="black")

    print(f"[1] Simulated Gemini Vision Response:")
    print(f"    '{simulated_response_text.replace(chr(10), ' | ')}'")
    print(f"    Parsed raw_x={simulated_raw_x}, raw_y={simulated_raw_y}")

    # 2. Trace branch condition
    cond_normalized = (simulated_raw_x <= 1000 and simulated_raw_y <= 1000 and (img_w > 1000 or img_h > 1000))
    print(f"\n[2] Branch Condition Check in _screen_find:")
    print(f"    raw_x <= 1000: {simulated_raw_x} <= 1000 -> {simulated_raw_x <= 1000} (FALSE!)")
    print(f"    Normalized condition: {cond_normalized}")
    assert not cond_normalized, "Normalized condition should be FALSE for physical pixel coordinates > 1000!"
    print("    -> Confirmed: Branch evaluates to FALSE, routing into 'else:' fallback branch.")

    # 3. Fallback arithmetic
    # target_x = int(raw_x * (screen_w / img_w))
    # target_y = int(raw_y * (screen_h / img_h))
    expected_target_x = int(simulated_raw_x * (screen_w / img_w))  # int(1450 * (1536 / 1920)) = int(1450 * 0.8) = 1160
    expected_target_y = int(simulated_raw_y * (screen_h / img_h))  # int(820 * (960 / 1200)) = int(820 * 0.8) = 656
    print(f"\n[3] Fallback Coordinate Calculation:")
    print(f"    target_x = int({simulated_raw_x} * ({screen_w} / {img_w})) = int({simulated_raw_x} * {screen_w/img_w}) = {expected_target_x}")
    print(f"    target_y = int({simulated_raw_y} * ({screen_h} / {img_h})) = int({simulated_raw_y} * {screen_h/img_h}) = {expected_target_y}")
    assert expected_target_x == 1160
    assert expected_target_y == 656

    # 4. End-to-end execution through _screen_find and computer_control
    print(f"\n[4] Executing through _screen_find and computer_control dispatch:")
    with patch("pyautogui.size", return_value=(screen_w, screen_h)), \
         patch("pyautogui.screenshot", return_value=mock_img), \
         patch("core.gemini.call", return_value=mock_resp), \
         patch("pyautogui.click") as mock_click:

        # Test _screen_find directly
        found = computer_control._screen_find("some button")
        assert found is not None
        fx, fy, finter = found
        print(f"    _screen_find returned: x={fx}, y={fy}, interaction='{finter}'")
        assert fx == expected_target_x, f"Expected fx={expected_target_x}, got {fx}"
        assert fy == expected_target_y, f"Expected fy={expected_target_y}, got {fy}"
        assert finter == "single"

        # Test computer_control screen_click
        res = computer_control.computer_control({"action": "screen_click", "description": "some button"})
        print(f"    computer_control return: '{res}'")
        mock_click.assert_called_once_with(1160, 656, button="left", clicks=1)
        print(f"    pyautogui.click call: {mock_click.call_args_list}")
        print("    -> Confirmed: Fallback branch produced accurate final click at (1160, 656) with clicks=1.")


if __name__ == "__main__":
    run_spotify_liked_songs_full_trace()
    run_physical_pixel_fallback_dedicated_test()
    print("\n" + "=" * 70)
    print("ALL VERIFICATION CHECKS COMPLETED SUCCESSFULLY!")
    print("=" * 70)
