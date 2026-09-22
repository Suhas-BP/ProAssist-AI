"""
ProAssist AI - Microphone & Wake-Word Diagnostic Tool
Inspects microphone capture, measures RMS/Peak audio levels, and tests
Whisper keyword detection on live speech in real time.
"""

import sys
import time
import pyaudio
import numpy as np

import config
from wake_word.audio_stream import MicrophoneStream
from wake_word.detector import WhisperKeywordDetector

def main():
    print("=" * 65)
    print("       PROASSIST AI - MICROPHONE & WAKE-WORD DIAGNOSTIC")
    print("=" * 65)

    p = pyaudio.PyAudio()
    dev_count = p.get_device_count()
    print(f"[*] Total audio devices detected: {dev_count}")
    try:
        default_dev = p.get_default_input_device_info()
        print(f"[*] Default input device: {default_dev['name']} (Index: {default_dev['index']})")
        print(f"[*] Default native sample rate: {default_dev['defaultSampleRate']} Hz")
    except Exception as e:
        print(f"[!] Error getting default device: {e}")
    p.terminate()

    print(f"\n[*] Configured sample rate : {config.SAMPLE_RATE} Hz")
    print(f"[*] Target wake phrase     : \"{config.WAKE_PHRASE}\" (Strict matching)")
    print(f"[*] Energy threshold       : {config.KEYWORD_SPOT_ENERGY_THRESHOLD}")
    print(f"[*] Sliding buffer window  : {config.KEYWORD_SPOT_BUFFER_SECONDS}s")

    print("\n[*] Initializing WhisperKeywordDetector...")
    detector = WhisperKeywordDetector()

    print("\n" + "#" * 65)
    print("  LIVE MICROPHONE TEST: SPEAK 'AGENT' NOW")
    print("  Monitoring microphone for 30 seconds... (Press Ctrl+C to stop)")
    print("#" * 65 + "\n")

    stream = MicrophoneStream()
    stream.start()

    start_time = time.time()
    try:
        while time.time() - start_time < 30:
            pcm_bytes, chunk_int16 = stream.read_chunk()
            if chunk_int16 is None or len(chunk_int16) == 0:
                time.sleep(0.01)
                continue

            detected = detector.is_detected(chunk_int16)
            if detected:
                print("\n" + "#" * 65)
                print(f"SUCCESS: WAKE WORD '{config.WAKE_PHRASE.upper()}' DETECTED!")
                print("#" * 65 + "\n")
                break
    except KeyboardInterrupt:
        print("\nDiagnostic stopped by user.")
    finally:
        stream.stop()

    print("\nDiagnostic complete.")

if __name__ == "__main__":
    main()
