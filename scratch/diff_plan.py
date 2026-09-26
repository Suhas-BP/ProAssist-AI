import difflib
from pathlib import Path

old_file = Path(r"C:\Users\santh\.gemini\antigravity-ide\brain\8a51d655-10fe-4649-be6d-a4c90a685230\implementation_plan_initial.md")
# Let's save initial if we had it or construct it
old_content = """# Investigation & Implementation Plan: Speaker Output Bug & Root Cause

Investigate why the agent produced no audible speaker output, why "Audio output: host API reports success but moves no audio (0 ms for 600 ms) — skipping it" was logged, why the earlier automated test falsely passed, and provide a targeted fix and verification plan.

## User Review Required

> [!IMPORTANT]
> **Key Finding**: The physical reason for zero audible sound during real tests was that **Windows master volume for the default audio endpoint (`Speakers (2- Realtek(R) Audio)`) was MUTED (`Mute: 1`)**.
> 
> The log message `"Audio output: host API reports success but moves no audio (0 ms for 600 ms) — skipping it"` was a startup probe of PortAudio's DirectSound output backend (which was rejected in favor of MME), not a runtime drop of agent speech.
> 
> Furthermore, `actions/computer_settings.py` was crashing on modern `pycaw` (`AttributeError: 'AudioDevice' object has no attribute 'Activate'`) and falling back to `pyautogui.press("volumemute")`, which toggled the hardware mute state in Windows.

---

## 1. Investigation Findings (Items 1–4)

### Item 1: Locate Warning Source & Inspection
- **Location**: [`core/audio_devices.py:140-151`](file:///d:/Mark-LIV-main/core/audio_devices.py#L140-L151) inside `_transport_works(idx, kind, api_key)`.
- **Code**:
  ```python
  if kind == "output":
      # main.py writes with stream.write() — a real sink is rate-limited
      # by the hardware clock, a fake one swallows the buffer instantly.
      st = sd.RawOutputStream(samplerate=rate, channels=1, dtype="int16",
                              blocksize=1024, device=idx)
      st.start()
      t0 = time.monotonic()
      st.write(bytes(int(rate * secs) * 2))   # silence — inaudible
      elapsed = time.monotonic() - t0
      st.stop(); st.close()
      ok = elapsed > secs * 0.5
      if not ok:
          print(f"[Audio] output: host API reports success but moves no "
                f"audio ({elapsed*1000:.0f} ms for {secs*1000:.0f} ms) "
                f"— skipping it")
  ```
- **Check Mechanism**: It measures **wall-clock elapsed time** (`elapsed = time.monotonic() - t0`) during a synchronous write of 600 ms (`secs = 0.6`) of silence to PortAudio.
  - On a real hardware audio sink, `st.write()` is rate-limited by the hardware clock and blocks for ~600 ms.
  - On Windows DirectSound (`device=7`), PortAudio's write returns instantly in `0.0 ms` without blocking.
  - The check detects `elapsed <= 300 ms`, logs the warning, and rejects DirectSound for output.

### Item 2: Reconcile with Earlier Automated Test "PASS"
- **Test File**: [`scratch/test_pipeline_stages.py:183-202`](file:///d:/Mark-LIV-main/scratch/test_pipeline_stages.py#L183-L202)
- **Why it passed despite silence**:
  1. The automated test only checked that `spk_stream.write(...)` did not raise an unhandled exception or return an error code from PortAudio.
  2. In Windows Core Audio, when the active speaker is **MUTED** (`Mute: 1`), PortAudio and MME still accept audio buffers and advance stream clocks without any exception or error code — the Windows audio mixer simply drops the samples before the DAC.
  3. The test did not verify OS endpoint volume/mute state, did not assert elapsed playback time against audio duration, and did not verify acoustic audibility.

### Item 3: Output Device Resolution
- **Config**: `config/api_keys.json` has `"output_device": ""`.
- **Resolution**:
  - `audio_devices.resolve("", "output")` returns `None`.
  - In `main.py`, `_open_spk(None)` opens `sd.RawOutputStream(..., device=None)`.
  - In `sounddevice`, `device=None` maps to `sd.default.device[1]`, which is index `3` (`Speakers (2- Realtek(R) Audio), MME`).
  - Cross-check against Windows OS via `pycaw.AudioUtilities`:
    - OS Default Audio Endpoint: `Speakers (2- Realtek(R) Audio)`.
    - Status: `AudioDeviceState.Active` (all other endpoints like Headphones are unplugged/not present).
    - **Current OS Volume State**: `Master Volume: 1.0 (100%)`, but **`Mute: 1` (MUTED)**!
    - Resolution is targeting the correct, real physical speakers, but the speakers were muted in the OS.

### Item 4: Silent Exception / Fallback Path
- **"Skipping it" meaning**: Occurs **only** during startup enumeration in `_query()`. It skips the **DirectSound host API** because DirectSound does not rate-limit writes, and successfully advances to **MME** (`[Audio] output: using mme (1 devices)`). It does **not** skip spoken turns.
- **Runtime turn behavior**: During an actual agent turn, `main.py` successfully streams chunks to `sd.RawOutputStream` via MME. Visemes and avatar animations run, transcripts appear in UI, and `stream.write()` returns without error. Because the OS mixer was muted, no sound was produced.

---

## Proposed Targeted Fixes

### 1. [`core/audio_devices.py`](file:///d:/Mark-LIV-main/core/audio_devices.py)
- Split `_PREFERRED_APIS["Windows"]` into direction-specific preferences:
  - Input prefers `"directsound"`, `"mme"`, `"wasapi"`.
  - Output prefers `"mme"`, `"wasapi"` (excluding DirectSound since DirectSound output is a known 0 ms sink on Windows). This avoids probing DirectSound on every startup and eliminates the confusing warning.
- Add an unmute check helper (`ensure_unmuted()`) using `pycaw` so the app detects and automatically clears Windows mute before opening output streams.

### 2. [`actions/computer_settings.py`](file:///d:/Mark-LIV-main/actions/computer_settings.py)
- Fix the `pycaw` compatibility bug in `volume_get()` and `volume_set()`.
  Modern pycaw uses `devices.EndpointVolume` directly; calling `devices.Activate(...)` crashed and triggered the fallback `pyautogui.press("volumemute")` which muted Windows.

### 3. [`main.py`](file:///d:/Mark-LIV-main/main.py)
- In `_play_audio`, check if the speaker endpoint is muted before starting playback. If muted, automatically unmute it and log a clear notice in the system log so the user's speech is never lost to silent mute states.

### 4. [`scratch/test_pipeline_stages.py`](file:///d:/Mark-LIV-main/scratch/test_pipeline_stages.py)
- Update Stage 7 to check Windows mute status and verify real-time consumption duration, preventing future false "PASS" reports.

---

## Verification Plan

### Automated Tests
1. Run `python scratch/test_speaker_playback.py` to confirm `RawOutputStream` opens, unmuted state is verified, and real-time playback takes the expected duration.
2. Run `scratch/test_pipeline_stages.py` Stage 7 with mute verification.

### Real-Listening Confirmation (Item 6)
1. Run a standalone test script that plays a clean audible audio sample / Gemini voice turn through the physical speakers.
2. Prompt user/human listening verification to confirm that speech is clearly heard through the physical laptop speakers.
"""

new_file = Path(r"C:\Users\santh\.gemini\antigravity-ide\brain\8a51d655-10fe-4649-be6d-a4c90a685230\implementation_plan.md")
new_content = new_file.read_text(encoding="utf-8")

diff = list(difflib.unified_diff(
    old_content.splitlines(keepends=True),
    new_content.splitlines(keepends=True),
    fromfile="implementation_plan.md (initial)",
    tofile="implementation_plan.md (updated)",
))
print("".join(diff))
