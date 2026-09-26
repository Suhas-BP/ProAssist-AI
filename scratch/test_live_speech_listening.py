"""
scratch/test_live_speech_listening.py
Trigger a real Gemini Live turn and play spoken speech through system speakers for human verification.
"""
import sys
import time
import asyncio
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import sounddevice as sd
from memory.config_manager import load_api_keys, get_output_device
from core import audio_devices
from google import genai
from google.genai import types

# 1. Ensure speakers are unmuted
unmuted = audio_devices.ensure_unmuted()
print(f"[Audio] ensure_unmuted() returned: {unmuted}")

try:
    from pycaw.pycaw import AudioUtilities
    spk = AudioUtilities.GetSpeakers()
    vol = getattr(spk, "EndpointVolume", None)
    if vol:
        print(f"[Audio] Verified Master Volume: {vol.GetMasterVolumeLevelScalar()*100:.0f}%, Muted: {bool(vol.GetMute())}")
except Exception as e:
    print(f"[Audio] Volume inspection: {e}")

cfg = load_api_keys()
api_key = cfg.get("gemini_api_key", "").strip()
client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})

RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
LIVE_MODEL = "models/gemini-3.1-flash-live-preview"

async def test_live_speech():
    print(f"\nConnecting to Gemini Live session ({LIVE_MODEL})...")
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Puck"
                )
            )
        ),
    )

    async with client.aio.live.connect(model=LIVE_MODEL, config=live_config) as session:
        print("Connected to Gemini Live! Sending prompt...")
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": "Hello, please say clearly: 'Audio output test successful, speakers are fully working.' in a single clear sentence."}]},
            turn_complete=True,
        )

        pcm_chunks = []
        transcript = []

        print("Awaiting model spoken response...")
        async for response in session.receive():
            if response.data:
                pcm_chunks.append(response.data)
            if response.server_content:
                sc = response.server_content
                if sc.output_transcription and sc.output_transcription.text:
                    transcript.append(sc.output_transcription.text)
                if sc.turn_complete:
                    break

        all_pcm = b"".join(pcm_chunks)
        print(f"\nReceived {len(all_pcm)} bytes of speech.")
        print(f"Transcript: '{' '.join(transcript).strip()}'")

        spk_name = get_output_device()
        spk_idx = audio_devices.resolve(spk_name, "output")
        print(f"\nOpening RawOutputStream on device: {spk_idx} ('{spk_name or 'System default'}')...")
        
        st = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_SIZE,
            device=spk_idx,
        )
        st.start()

        duration = len(all_pcm) / (RECEIVE_SAMPLE_RATE * 2)
        print(f"Playing {duration:.2f} seconds of spoken audio through physical speakers now...")
        t0 = time.monotonic()
        for i in range(0, len(all_pcm), CHUNK_SIZE):
            st.write(all_pcm[i : i + CHUNK_SIZE])
        elapsed = time.monotonic() - t0
        st.stop()
        st.close()

        print(f"Playback finished. Elapsed wall-clock time: {elapsed:.2f}s for {duration:.2f}s of audio.")
        print("\n" + "=" * 70)
        print("REAL-LISTENING CONFIRMATION REQUIRED FROM HUMAN USER:")
        print("Did you hear the assistant say through your speakers:")
        print(f"\"{' '.join(transcript).strip()}\"?")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_live_speech())
