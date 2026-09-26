"""
ProAssist AI - Phase 2 Main Orchestrator
Integrates Phase 1 Security (Wake-Word Detection + Speaker Verification)
with Phase 2 Command Execution (Fast Wake Detection + Model Reuse +
Continuous Conversational Mode + Safe Exit Routing + Verification Logging).
Runs as a background process without modifying any Phase 1 code.
"""

import sys
import time
import signal
from pathlib import Path
import numpy as np

# Ensure UTF-8 console encoding and immediate unbuffered output for live debugging telemetry
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass


# Add project root to sys.path and remove script directory to avoid shadowing stdlib
PROJECT_ROOT = Path(__file__).resolve().parent.parent
script_dir = str(Path(__file__).resolve().parent)
while script_dir in sys.path:
    sys.path.remove(script_dir)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import config
from wake_word.audio_stream import MicrophoneStream, record_audio
from wake_word.detector import WhisperKeywordDetector, get_wake_word_detector
from voice_auth.verifier import VoiceVerifier
from voice_auth.liveness import LivenessChecker

# Phase 2 Components
from phase2.command_listener import CommandListener
from phase2.command_router import CommandRouter
from phase2.responder import Responder
from phase2.logger import get_verification_logger
from phase2.email import ContactManager, EmailSender, handle_email_flow
from phase2.wake_detector import Phase2WakeDetector
from phase2 import config as p2_config




