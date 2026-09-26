"""
scratch/test_speaker_playback.py
Test RawOutputStream output playback.
"""
import sys
import numpy as np
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

import sounddevice as sd
from memory.config_manager import get_output_device
from core import audio_devices

RECEIVE_SAMPLE_RATE = 24000
CHANNELS = 1
CHUNK_SIZE = 1024

spk_name = get_output_device()
spk_dev = audio_devices.resolve(spk_name, "output")
print(f"Configured output: '{spk_name}', resolved: {spk_dev}")

try:
    stream = sd.RawOutputStream(
        samplerate=RECEIVE_SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=CHUNK_SIZE,
        device=spk_dev,
    )
    stream.start()
    lat = float(getattr(stream, "latency", 0.0) or 0.0)
    print(f"SUCCESS: RawOutputStream started! Reported latency: {lat*1000:.1f} ms")

    # Generate a brief 0.2s gentle 440Hz tone to test write
    t = np.linspace(0, 0.2, int(RECEIVE_SAMPLE_RATE * 0.2), endpoint=False)
    # fade in and fade out envelope to avoid click
    env = np.sin(np.pi * np.linspace(0, 1, len(t)))
    tone = (np.sin(2 * np.pi * 440 * t) * 1000 * env).astype(np.int16)
    raw = tone.tobytes()

    for i in range(0, len(raw), CHUNK_SIZE):
        stream.write(raw[i : i + CHUNK_SIZE])
    
    stream.stop()
    stream.close()
    print("SUCCESS: Audio written and stream closed cleanly.")
except Exception as e:
    print(f"FAILED: {e}")
