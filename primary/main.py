"""
ProAssist AI - Phase 1 Main Background Orchestrator
Continuously listens for the wake phrase in the background, captures
speaker voice, computes neural embedding, verifies cosine similarity against
the enrolled voiceprint, and activates the assistant upon successful authentication.
"""

import sys
import io
import time
import signal
import builtins

# Force unbuffered output across the entire application
_orig_print = builtins.print
def _unbuffered_print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _orig_print(*args, **kwargs)
builtins.print = _unbuffered_print

# Ensure UTF-8 output and immediate unbuffered flushing on Windows console
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", line_buffering=True, write_through=True)
            sys.stderr.reconfigure(encoding="utf-8", line_buffering=True, write_through=True)
        else:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True, write_through=True)
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True, write_through=True)
    except Exception:
        pass

    # Disable Windows Console QuickEdit Mode to prevent accidental mouse clicks from freezing the process
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        h_in = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(h_in, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080
            new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(h_in, new_mode)
    except Exception:
        pass

import pyttsx3
import numpy as np
import config
from wake_word.audio_stream import MicrophoneStream, record_audio
from wake_word.detector import get_wake_word_detector
from voice_auth.verifier import VoiceVerifier
from voice_auth.liveness import LivenessChecker
from phase2.command_listener import CommandListener
from phase2.command_router import CommandRouter
from phase2.responder import Responder
from phase2.email import ContactManager, EmailSender, handle_email_flow
from phase2.logger import get_verification_logger


def speak_feedback(text: str):
    """Speaks feedback aloud using pyttsx3."""
    if config.ENABLE_TTS:
        try:
            from phase2.responder import get_cached_tts_engine
            engine = get_cached_tts_engine()
            if engine is None:
                engine = pyttsx3.init()
            rate = getattr(config, "TTS_RATE", 200)
            engine.setProperty("rate", rate)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"[TTS Error] {e}")


