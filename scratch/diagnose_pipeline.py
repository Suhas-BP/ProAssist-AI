"""
scratch/diagnose_pipeline.py
Diagnostic tool to inspect audio hardware, sounddevice stream, audio levels,
wake word / VAD, mute state, and pipeline flags.
"""
import sys
import time
import numpy as np
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import sounddevice as sd
from memory.config_manager import load_api_keys, get_input_device, get_output_device
from core import audio_devices

print("=" * 70)
print("STAGE 1 & SUSPECT 1: AUDIO CONFIG & HARDWARE CHECK")
print("=" * 70)

cfg = load_api_keys()
print(f"api_keys.json contents:")
for k, v in cfg.items():
    if "key" in k:
        print(f"  {k}: {v[:8]}...{v[-4:] if len(v)>12 else ''}")
    else:
        print(f"  {k}: {v}")

in_dev_cfg = get_input_device()
out_dev_cfg = get_output_device()
print(f"\nConfigured input device : '{in_dev_cfg}'")
print(f"Configured output device: '{out_dev_cfg}'")

resolved_in = audio_devices.resolve(in_dev_cfg, "input")
resolved_out = audio_devices.resolve(out_dev_cfg, "output")
print(f"Resolved input device index : {resolved_in}")
print(f"Resolved output device index: {resolved_out}")

print("\nQuerying system default devices from sounddevice:")
try:
    default_devs = sd.default.device
    print(f"sd.default.device: {default_devs}")
    in_info = sd.query_devices(kind='input')
    print(f"Default input device: {in_info['name']} (hostapi={in_info['hostapi']}, channels={in_info['max_input_channels']})")
except Exception as e:
    print(f"❌ Failed to query default input device: {e}")

try:
    out_info = sd.query_devices(kind='output')
    print(f"Default output device: {out_info['name']} (hostapi={out_info['hostapi']}, channels={out_info['max_output_channels']})")
except Exception as e:
    print(f"❌ Failed to query default output device: {e}")

print("\n" + "=" * 70)
print("STAGE 2: CAPTURE THREAD & LIVE AUDIO FRAMES")
print("=" * 70)

SEND_SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024

frames_received = 0
audio_levels = []
max_amp = 0.0

def callback(indata, frames, time_info, status):
    global frames_received, max_amp
    frames_received += 1
    amp = float(np.max(np.abs(indata)))
    rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
    audio_levels.append((amp, rms))
    if amp > max_amp:
        max_amp = amp

try:
    print(f"Opening InputStream(samplerate={SEND_SAMPLE_RATE}, channels={CHANNELS}, device={resolved_in})...")
    stream = sd.InputStream(
        samplerate=SEND_SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=CHUNK_SIZE,
        device=resolved_in,
        callback=callback,
    )
    with stream:
        print("Stream open! Listening for 3 seconds...")
        time.sleep(3.0)

    print(f"Captured {frames_received} frames.")
    if frames_received > 0:
        avg_amp = sum(a[0] for a in audio_levels) / len(audio_levels)
        avg_rms = sum(a[1] for a in audio_levels) / len(audio_levels)
        print(f"Max amplitude: {max_amp} (int16 scale max is 32767)")
        print(f"Average amplitude: {avg_amp:.2f}")
        print(f"Average RMS: {avg_rms:.2f}")
    else:
        print("❌ NO FRAMES RECEIVED!")
except Exception as e:
    print(f"❌ Error opening or reading audio stream: {e}")

print("\n" + "=" * 70)
print("DIAGNOSIS COMPLETE")
print("=" * 70)
