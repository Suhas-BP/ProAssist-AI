"""
scratch/test_live_audio_stream.py
Test streaming real PCM audio chunks into Gemini Live session.
"""
import sys
import asyncio
import numpy as np
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from google import genai
from google.genai import types
from memory.config_manager import load_api_keys

cfg = load_api_keys()
api_key = cfg.get("gemini_api_key", "").strip()
LIVE_MODEL = "models/gemini-3.1-flash-live-preview"

async def test_audio_stream():
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        input_audio_transcription={},
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
            )
        )
    )
    print("Connecting to Live session for streaming test...")
    async with client.aio.live.connect(model=LIVE_MODEL, config=live_config) as session:
        print("Connected!")
        # Generate 1.5 seconds of a simple sine wave tone / chirp
        sr = 16000
        t = np.linspace(0, 1.5, int(sr * 1.5), endpoint=False)
        tone = (np.sin(2 * np.pi * 440 * t) * 5000).astype(np.int16)
        raw_bytes = tone.tobytes()

        # Send in 1024-byte chunks (matching app chunking)
        chunk_size = 1024
        print(f"Streaming {len(raw_bytes)} bytes in chunks of {chunk_size}...")
        for i in range(0, len(raw_bytes), chunk_size):
            chunk = raw_bytes[i : i + chunk_size]
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm")
            )
            await asyncio.sleep(0.03)
        print("Stream finished.")
        return True

if __name__ == "__main__":
    res = asyncio.run(test_audio_stream())
    print(f"Streaming test result: {res}")