def main():
    print("=" * 70)
    print("      PROASSIST AI - BACKGROUND SERVICE (PHASE 1)")
    print("  Intelligent Multilingual Voice Assistant - Core Security Engine")
    print("=" * 70)
    print(f"[*] Engine             : {config.WAKE_WORD_ENGINE}")
    print(f"[*] Wake Phrase        : \"{config.WAKE_PHRASE.upper()}\"")
    print(f"[*] Voice Threshold    : {config.VOICE_SIMILARITY_THRESHOLD:.2f}")
    print(f"[*] Liveness Anti-Replay: {'ENABLED' if config.ENABLE_LIVENESS else 'DISABLED'}")
    print("=" * 70)

    # 1. Initialize Voice Verifier
    print("[1/4] Loading speaker verification model...")
    verifier = VoiceVerifier()
    if not verifier.is_enrolled():
        print("\n[ALERT] No enrolled voiceprint found!")
        print("[ACTION] Please first register your voice by running:")
        print("         python voice_auth/enroll.py\n")
        sys.exit(1)

    # 2. Initialize Liveness module if configured
    liveness_checker = LivenessChecker(verifier=verifier) if config.ENABLE_LIVENESS else None

    # 3. Initialize Wake-Word Detector
    print("[2/4] Loading wake-word detector ('Agent')...")
    detector = get_wake_word_detector()

    # 4. Initialize Command Execution Modules
    print("[3/4] Initializing command listener & execution engine...")
    responder = Responder(enable_tts=config.ENABLE_TTS)
    command_listener = CommandListener(multilingual=True)
    contact_manager = ContactManager()
    email_sender = EmailSender()
    command_router = CommandRouter(contact_manager=contact_manager)
    logger = get_verification_logger()
    print("[4/4] All systems initialized successfully!\n")

    # 5. Handle clean termination
    service_start_time = time.time()
    running = True
    shutdown_reason = None

    def handle_signal(sig, frame):
        nonlocal running, shutdown_reason
        elapsed = time.time() - service_start_time
        # Suppress transient console signals delivered within 1.0s of process launch
        if elapsed < 1.0:
            print(f"[DEBUG] Ignored startup console signal ({sig}) at {elapsed:.2f}s.")
            return
        shutdown_reason = f"OS Signal {sig} (Ctrl+C)"
        print("\n[Service] Shutdown signal received. Stopping ProAssist AI...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_signal)

    print("[Service] ProAssist AI is running in the background...")
    print(f"[Service] Listening for wake phrase: \"{config.WAKE_PHRASE}\" (Press Ctrl+C to stop)")
    print("[Service] Speak clearly: say \"Agent\" to begin.\n")

    # 6. Continuous background listening loop
    loop_ticks = 0
    first_chunk_logged = False
    try:
        while running:
            mic_stream = MicrophoneStream()
            try:
                mic_stream.start()
                print("[Ready] Microphone stream active. Waiting for wake word 'agent'...")
                while running:
                    try:
                        pcm_bytes, chunk_int16 = mic_stream.read_chunk()
                    except Exception as read_err:
                        if not getattr(mic_stream, "is_running", True):
                            break
                        print(f"[DEBUG] Microphone read error: {read_err}. Retrying...")
                        time.sleep(0.05)
                        continue

                    # Safe handling of empty buffers or stopped stream
                    if chunk_int16 is None or len(chunk_int16) == 0:
                        if not getattr(mic_stream, "is_running", True):
                            break
                        time.sleep(0.02)
                        continue

                    if not first_chunk_logged:
                        first_chunk_logged = True
                        chunk_f32 = chunk_int16.astype(np.float32) / 32768.0
                        rms = float(np.sqrt(np.mean(chunk_f32 ** 2)))
                        peak = float(np.max(np.abs(chunk_f32)))
                        dev_info = mic_stream.get_device_info()
                        print(f"[Mic] Connected Device: {dev_info.get('name', 'Default')}")
                        print(f"[Mic] Sample rate: {mic_stream.sample_rate}Hz | Baseline RMS: {rms:.4f} | Peak: {peak:.4f}\n")

                    loop_ticks += 1
                    # Periodic heartbeat every ~10 seconds (approx 125 chunks of 80ms)
                    if loop_ticks % 125 == 0:
                        print("[Heartbeat] ProAssist listening... (Say 'Agent' to activate)")

                    # Check wake word
                    try:
                        wake_detected = detector.is_detected(chunk_int16)
                    except Exception as det_err:
                        import traceback
                        print(f"[DEBUG] Wake detector exception: {det_err}")
                        traceback.print_exc()
                        wake_detected = False

                    if not wake_detected:
                        continue

                    print("\n" + "#" * 60)
                    print(f"[*] WAKE WORD DETECTED! Starting speaker verification...")
                    print("#" * 60)

                    # Temporarily stop wake stream to free microphone for authentication
                    mic_stream.stop()
                    logger.log_wake_word(config.WAKE_PHRASE)

                    is_authenticated = False
                    user_name = "User"

                    if config.ENABLE_LIVENESS and liveness_checker:
                        # Challenge-Response Liveness Flow
                        passed, report = liveness_checker.verify_liveness_challenge()
                        if passed:
                            is_authenticated = True
                            user_name = verifier.enrolled_meta.get("user_name", "User")
                            sim = report.get("speaker_similarity", 1.0)
                            print("[AGENT] Authenticated")
                            logger.log_verification(
                                score=sim,
                                threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                result="AUTHORIZED",
                                user=user_name,
                            )
                        else:
                            sim = report.get("speaker_similarity", 0.0)
                            reason = report.get("reason", "Liveness or voice mismatch")
                            print("[AGENT] Voice or challenge mismatch. Ignoring request.")
                            print("[AGENT] Returning to background listening mode.")
                            logger.log_verification(
                                score=sim,
                                threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                result="REJECTED",
                                reason=reason,
                            )

                    else:
                        # Direct Voice Verification Flow
                        # 1. First, verify the speaker's voice directly from the wake utterance buffer
                        wake_audio = getattr(detector, "get_last_detected_audio", lambda: None)()
                        if wake_audio is None:
                            wake_audio = getattr(detector, "last_detected_audio", None)

                        is_auth = False
                        similarity = 0.0
                        details = {}

                        if wake_audio is not None and len(wake_audio) > 0:
                            is_auth, similarity, details = verifier.verify_audio(wake_audio)
                            print(f"[*] Wake-Utterance Voice Similarity: {similarity:.4f} | Threshold: {config.VOICE_SIMILARITY_THRESHOLD:.2f}")

                        # 2. If wake utterance already meets the threshold (e.g. user said "Agent"), authenticate immediately!
                        if is_auth:
                            is_authenticated = True
                            user_name = details.get("user", "User")
                            print(f"[AGENT] Authenticated via wake utterance ({similarity:.4f} >= {config.VOICE_SIMILARITY_THRESHOLD:.2f})")
                            logger.log_verification(
                                score=similarity,
                                threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                result="AUTHORIZED",
                                user=user_name,
                            )
                        else:
                            # 3. Fallback: If wake utterance was too brief or borderline, record follow-up speech
                            print(f"[*] Borderline wake score ({similarity:.4f}). Please say 'Agent' or your name ({config.AUTH_RECORD_DURATION}s)...")
                            speak_feedback("Please confirm")
                            auth_audio = record_audio(duration_seconds=config.AUTH_RECORD_DURATION)
                            is_auth_followup, sim_followup, details_followup = verifier.verify_audio(auth_audio)

                            # Also evaluate combined utterance (wake audio + follow-up audio) for maximum acoustic context
                            sim_combined = 0.0
                            is_auth_combined = False
                            if wake_audio is not None and len(wake_audio) > 0:
                                combined_audio = np.concatenate([wake_audio, auth_audio])
                                is_auth_combined, sim_combined, _ = verifier.verify_audio(combined_audio)

                            best_sim = max(similarity, sim_followup, sim_combined)
                            print(f"[*] Best Voice Similarity: {best_sim:.4f} (Wake: {similarity:.4f}, Follow-up: {sim_followup:.4f}, Combined: {sim_combined:.4f}) | Threshold: {config.VOICE_SIMILARITY_THRESHOLD:.2f}")

                            if best_sim >= config.VOICE_SIMILARITY_THRESHOLD:
                                is_authenticated = True
                                user_name = details.get("user") or details_followup.get("user") or "User"
                                print("[AGENT] Authenticated")
                                logger.log_verification(
                                    score=best_sim,
                                    threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                    result="AUTHORIZED",
                                    user=user_name,
                                )
                            else:
                                print(f"[AGENT] Authenticated: NO -> Voice mismatch ({best_sim:.4f} < {config.VOICE_SIMILARITY_THRESHOLD:.2f}).")
                                print("[AGENT] Ignoring request and returning to listening.")
                                logger.log_verification(
                                    score=best_sim,
                                    threshold=config.VOICE_SIMILARITY_THRESHOLD,
                                    result="REJECTED",
                                    reason=f"Voice mismatch ({best_sim:.4f} < {config.VOICE_SIMILARITY_THRESHOLD:.2f})",
                                )

                    # =========================================================
                    # ACTIVATION & CONTINUOUS CONVERSATION FLOW
                    # =========================================================
                    if is_authenticated:
                        # 1. Speak "How can I help you?"
                        prompt_phrase = "How can I help you?"
                        responder.respond(prompt_phrase, speak=True)
                        time.sleep(0.05)

                        # 2. Multi-turn continuous conversation loop
                        consecutive_silence = 0
                        while running:
                            print("[COMMAND] Listening for next command... (Say 'stop', 'bye', or 'that's all' to finish)")
                            command_text = command_listener.listen_and_transcribe()

                            if not command_text or not command_text.strip():
                                consecutive_silence += 1
                                if consecutive_silence >= 2:
                                    print("[COMMAND] No speech detected. Returning to standby.\n")
                                    break
                                else:
                                    print("[COMMAND] Still listening... (Say a command or 'stop')\n")
                                    continue

                            # Reset silence counter on valid speech
                            consecutive_silence = 0
                            print(f'[COMMAND] Recognized Text: "{command_text}"')
                            print("[COMMAND] Executing...")
                            result = command_router.execute(command_text, dry_run=False)

                            # Check for exit commands ("bye", "goodbye", "stop", "exit", "that's all", etc.)
                            if result.get("intent") == "exit":
                                exit_resp = result.get("response") or "Going back to wake-word listening."
                                responder.respond(exit_resp, speak=True)
                                print(f'[Service] Conversation session ended on "{command_text}".\n')
                                break
                            elif result.get("intent") == "email_compose":
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

                            print("[COMMAND] Action completed. Ready for your next command.\n")
                            time.sleep(0.05)

                    # Return to background listening for the wake word "Agent"
                    detector.reset()
                    print(f'[Service] Resumed listening for "{config.WAKE_PHRASE.title()}". Say "Agent" to begin.\n')
                    break

            except Exception as e:
                if running:
                    import traceback
                    print(f"[Stream Error] {e}. Restarting stream in 1 second...")
                    traceback.print_exc()
                    time.sleep(1)
            finally:
                mic_stream.stop()

    except KeyboardInterrupt:
        shutdown_reason = "KeyboardInterrupt (Ctrl+C)"
        print("\n[Service] Shutdown signal received (Ctrl+C). Stopping ProAssist AI...")
        running = False
    finally:
        if not running and shutdown_reason:
            print(f"[DEBUG] Main loop terminated. Reason: {shutdown_reason}")
        print("[Service] ProAssist AI service terminated gracefully.")


if __name__ == "__main__":
    main()
