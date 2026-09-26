import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import win32com.client
import wave
import numpy as np
import scipy.signal
from core.voice_auth import VoiceAuthenticator

voice = win32com.client.Dispatch("SAPI.SpVoice")
stream = win32com.client.Dispatch("SAPI.SpFileStream")
wav_path = str(Path("scratch/test_challenge_audio.wav").resolve())
stream.Open(wav_path, 3, False)
voice.AudioOutputStream = stream
voice.Speak("Silver clouds drift quietly.")
stream.Close()

with wave.open(wav_path, "rb") as w:
    sr = w.getframerate()
    frames = w.readframes(w.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16)

num_samples = int(len(audio) * 16000 / sr)
audio_16k = scipy.signal.resample(audio, num_samples).astype(np.int16)
if len(audio_16k) < 32000:
    audio_16k = np.pad(audio_16k, (0, 32000 - len(audio_16k)))

va = VoiceAuthenticator()
accepted, score, name = va.verify(audio_16k)
threshold = va.profile().get("threshold", 0.72)
print(f"SAPI voice test -> accepted: {accepted}, score: {score:.4f}, enrolled name: '{name}', threshold: {threshold}")
