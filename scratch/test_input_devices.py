import sys
import time
from pathlib import Path
import numpy as np

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

import sounddevice as sd
from core.audio_devices import resolve, list_devices

print("Testing input devices:")
devices = ["", "Microphone Array (2- Realtek(R) Audio)", "Headset (Noise Buds Marine)"]

for name in devices:
    label = name if name else "System Default"
    idx = resolve(name, "input") if name else None
    print(f"\n--- Testing '{label}' (resolve -> {idx}) ---")
    levels = []
    def cb(indata, frames, time_info, status):
        levels.append(float(np.max(np.abs(indata))))
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1024, device=idx, callback=cb):
            time.sleep(2.0)
        max_l = max(levels) if levels else 0
        avg_l = sum(levels)/len(levels) if levels else 0
        print(f"Result: Frames={len(levels)}, Max={max_l}, Avg={avg_l:.1f}")
    except Exception as e:
        print(f"Result: FAILED -> {e}")
