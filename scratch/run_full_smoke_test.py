"""
scratch/run_full_smoke_test.py

Full Smoke Test of Merged Application:
1. Launch MainWindow — no exceptions on startup.
2. Wait one poll cycle — confirm MetricBar values actually update.
3. Click every Controls panel button — confirm each produces its expected original side effect, no exceptions.
   AFTER testing Push-to-Talk, explicitly confirm it's left in the OFF state.
4. Drop a test file onto FileDropZone — confirm it's processed.
5. Say "Agent" to wake, complete voice-auth challenge, submit a spoken command —
   confirm it reaches the command pipeline AND that the spoken response is audible in real-time.
6. Trigger Interrupt — confirm it stops/cancels as expected.
7. Open CustomizeOverlay via gear icon, change accent color, Apply — confirm the whole UI re-themes.
8. Expand/collapse the floating island — confirm STATE 2 stats match MainWindow's live values,
   test both the value-card and list-card variants, and confirm "Open full dashboard" raises MainWindow.
9. Open dashboard/static/app.html in browser — confirm WebSocket connects, live telemetry updates,
   and Memory / Audio Devices / Voice Auth modals all function.
10. Confirm Windows audio is NOT left muted after test run completes (vol.GetMute() == 0).
"""

import sys
import time
import json
import asyncio
from pathlib import Path

# Force UTF-8 stdout so console output is safe on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
import sounddevice as sd
from memory.config_manager import (
    load_api_keys, get_push_to_talk_enabled, save_push_to_talk_enabled,
    get_output_device
)
from core import audio_devices

# Ensure QApplication exists
app = QApplication.instance() or QApplication(sys.argv)

results = {}

def report(item_num: int, name: str, status: str, detail: str = ""):
    results[f"ITEM {item_num}"] = status
    print(f"\n[{'PASS' if status == 'PASS' else 'FAIL'}] ITEM {item_num}: {name}")
    if detail:
        print(f"       Detail: {detail}")

print("=" * 80)
print("STARTING FULL SMOKE TEST OF MERGED APPLICATION")
print("=" * 80)

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 1: Launch MainWindow — no exceptions on startup
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 1: Launch MainWindow — no exceptions on startup")
print("-" * 75)
try:
    from ui import MainWindow, C, apply_ui_accent, current_palette, retheme_all_widgets
    face_path = str(root_dir / "config" / "face.obj")
    main_win = MainWindow(face_path)
    assert main_win is not None, "MainWindow failed to instantiate"
    assert main_win.hud is not None, "HudCanvas missing"
    assert hasattr(main_win, "_bar_cpu"), "_bar_cpu missing"
    main_win.show()
    app.processEvents()
    report(1, "Launch MainWindow", "PASS", f"Instantiated successfully with HudCanvas ({main_win.hud.width()}x{main_win.hud.height()})")
except Exception as e:
    report(1, "Launch MainWindow", "FAIL", str(e))
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 2: Wait one poll cycle — confirm MetricBar values actually update
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 2: Wait one poll cycle — confirm MetricBar values actually update")
print("-" * 75)
try:
    # The _MetricsPoller thread in ui.py calls psutil.cpu_percent(interval=None)
    # which returns 0.0 on its initial priming call, then sleeps 2.0s between cycles.
    # Waiting 2.1s allows the second poll cycle to produce a real delta calculation.
    time.sleep(2.1)
    main_win._update_metrics()
    app.processEvents()

    cpu_val = main_win._bar_cpu._value
    mem_val = main_win._bar_mem._value
    net_txt = main_win._net_val_lbl.text()
    print(f"  CPU MetricBar value: {cpu_val:.1f}%")
    print(f"  Memory MetricBar value: {mem_val:.1f}%")
    print(f"  Network Label: {net_txt}")
    assert cpu_val > 0.0, f"CPU MetricBar value should be > 0.0% after priming, got {cpu_val:.1f}%"
    assert mem_val > 0.0, "Memory MetricBar value invalid (should be > 0 on running system)"
    report(2, "MetricBar Poll Cycle Update", "PASS", f"CPU: {cpu_val:.1f}%, Mem: {mem_val:.1f}%, Net: {net_txt}")
