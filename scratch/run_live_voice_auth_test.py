"""
scratch/run_live_voice_auth_test.py

Interactive live microphone capture test for Voice Authentication.
Prompts the user with an official challenge phrase, counts down,
records 5 seconds from the microphone at 16kHz, and evaluates against
the enrolled profile ("Santhosh").
"""
import sys
import time
from pathlib import Path
import numpy as np

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import sounddevice as sd
from core.voice_auth import VoiceAuthenticator, AUTHENTICATION_SENTENCES, MATCH_THRESHOLD
from memory.config_manager import get_input_device
from core import audio_devices

sys.stdout.reconfigure(line_buffering=True)

CHALLENGE_PHRASE = AUTHENTICATION_SENTENCES[0]  # "Silver clouds drift quietly."
RECORD_SECONDS = 6.0  # Exactly matches AUTH_SAMPLE_SECONDS in main.py
SAMPLE_RATE = 16000

print("=" * 75)
print("LIVE VOICE AUTHENTICATION TEST")
print("=" * 75)
print(f"\nTarget Challenge Sentence to speak aloud:\n")
print(f"    >>> \"{CHALLENGE_PHRASE}\" <<<\n")
print("=" * 75)

# Check microphone
in_dev_cfg = get_input_device()
in_dev = audio_devices.resolve(in_dev_cfg, "input")
dev_info = sd.query_devices(in_dev, kind="input")
print(f"Microphone Device : {dev_info['name']}")
print(f"Sampling Rate     : {SAMPLE_RATE} Hz (16-bit mono)")
print(f"Duration          : {RECORD_SECONDS} seconds\n")

import winsound

print("Get ready to speak the challenge sentence when recording starts!")
for remaining in [3, 2, 1]:
    print(f"Starting in {remaining}...")
    try:
        winsound.Beep(800, 150)
    except Exception:
        pass
    time.sleep(0.85)

print(f"\n>>> [RECORDING NOW] SPEAK CLEARLY INTO MIC: \"{CHALLENGE_PHRASE}\" <<<")
try:
    winsound.Beep(1200, 300)
except Exception:
    pass

audio_data = sd.rec(
    int(RECORD_SECONDS * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="int16",
    device=in_dev,
)
sd.wait()

try:
    winsound.Beep(500, 200)
except Exception:
    pass
print("[RECORDING FINISHED] Processing speaker embedding...\n")

samples = audio_data[:, 0].copy()

# Save capture to WAV for diagnostic inspection
import wave
out_wav = Path("scratch/live_capture_santhosh.wav")
with wave.open(str(out_wav), "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(SAMPLE_RATE)
    wf.writeframes(samples.tobytes())

# Audio Level Diagnostics
peak = int(np.max(np.abs(samples)))
rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
print(f"Audio Diagnostics:")
print(f"  Captured Samples : {len(samples)} ({len(samples)/SAMPLE_RATE:.1f}s)")
print(f"  Peak Amplitude   : {peak} / 32767 ({peak/32767*100:.1f}%)")
print(f"  RMS Level        : {rms:.1f}")

if peak < 500:
    print("\n[WARNING] Audio level is extremely low or silent. Please check mic volume or mute switch.")

# Voice Authentication Evaluation
va = VoiceAuthenticator()
profile = va.profile()
threshold = profile.get("threshold", MATCH_THRESHOLD)
accepted, score, name = va.verify(samples)

print("\n" + "=" * 75)
print("VERIFICATION RESULTS")
print("=" * 75)
print(f"Enrolled User Name : {name}")
print(f"Passing Threshold  : {threshold:.1%}")
print(f"Live Match Score   : {score:.1%}")
print(f"Authentication     : {'ACCEPTED (PASS)' if accepted else 'DENIED (FAIL)'}")
print("=" * 75)

if accepted:
    print(f"\n[SUCCESS] Voice authenticated! Welcome, {name}.")
else:
    print(f"\n[FAILED] Score {score:.1%} did not meet threshold {threshold:.1%}.")
