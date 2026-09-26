"""
scratch/test_live_connect.py
Test Live session connection to LIVE_MODEL ("models/gemini-3.1-flash-live-preview")
using the actual genai client.
"""
import sys
import asyncio
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from google import genai
from google.genai import types
from memory.config_manager import load_api_keys

cfg = load_api_keys()
api_key = cfg.get("gemini_api_key", "").strip()
print(f"API key loaded: {api_key[:8]}... (len={len(api_key)})")

LIVE_MODEL = "models/gemini-3.1-flash-live-preview"

async def test_live():
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
            )
        )
    )
    print(f"Connecting to Gemini Live with model={LIVE_MODEL}...")
    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=live_config) as session:
            print("SUCCESS: Connected to Gemini Live session!")
            print("Sending a text turn 'Hello, can you hear me?'...")
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": "Hello, can you hear me?"}]},
                turn_complete=True,
            )
            print("Waiting for response chunks...")
            audio_chunks_received = 0
            text_received = []
            async for resp in session.receive():
                if resp.data:
                    audio_chunks_received += 1
                if resp.server_content:
                    sc = resp.server_content
                    if sc.output_transcription and sc.output_transcription.text:
                        text_received.append(sc.output_transcription.text)
                    if sc.turn_complete:
                        print("Turn complete received!")
                        break
            print(f"Total audio chunks received: {audio_chunks_received}")
            print(f"Transcript received: {' '.join(text_received)}")
            return True
    except Exception as e:
        print(f"FAILED to connect or receive: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_live())
    print(f"Live connect test result: {success}")