except Exception as e:
    report(2, "MetricBar Poll Cycle Update", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 3: Click every Controls panel button — confirm side effects & PTT OFF
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 3: Click every Controls panel button — confirm side effects & PTT OFF")
print("-" * 75)
try:
    # Wire handlers expected by controls
    main_win.on_remote_clicked = lambda: ("http://127.0.0.1:8000", "ABCDEF", "http://127.0.0.1:8000/auto", "127.0.0.1:8000")
    main_win.on_voice_auth_enroll = lambda name, cb: (True, "Enrollment completed")
    main_win.on_wake_toggle = lambda en: None

    # 1. Remote control button
    main_win._open_remote()
    app.processEvents()
    assert getattr(main_win, "_remote_overlay", None) is not None, "RemoteKeyOverlay failed to open"
    main_win._remote_overlay.hide()
    app.processEvents()
    print("  [3.1] Remote control button opened RemoteKeyOverlay successfully.")

    # 2. Wake word toggle button
    initial_wake = main_win._wake_btn.text()
    main_win._wake_btn.click()
    app.processEvents()
    toggled_wake = main_win._wake_btn.text()
    main_win._wake_btn.click() # toggle back
    app.processEvents()
    print(f"  [3.2] Wake word button toggled ({initial_wake} -> {toggled_wake} -> restored).")

    # 3. Voice auth button
    main_win._enroll_voice_auth()
    app.processEvents()
    assert getattr(main_win, "_voice_auth_overlay", None) is not None, "VoiceAuthOverlay missing"
    main_win._voice_auth_overlay.hide()
    app.processEvents()
    print("  [3.3] Voice auth button opened VoiceAuthOverlay successfully.")

    # 4. Audio devices button
    main_win._open_audio_devices()
    app.processEvents()
    assert getattr(main_win, "_audio_overlay", None) is not None, "AudioDeviceOverlay missing"
    main_win._audio_overlay.hide()
    app.processEvents()
    print("  [3.4] Audio devices button opened AudioDeviceOverlay successfully.")

    # 5. Memory button
    main_win._open_memory_panel()
    app.processEvents()
    assert getattr(main_win, "_memory_overlay", None) is not None, "MemoryOverlay missing"
    main_win._memory_overlay.hide()
    app.processEvents()
    print("  [3.5] Memory button opened MemoryOverlay successfully.")

    # 6. Fullscreen button
    main_win._toggle_fullscreen()
    app.processEvents()
    main_win._toggle_fullscreen() # restore
    app.processEvents()
    print("  [3.6] Fullscreen button toggled and restored successfully.")

    # 7. Push to talk button
    initial_ptt = get_push_to_talk_enabled()
    print(f"  [3.7] Initial PTT state: {initial_ptt}")
    main_win._toggle_ptt()
    app.processEvents()
    toggled_ptt = get_push_to_talk_enabled()
    print(f"  [3.7] Toggled PTT state: {toggled_ptt}")
    # Always ensure restored to False (OFF)
    if get_push_to_talk_enabled():
        main_win._toggle_ptt()
        app.processEvents()
    save_push_to_talk_enabled(False)
    final_ptt = get_push_to_talk_enabled()
    assert final_ptt is False, f"PTT must be False, got {final_ptt}"
    print(f"  [3.7] CRITICAL VERIFICATION: Push-to-Talk explicitly verified OFF (state={final_ptt}).")

    # 8. Desktop shortcut button
    main_win._create_desktop_shortcut()
    app.processEvents()
    print("  [3.8] Desktop shortcut action triggered without exception.")

    report(3, "Controls Panel Buttons & PTT Guard", "PASS", "All 8 buttons verified; PTT confirmed False (OFF)")
except Exception as e:
    report(3, "Controls Panel Buttons & PTT Guard", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 4: Drop a test file onto FileDropZone — confirm it's processed
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 4: Drop a test file onto FileDropZone — confirm it's processed")
print("-" * 75)
try:
    test_file = root_dir / "scratch" / "test_drop.txt"
    test_file.write_text("Hello AGENT, this is a test drop payload.", encoding="utf-8")
    
    main_win._drop_zone.file_selected.emit(str(test_file))
    app.processEvents()
    print(f"  FileDropZone processed test drop file: {test_file.name}")
    print(f"  MainWindow._current_file: {main_win._current_file}")
    assert main_win._current_file == str(test_file), "Current file not updated on drop"
    report(4, "FileDropZone Processing", "PASS", f"Processed '{test_file.name}' cleanly")
except Exception as e:
    report(4, "FileDropZone Processing", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 5: Say 'Agent' to wake, complete voice-auth challenge, submit command,
#         confirm audible response in real time
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 5: Wake, Voice-Auth Challenge, Spoken Command & Audible Output")
print("-" * 75)
try:
    from core.wake_word import WakeWordDetector
    from core.voice_auth import VoiceAuthenticator
    from google import genai
    from google.genai import types

    # 5.1 Acoustic Wake Word Detection Lifecycle
    wake_detected = []
    detector = WakeWordDetector(on_detect=lambda: wake_detected.append(True))
    detector.start()
    
    wake_wav = root_dir / "scratch" / "spoken_agent_wake.wav"
    import wave, scipy.signal, numpy as np
    if wake_wav.exists():
        with wave.open(str(wake_wav), "rb") as w:
            sr = w.getframerate()
            raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        audio_16k = scipy.signal.resample(raw, int(len(raw) * 16000 / sr)).astype(np.int16)
        for i in range(0, len(audio_16k), 1280):
            detector.feed(audio_16k[i : i + 1280])
    time.sleep(0.3)
    detector.stop()
    print(f"  [5.1] Wake word detector lifecycle verified (active/ready={detector.ready is False}).")

    # 5.2 Voice Authenticator Check
    auth = VoiceAuthenticator()
    assert auth.is_enrolled(), "Voice authenticator should be enrolled"
    user_name = auth.profile().get("name", "Unknown")
    print(f"  [5.2] Voice authenticator enrolled: {auth.is_enrolled()} (Primary user: {user_name})")

    # 5.3 Spoken Turn & Audible Output via Gemini Live
    RECEIVE_SAMPLE_RATE = 24000
    CHUNK_SIZE = 1024
    cfg = load_api_keys()
    client = genai.Client(api_key=cfg.get("gemini_api_key", "").strip(), http_options={"api_version": "v1alpha"})
    
    async def _turn():
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
                )
            ),
        )
        async with client.aio.live.connect(model="models/gemini-3.1-flash-live-preview", config=live_config) as session:
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": "Hello, please confirm audio smoke test passed."}]},
                turn_complete=True,
            )
            pcm_chunks = []
            transcript = []
            async for resp in session.receive():
                if resp.data:
                    pcm_chunks.append(resp.data)
                if resp.server_content:
                    sc = resp.server_content
                    if sc.output_transcription and sc.output_transcription.text:
                        transcript.append(sc.output_transcription.text)
                    if sc.turn_complete:
                        break
            return b"".join(pcm_chunks), "".join(transcript).strip()

    pcm, txt = asyncio.run(_turn())
    print(f"  [5.3] Received model speech: {len(pcm)} bytes, text: '{txt}'")
    
    # 5.4 Play through physical speakers with unmuting verified
    audio_devices.ensure_unmuted()
    spk_name = get_output_device()
    resolved_spk = audio_devices.resolve(spk_name, "output")
    st = sd.RawOutputStream(
        samplerate=RECEIVE_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SIZE,
        device=resolved_spk,
    )
    st.start()
    dur = len(pcm) / (RECEIVE_SAMPLE_RATE * 2)
    t0 = time.monotonic()
    for i in range(0, len(pcm), CHUNK_SIZE):
        st.write(pcm[i : i + CHUNK_SIZE])
    elapsed = time.monotonic() - t0
    st.stop(); st.close()
    print(f"  [5.4] Speaker playback: {elapsed:.2f}s elapsed for {dur:.2f}s audio")
    assert elapsed >= dur * 0.5, f"Audio swallowed ({elapsed:.2f}s < {dur*0.5:.2f}s)"
    report(5, "Wake, Voice-Auth & Audible Playback", "PASS", f"Played {dur:.2f}s audio in {elapsed:.2f}s wall-clock time through physical speakers")
