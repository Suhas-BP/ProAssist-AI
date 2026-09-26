import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import wave
import numpy as np
import scipy.signal
from core.voice_auth import VoiceAuthenticator

va = VoiceAuthenticator()
profile = va.profile()
print(f"Profile: name={profile.get('name')}, threshold={profile.get('threshold')}")

files = [
    'd:/Agent.wav',
    'd:/Agent (1).wav',
    'd:/Agent (2).wav',
    'd:/agent_test.wav',
    'd:/Alex.wav',
    'd:/Alien.wav',
    'd:/Animal.wav'
]

for filepath in files:
    p = Path(filepath)
    if not p.exists():
        continue
    with wave.open(str(p), 'rb') as w:
        sr = w.getframerate()
        frames = w.readframes(w.getnframes())
        raw = np.frombuffer(frames, dtype=np.int16)
    
    # Resample to 16kHz
    num_samples = int(len(raw) * 16000 / sr)
    samples_16k = scipy.signal.resample(raw, num_samples).astype(np.int16)
    
    # Ensure minimum 2 seconds length for speaker embedding generator
    if len(samples_16k) < 32000:
        # pad with zeros
        samples_16k_padded = np.pad(samples_16k, (0, 32000 - len(samples_16k)))
    else:
        samples_16k_padded = samples_16k
        
    accepted, score, name = va.verify(samples_16k_padded)
    print(f"{filepath} ({len(raw)/sr:.2f}s) -> accepted: {accepted}, score: {score:.4f} ({score:.1%}), name: {name}")