def main():
    print("=" * 70)
    print("      PROASSIST AI - BACKGROUND ASSISTANT (PHASE 1 + PHASE 2)")
    print("   Intelligent Multilingual Voice Assistant - Secure Command Core")
    print("=" * 70)
    print(f"[*] Engine             : {config.WAKE_WORD_ENGINE}")
    print(f"[*] Wake Phrase        : \"{config.WAKE_PHRASE.upper()}\"")
    print(f"[*] Voice Threshold    : {config.VOICE_SIMILARITY_THRESHOLD:.2f}")
    print(f"[*] Liveness Check     : {'ENABLED' if config.ENABLE_LIVENESS else 'DISABLED'}")
    print(f"[*] Continuous Mode    : ENABLED (\"How can I help you?\")")
    print("=" * 70)

    # 1. Initialize Phase 1 Security Modules
    verifier = VoiceVerifier()
    if not verifier.is_enrolled():
        print("\n[ALERT] No enrolled voiceprint found!")
        print("[ACTION] Please register your voice first by running:")
        print("         python voice_auth/enroll.py\n")
        sys.exit(1)

    liveness_checker = LivenessChecker(verifier=verifier) if config.ENABLE_LIVENESS else None

    # Initialize Phase 2 Wake-Word Detector with calibrated threshold and telemetry

    if config.WAKE_WORD_ENGINE == "whisper_keyword":
        detector = Phase2WakeDetector(
            buffer_seconds=p2_config.WAKE_BUFFER_SECONDS,
            check_interval=p2_config.WAKE_CHECK_INTERVAL,
            energy_threshold=p2_config.WAKE_ENERGY_THRESHOLD,
        )
    else:
        detector = get_wake_word_detector()

    # 2. Initialize Phase 2 Command & Response Modules
    responder = Responder(enable_tts=config.ENABLE_TTS)
    # Share initialized Whisper model from detector to avoid duplicate model loading
    shared_whisper_model = getattr(detector, "model", None)
    command_listener = CommandListener(model=shared_whisper_model)
    contact_manager = ContactManager()
    email_sender = EmailSender()
    command_router = CommandRouter(contact_manager=contact_manager)
    logger = get_verification_logger()


    # 3. Clean signal handling
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        print("\n[Service] Shutdown signal received. Stopping ProAssist AI Phase 2...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)

    print("\n[Service] ProAssist AI Phase 2 is running in the background...")
    print(f"[Service] Listening for wake phrase: \"{config.WAKE_PHRASE}\" (Press Ctrl+C to stop)\n")

    # 4. Background service loop
    chunk_counter = 0
    consecutive_failures = 0          # tracks consecutive failed auth attempts
    lockout_until = 0.0               # timestamp when lockout expires

    def speak_access_denied():
        """Speaks 'Access denied' aloud so unauthorized person is clearly informed."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", getattr(config, "TTS_RATE", 200))
            engine.say("Access denied. Voice not recognized.")
            engine.runAndWait()
        except Exception:
            pass

    while running:
        mic_stream = MicrophoneStream()
        try:
            mic_stream.start()
            # Step 1: Microphone opened successfully - report device info
            try:
                pa = mic_stream.pyaudio_instance
                dev_idx = mic_stream.device_index
                if dev_idx is None:
                    dev_info = pa.get_default_input_device_info()
                else:
                    dev_info = pa.get_device_info_by_index(dev_idx)
                print(f"[Microphone] Opened successfully: [{dev_info.get('index')}] {dev_info.get('name')}")
                print(f"  Sample Rate: {mic_stream.sample_rate} Hz | Channels: {mic_stream.channels} | Chunk Size: {mic_stream.chunk_size}")
            except Exception as dev_err:
                print(f"[Microphone] Opened successfully (Device query note: {dev_err})")

            while running:
                pcm_bytes, chunk_int16 = mic_stream.read_chunk()
                chunk_counter += 1
                chunk_f32 = chunk_int16.astype(np.float32) / 32768.0
                chunk_rms = float(np.sqrt(np.mean(chunk_f32 ** 2)))

                # Step 2 & 3: Audio received telemetry (every ~1.2s)
                if chunk_counter % 15 == 0:
                    print(f"[WakeWord DEBUG] Audio received | Chunks: {chunk_counter} | RMS: {chunk_rms:.4f}")

                # Check wake word
                if detector.is_detected(chunk_int16):
                    print(f"[WakeWord DEBUG] Wake match: TRUE")

                    # Security lockout check — ignore wake word if still locked out
                    now = time.time()
                    if now < lockout_until:
                        remaining = int(lockout_until - now)
                        print(f"[SECURITY] System in lockout. Ignoring wake word. ({remaining}s remaining)")
                        continue

                    print("\n" + "#" * 65)
                    print(f"[*] [Phase1] Starting speaker verification...")
                    print("#" * 65)

                    mic_stream.stop()
                    logger.log_wake_word(config.WAKE_PHRASE)

                    is_authenticated = False
                    user_name = "User"

                    # ─────────────────────────────────────────────────────────
                    # Speaker Authentication (Phase 1 Security Engine)
                    # ─────────────────────────────────────────────────────────
                    if config.ENABLE_LIVENESS and liveness_checker:
                        passed, report = liveness_checker.verify_liveness_challenge()
                        if passed:
                            is_authenticated = True
                            consecutive_failures = 0
                            user_name = verifier.enrolled_meta.get("user_name", "User")
                            sim = report.get("speaker_similarity", 1.0)
                            print(f"[AGENT] Liveness + Voice verified! Similarity: {sim:.4f}")
                            logger.log_verification(
                                score=sim,
                                threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                result="AUTHORIZED",
                                user=user_name,
                            )
                        else:
                            sim = report.get("speaker_similarity", 0.0)
                            content_ok = report.get("content_passed", False)
                            voice_ok = report.get("speaker_passed", False)
                            reason = (
                                "Voice mismatch (different speaker)" if not voice_ok
                                else "Challenge phrase not spoken correctly"
                            )
                            consecutive_failures += 1
                            print(f"[SECURITY] UNAUTHORIZED ACCESS ATTEMPT BLOCKED")
                            print(f"  Voice Similarity : {sim:.4f} (need >= {config.LIVENESS_SIMILARITY_THRESHOLD:.2f})")
                            print(f"  Content Match    : {'PASS' if content_ok else 'FAIL'}")
                            print(f"  Reason           : {reason}")
                            print(f"  Consecutive fails: {consecutive_failures}/{config.AUTH_MAX_ATTEMPTS}")
                            logger.log_verification(
                                score=sim,
                                threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                result="REJECTED",
                                reason=reason,
                            )
                            # Speak audible rejection so imposter hears it
                            speak_access_denied()
                    else:
                        print(f"[*] Recording {config.AUTH_RECORD_DURATION}s voice sample for authentication...")
                        auth_audio = record_audio(duration_seconds=config.AUTH_RECORD_DURATION)
                        is_auth, similarity, details = verifier.verify_audio(auth_audio)

                        print(f"[*] Cosine Similarity: {similarity:.4f} | Threshold: {config.VOICE_SIMILARITY_THRESHOLD:.2f}")
                        if is_auth:
                            is_authenticated = True
                            consecutive_failures = 0
                            user_name = details.get("user", "User")
                            print("[AGENT] Authenticated")
                            logger.log_verification(
                                score=similarity,
                                threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                result="AUTHORIZED",
                                user=user_name,
                            )
                        else:
                            consecutive_failures += 1
                            print(f"[SECURITY] UNAUTHORIZED ACCESS ATTEMPT BLOCKED")
                            print(f"  Voice mismatch: {similarity:.4f} < {config.VOICE_SIMILARITY_THRESHOLD:.2f}")
                            print(f"  This voice does NOT match the enrolled speaker.")
                            print(f"  Consecutive fails: {consecutive_failures}/{config.AUTH_MAX_ATTEMPTS}")
                            logger.log_verification(
                                score=similarity,
                                threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                result="REJECTED",
                                reason=f"Voice mismatch ({similarity:.4f} < {config.VOICE_SIMILARITY_THRESHOLD:.2f})",
                            )
                            # Speak audible rejection so imposter hears it
                            speak_access_denied()

                    # ─────────────────────────────────────────────────────────
                    # Security lockout after consecutive failures
                    # ─────────────────────────────────────────────────────────
                    if not is_authenticated and consecutive_failures >= config.AUTH_MAX_ATTEMPTS:
                        lockout_until = time.time() + config.AUTH_LOCKOUT_SECONDS
                        print(f"\n[SECURITY] *** LOCKOUT ACTIVATED ***")
                        print(f"  {consecutive_failures} consecutive failed authentication attempts detected.")
                        print(f"  System locked for {config.AUTH_LOCKOUT_SECONDS} seconds.")
                        print(f"  No commands will be accepted during lockout.\n")
                        try:
                            import pyttsx3
                            engine = pyttsx3.init()
                            engine.setProperty("rate", getattr(config, "TTS_RATE", 200))
                            engine.say(f"Security lockout. System locked for {config.AUTH_LOCKOUT_SECONDS} seconds.")
                            engine.runAndWait()
                        except Exception:
                            pass
                        consecutive_failures = 0  # reset for next cycle

                    # ─────────────────────────────────────────────────────────
                    # ACTIVATION & CONTINUOUS CONVERSATION FLOW
                    # ─────────────────────────────────────────────────────────
                    if is_authenticated:
                        # 1. Speak "How can I help you?"
                        prompt_phrase = "How can I help you?"
                        responder.respond(prompt_phrase, speak=True)

                        # Audio device release delay before starting microphone
                        time.sleep(0.3)

                        # 2. Continuous conversation loop
                        while running:
                            print("[COMMAND] Listening...")
                            command_text = command_listener.listen_and_transcribe()

                            # Handle empty / silence safely without ending conversation
                            if not command_text or not command_text.strip():
                                print("[COMMAND] No speech recognized. Listening again...\n")
                                continue

                            print(f'[COMMAND] Recognized Text: "{command_text}"')
                            print("[COMMAND] Executing...")
                            result = command_router.execute(command_text, dry_run=False)

                            # Check for exit commands ("bye", "goodbye", "stop", "exit", etc.)
                            if result.get("intent") == "exit":
                                exit_resp = "Goodbye."
                                responder.respond(exit_resp, speak=True)
                                print(f'[Service] Resumed listening for "{config.WAKE_PHRASE.title()}"\n')
                                break

                            # Check for email flow
                            if result.get("intent") == "email_compose":
                                handle_email_flow(
                                    recipient_name=result.get("recipient_name", "Someone"),
                                    contact_manager=contact_manager,
                                    command_listener=command_listener,
                                    responder=responder,
                                    email_sender=email_sender,
                                )
                            else:
                                response_text = result.get("response", "")
                                if response_text:
                                    responder.respond(response_text, speak=True, language=result.get("language", "en"))

                            print("[COMMAND] Action completed\n")
                            time.sleep(0.3)

                    # Return to listening for the wake word "Agent"
                    detector.reset()
                    break

        except Exception as e:
            if running:
                print(f"[Stream Error] {e}. Restarting stream in 1 second...")
                time.sleep(1)
        finally:
            mic_stream.stop()

    print("[Service] ProAssist AI Phase 2 terminated gracefully.")


if __name__ == "__main__":
    main()