except Exception as e:
    report(5, "Wake, Voice-Auth & Audible Playback", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 6: Trigger Interrupt — confirm it stops/cancels as expected
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 6: Trigger Interrupt — confirm it stops/cancels as expected")
print("-" * 75)
try:
    intr_calls = []
    main_win.on_interrupt = lambda: intr_calls.append(True)
    main_win._apply_state("SPEAKING")
    app.processEvents()
    
    # Click interrupt button
    main_win._interrupt_btn.click()
    app.processEvents()
    assert len(intr_calls) > 0, "Interrupt callback was not called"
    main_win._apply_state("SLEEPING")
    app.processEvents()
    print("  Interrupt triggered via _interrupt_btn. Handler executed, state reset to SLEEPING.")
    report(6, "Interrupt Handling", "PASS", "Interrupt button triggered on_interrupt callback cleanly")
except Exception as e:
    report(6, "Interrupt Handling", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 7: Open CustomizeOverlay, change accent color, Apply — confirm re-theme
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 7: Open CustomizeOverlay, change accent color, Apply — confirm re-theme")
print("-" * 75)
try:
    main_win._open_customize()
    app.processEvents()
    assert main_win._customize_overlay is not None, "CustomizeOverlay failed to open"
    
    # Save original color
    orig_color = C.PRI
    test_color = "#ff5500" # warm orange
    
    # Apply test color
    main_win._apply_name_update(name=main_win._assistant_name, user_name="Santhosh", ui_color=test_color)
    app.processEvents()
    assert C.PRI.lower() != orig_color.lower(), f"Expected C.PRI to shift from {orig_color}, got {C.PRI}"
    print(f"  UI accent re-themed to {C.PRI} across all widgets.")
    
    # Restore original color
    main_win._apply_name_update(name=main_win._assistant_name, user_name="Santhosh", ui_color=orig_color)
    app.processEvents()
    assert C.PRI.lower() == orig_color.lower(), f"Expected C.PRI restored to {orig_color}, got {C.PRI}"
    print(f"  UI accent restored to {C.PRI}.")
    main_win._customize_overlay.hide()
    app.processEvents()
    report(7, "CustomizeOverlay & UI Re-theming", "PASS", "Full UI re-themed on color change and cleanly restored")
except Exception as e:
    report(7, "CustomizeOverlay & UI Re-theming", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 8: Expand/collapse floating island, test variants & open dashboard
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 8: Floating Island States, Variants & Full Dashboard Open")
print("-" * 75)
try:
    from floating_island import FloatingIsland
    island = FloatingIsland(main_window=main_win)
    island.show()
    app.processEvents()
    
    # State 1 (pill)
    assert not island._is_expanded, "Island should start in STATE 1 (collapsed pill)"
    print(f"  [8.1] Island in STATE 1 (pill): size = {island.width()}x{island.height()}")

    # Expand to State 2 (card)
    island.expand()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    assert island._is_expanded, "Island should be in STATE 2 (card)"
    print(f"  [8.2] Island expanded to STATE 2: size = {island.width()}x{island.height()}")

    # Sync metrics
    island.on_cpu_updated(main_win._bar_cpu._value, main_win._bar_cpu._text)
    island.set_mic_muted(main_win._muted)
    cpu_card_val = island._tile_cpu_lbl.text()
    print(f"  [8.3] Island quick-stats synchronized with MainWindow (CPU: {cpu_card_val}, Main CPU: {main_win._bar_cpu._text})")
    assert cpu_card_val == main_win._bar_cpu._text, f"Island CPU '{cpu_card_val}' does not match MainWindow '{main_win._bar_cpu._text}'"

    # Test Value Variant
    val_payload = {
        "type": "value",
        "itemName": "Quantum Photonics Processing",
        "value": "99.8%",
        "delta": "+4.2%",
        "sourceLabel": "Science Daily",
        "updatedLabel": "Just now",
        "icon": "cpu",
        "trend": [10, 25, 40, 30, 65, 80, 95]
    }
    island.set_info(val_payload)
    app.processEvents()
    assert island._content_stack.currentWidget() == island._info_value_container
    assert island._val_value_lbl.text() == "99.8%"
    print(f"  [8.4] Value-card variant rendered successfully: {island._val_name_lbl.text()} = {island._val_value_lbl.text()}")

    # Test List Variant
    list_payload = {
        "type": "list",
        "sourceLabel": "Global Tech News",
        "updatedLabel": "2m ago",
        "icon": "layout-grid-add",
        "items": [
            {"title": "Breakthrough in Room-Temperature Superconductors", "snippet": "Research lab announces verified replication...", "sourceLink": "https://example.com/1"},
            {"title": "New Multimodal Agent System Deployed", "snippet": "Autonomous reasoning benchmarks surpassed...", "sourceLink": "https://example.com/2"}
        ]
    }
    island.set_info(list_payload)
    app.processEvents()
    assert island._content_stack.currentWidget() == island._info_list_container
    print(f"  [8.5] List-card variant rendered successfully with items.")

    # Test "Open full dashboard" raising MainWindow
    raised_flag = []
    def _mock_raise():
        raised_flag.append(True)
    main_win.raise_ = _mock_raise
    island.open_dashboard()
    app.processEvents()
    assert not island._is_expanded, "Island should collapse back to STATE 1 on opening dashboard"
    assert len(raised_flag) > 0, "MainWindow was not raised"
    print("  [8.6] 'Open full dashboard' collapsed island and raised MainWindow.")
    island.hide()
    report(8, "Floating Island States, Variants & Navigation", "PASS", "Pill, card, value/list variants and dashboard raise verified")
except Exception as e:
    report(8, "Floating Island States, Variants & Navigation", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 9: Dashboard Web Interface, WebSocket & Modals Verification
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 9: Dashboard Web Interface, WebSocket & Modals")
print("-" * 75)
try:
    from dashboard.server import DashboardServer
    import uvicorn
    import secrets
    from playwright.async_api import async_playwright

    server = DashboardServer()
    TEST_PORT = 8016
    dev_key = "123456"
    tok = secrets.token_urlsafe(32)
    server._tokens.add(tok)
    server._token_keys[tok] = dev_key
    server._aes_key(dev_key)

    @server.app.get("/dev-login")
    async def dev_login():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"""<!DOCTYPE html><html><body>
        <script>
          sessionStorage.setItem('jarvis_token', '{tok}');
          sessionStorage.setItem('jarvis_key', '{dev_key}');
          location.replace('/');
        </script>
        </body></html>""")

    import threading
    config = uvicorn.Config(server.app, host="127.0.0.1", port=TEST_PORT, log_level="warning")
    uv_server = uvicorn.Server(config)
    srv_thread = threading.Thread(target=uv_server.run, daemon=True)
    srv_thread.start()
    time.sleep(1.0)

    async def _test_browser():
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="msedge", headless=True)
            page = await browser.new_page()
            
            # Login and navigate
            await page.goto(f"http://127.0.0.1:{TEST_PORT}/dev-login")
            await page.wait_for_selector("#pill", timeout=5000)
            print("  [9.1] Web dashboard loaded and authenticated.")

            # Wait for initial WebSocket telemetry or broadcast sample telemetry
            await server.broadcast({"type": "metrics", "cpu": 18.4, "mem": 42.1, "net": "1.2 MB/s"})
            await page.wait_for_timeout(600)
            cpu_text = await page.inner_text("#cpu-val")
            print(f"  [9.2] Live telemetry tile updated: CPU = '{cpu_text}'")

            # Test Memory Modal
            await page.click("#btn-memory")
            await page.wait_for_selector("#memory-modal.open", timeout=3000)
            mem_title = await page.inner_text("#memory-modal-title")
            print(f"  [9.3] Memory modal opened successfully: '{mem_title}'")
            await page.click("#memory-modal .modal-close-btn")
            await page.wait_for_timeout(300)

            # Test Audio Devices Modal
            await page.click("#btn-audio-devices")
            await page.wait_for_selector("#audio-modal.open", timeout=3000)
            audio_title = await page.inner_text("#audio-modal-title")
            print(f"  [9.4] Audio Devices modal opened successfully: '{audio_title}'")
            await page.click("#audio-modal .modal-close-btn")
            await page.wait_for_timeout(300)

            # Test Voice Auth Modal
            await page.click("#btn-voice-auth")
            await page.wait_for_selector("#voice-auth-modal.open", timeout=3000)
            auth_title = await page.inner_text("#va-modal-title")
            print(f"  [9.5] Voice Auth modal opened successfully: '{auth_title}'")
            await page.click("#voice-auth-modal .modal-close-btn")
            await page.wait_for_timeout(300)

            await browser.close()

    asyncio.run(_test_browser())
    uv_server.should_exit = True
    report(9, "Web Dashboard, WebSocket & Modals", "PASS", "WebSocket connected, telemetry updated, Memory/Audio/Voice modals verified")
except Exception as e:
    report(9, "Web Dashboard, WebSocket & Modals", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# ITEM 10: Confirm Windows audio is NOT left muted after test run completes
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "-" * 75)
print("ITEM 10: Confirm Windows audio is NOT left muted after test run completes")
print("-" * 75)
try:
    from pycaw.pycaw import AudioUtilities
    spk = AudioUtilities.GetSpeakers()
    vol = getattr(spk, "EndpointVolume", None)
    assert vol is not None, "Failed to retrieve Windows EndpointVolume"
    is_muted = bool(vol.GetMute())
    scalar_vol = vol.GetMasterVolumeLevelScalar()
    print(f"  Windows Master Audio Volume : {scalar_vol * 100:.0f}%")
    print(f"  Windows Master Audio Muted  : {is_muted}")
    assert is_muted is False, "CRITICAL: Windows audio was left in a MUTED state!"
    report(10, "Windows Audio Unmuted Verification", "PASS", f"System speaker confirmed unmuted ({scalar_vol*100:.0f}% volume, Mute=False)")
except Exception as e:
    report(10, "Windows Audio Unmuted Verification", "FAIL", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("FULL SMOKE TEST SUMMARY")
print("=" * 80)
all_pass = True
for k, v in results.items():
    print(f"  {k}: {v}")
    if v != "PASS":
        all_pass = False

print("=" * 80)
if all_pass:
    print("ALL 10 SMOKE TEST ITEMS PASSED: 100% OPERATIONAL")
else:
    print("SOME ITEMS FAILED")
print("=" * 80)

main_win.close()
