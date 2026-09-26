import sys
import io
import re
from pathlib import Path
from PIL import Image

sys.path.insert(0, r"d:\Mark-LIV-main")
from core import gemini
from google.genai import types as gtypes

img = Image.open(r"d:\Mark-LIV-main\scratch\test_spotify_ui.png")
buf = io.BytesIO()
img.save(buf, format="PNG")
image_bytes = buf.getvalue()

targets = [
    ("Liked Songs", "playlist entry in sidebar"),
    ("Play button", "green round play button in main area"),
]

for target, desc in targets:
    prompt = (
        f"This is a screenshot of the user's screen. "
        f"Locate the UI element described as: '{target}' ({desc}).\n"
        f"Also determine the appropriate mouse interaction type based on visual context:\n"
        f"- If the target is a list item, table row, playlist entry, song/track, file icon, or folder icon meant to be opened/activated: interaction is 'double'\n"
        f"- If the target is a button, menu item, tab, toggle, checkbox, hyperlink, or single control: interaction is 'single'\n"
        f"- If ambiguous, default to 'single'\n\n"
        f"Reply in EXACTLY this format:\n"
        f"COORDINATES: x,y\n"
        f"INTERACTION: single|double\n"
        f"Where x,y are normalized coordinates from 0 to 1000 (0,0 is top-left, 1000,1000 is bottom-right).\n"
        f"If not visible, reply: NOT_FOUND"
    )

    print(f"\n--- Testing Target: '{target}' ---")
    resp = gemini.call(
        [gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
        tier=gemini.FAST, timeout_ms=20_000
    )
    if resp:
        print("Model Response:\n", (resp.text or "").strip())
    else:
        print("Model returned None")
