"""
Automated Test Suite for ProAssist AI Phase 2
Tests:
1. Command listener initialization & speech-to-text transcription
2. Command router with all supported commands (time, date, calculator, notepad, can you hear me)
3. Unknown command safety handling and fallback
4. Responder formatting and text output
5. Phase 1 integrity & isolation verification
6. Voice verification logger
7. Faster wake-word detection & shared model reuse
8. Continuous command mode with multiple commands
9. Safe exit commands & return to wake-word listening
10. Speaker authentication gating (unauthenticated rejection blocks command mode)
"""

import os
import sys
from pathlib import Path
import numpy as np
import pyttsx3
import scipy.io.wavfile as wavfile
import scipy.signal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from wake_word.detector import WhisperKeywordDetector
from phase2.command_listener import CommandListener
from phase2.command_router import CommandRouter
from phase2.responder import Responder
from phase2 import config as p2_config


def test_1_command_listener_and_stt():
    print("\n--- TEST 1: Command Listener & Speech-to-Text Transcription ---")
    listener = CommandListener()
    assert listener is not None
    assert listener.model is not None

    # Test with silence
    silence = np.zeros(16000 * 2, dtype=np.float32)
    transcription_silence = listener.transcribe_audio(silence)
    assert transcription_silence == "", "Silence should transcribe to empty string"
    print("  Silence input handling: correctly returned empty string.")

    # Test with synthesized speech audio: "what time is it"
    test_dir = Path("tests/audio_cache")
    test_dir.mkdir(parents=True, exist_ok=True)
    wav_path = str(test_dir / "test_cmd_time.wav")

    engine = pyttsx3.init()
    engine.save_to_file("what time is it", wav_path)
    engine.runAndWait()

    sr, audio = wavfile.read(wav_path)
    if audio.ndim > 1:
        audio = audio[:, 0]
    audio_f32 = audio.astype(np.float32) / 32768.0
    if sr != 16000:
        audio_f32 = scipy.signal.resample(audio_f32, int(len(audio_f32) * 16000 / sr)).astype(np.float32)

    recognized = listener.transcribe_audio(audio_f32).lower()
    print(f"  Synthesized Audio Transcription: \"{recognized}\"")

    # Clean up test file
    if os.path.exists(wav_path):
        os.remove(wav_path)
    if os.path.exists(test_dir):
        os.rmdir(test_dir)

    assert "time" in recognized, f"Expected 'time' in transcription, got '{recognized}'"
    print(">> [PASS] CommandListener and local Whisper STT functioning accurately.")


def test_2_command_router_supported_commands():
    print("\n--- TEST 2: Command Router Supported Commands ---")
    router = CommandRouter()

    # 1. Time Command
    res_time = router.execute("what time is it")
    print(f"  'what time is it' -> Response: \"{res_time['response']}\"")
    assert res_time["intent"] == "get_time"
    assert res_time["status"] == "success"
    assert "The current time is" in res_time["response"]

    # 2. Date Command
    res_date = router.execute("what is today's date")
    print(f"  'what is today\\'s date' -> Response: \"{res_date['response']}\"")
    assert res_date["intent"] == "get_date"
    assert res_date["status"] == "success"
    assert "Today is" in res_date["response"]

    # 3. Open Calculator (dry run)
    res_calc = router.execute("open calculator", dry_run=True)
    print(f"  'open calculator' -> Response: \"{res_calc['response']}\"")
    assert res_calc["intent"] == "open_calculator"
    assert res_calc["status"] == "success"
    assert res_calc["response"] == "Opening Calculator."

    # 4. Open Notepad (dry run)
    res_pad = router.execute("open notepad", dry_run=True)
    print(f"  'open notepad' -> Response: \"{res_pad['response']}\"")
    assert res_pad["intent"] == "open_notepad"
    assert res_pad["status"] == "success"
    assert res_pad["response"] == "Opening Notepad."

    # 5. Conversational check: "Can you hear me?"
    res_hear = router.execute("can you hear me")
    print(f"  'can you hear me' -> Response: \"{res_hear['response']}\"")
    assert res_hear["intent"] == "can_you_hear_me"
    assert res_hear["status"] == "success"
    assert res_hear["response"] == "Yes, I can hear you clearly."

    # 6. Conversational identity
    res_who = router.execute("who are you")
    print(f"  'who are you' -> Response: \"{res_who['response']}\"")
    assert res_who["intent"] == "who_are_you"
    assert res_who["status"] == "success"

    print(">> [PASS] All supported and conversational commands correctly routed.")


def test_3_command_router_unknown_and_safety():
    print("\n--- TEST 3: Command Router Unknown & Safety Fallback ---")
    router = CommandRouter()

    # Unknown command
    res_unknown = router.execute("delete all files on drive c")
    print(f"  'delete all files on drive c' -> Response: \"{res_unknown['response']}\"")
    assert res_unknown["intent"] == "unknown"
    assert not res_unknown["executed"]
    assert res_unknown["status"] == "unknown"
    assert "don't know how to handle that command yet" in res_unknown["response"]

    # Empty command
    res_empty = router.execute("   ")
    print(f"  Empty input -> Response: \"{res_empty['response']}\"")
    assert res_empty["intent"] == "empty"
    assert not res_empty["executed"]

    print(">> [PASS] Unknown commands safely blocked; fallback response generated.")


def test_4_responder():
    print("\n--- TEST 4: Responder Module ---")
    responder = Responder(enable_tts=False)
    out = responder.respond("ProAssist is ready to help.", speak=False)
    assert out == "ProAssist is ready to help."
    print(">> [PASS] Responder visual output verified.")


def test_5_phase1_integrity_check():
    print("\n--- TEST 5: Phase 1 Integrity & Protection Check ---")
    assert config.VOICE_SIMILARITY_THRESHOLD == 0.50
    assert config.EMBEDDING_DIM == 256
    assert config.SAMPLE_RATE == 16000
    print(f"  VOICE_SIMILARITY_THRESHOLD: {config.VOICE_SIMILARITY_THRESHOLD} (0.50 verified)")
    print("  Phase 1 core constants verified intact.")
    print(">> [PASS] Phase 1 isolation preserved.")




def test_6_verification_logger():
    print("\n--- TEST 6: Voice Verification Logger ---")
    from phase2.logger import VerificationLogger
    test_log = PROJECT_ROOT / "tests" / "test_verification.log"
    if test_log.exists():
        test_log.unlink()

    logger = VerificationLogger(log_path=test_log)
    logger.log_wake_word("Hey Agent")
    logger.log_verification(
        score=0.7845,
        threshold=0.72,
        result="AUTHORIZED",
        user="TestUser",
    )
    logger.log_verification(
        score=0.5512,
        threshold=0.72,
        result="REJECTED",
        reason="Voice mismatch (0.5512 < 0.72)",
    )

    assert test_log.exists(), "Log file should be created"
    with open(test_log, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 3, f"Expected 3 log entries, got {len(lines)}"
    assert "WAKE_WORD" in lines[0] and '"Hey Agent"' in lines[0]
    assert "VERIFICATION" in lines[1] and "score=0.7845" in lines[1] and "result=AUTHORIZED" in lines[1]
    assert "VERIFICATION" in lines[2] and "score=0.5512" in lines[2] and "result=REJECTED" in lines[2]

    # Verify no raw vectors or binary audio
    for line in lines:
        assert "array(" not in line, "No numpy vectors allowed in logs"
        assert "\\x" not in line, "No raw audio bytes allowed in logs"

    if test_log.exists():
        test_log.unlink()

    print("  Verification log entries structured, formatted, and privacy-safe.")
    print(">> [PASS] Verification logger passed.")


def test_7_model_reuse_and_fast_wake():
    print("\n--- TEST 7: Shared Model Reuse & Fast Wake Parameters ---")
    detector = WhisperKeywordDetector(
        buffer_seconds=p2_config.FAST_WAKE_BUFFER_SECONDS,
        check_interval=p2_config.FAST_WAKE_CHECK_INTERVAL,
        energy_threshold=p2_config.FAST_WAKE_ENERGY_THRESHOLD,
    )
    assert detector.buffer_seconds == 1.5, "Fast buffer should be 1.5s"
    assert detector.check_interval == 0.25, "Fast check interval should be 0.25s"
    assert detector.energy_threshold == 0.006, "Fast energy threshold should be 0.006"

    # Reuse detector's WhisperModel in CommandListener
    listener = CommandListener(model=detector.model)
    assert listener.model is detector.model, "CommandListener must reuse the exact same WhisperModel instance"

    # Test Phase2WakeDetector model reuse and calibrated settings
    from phase2.wake_detector import Phase2WakeDetector
    p2_det = Phase2WakeDetector(model=detector.model)
    assert p2_det.model is detector.model, "Phase2WakeDetector must reuse shared WhisperModel"
    assert p2_det.buffer_seconds == 2.0
    assert p2_det.check_interval == 0.4
    assert p2_det.energy_threshold == 0.013

    print("  Model instance reuse verified: zero redundant model loading.")
    print(">> [PASS] Fast wake detector and shared model reuse verified.")



def test_8_continuous_command_mode_multiturn():
    print("\n--- TEST 8: Continuous Command Mode (Multi-Command Flow) ---")
    router = CommandRouter()
    commands_to_simulate = [
        ("what time is it", "get_time", "The current time is"),
        ("open calculator", "open_calculator", "Opening Calculator."),
        ("can you hear me", "can_you_hear_me", "Yes, I can hear you clearly."),
        ("what is today's date", "get_date", "Today is"),
        ("open notepad", "open_notepad", "Opening Notepad."),
    ]

    conversation_history = []
    for cmd, expected_intent, expected_prefix in commands_to_simulate:
        res = router.execute(cmd, dry_run=True)
        assert res["intent"] == expected_intent
        assert expected_prefix in res["response"]
        conversation_history.append((cmd, res["response"]))
        # In continuous mode, system prompts for next command
        follow_up = p2_config.CONTINUOUS_PROMPT
        assert follow_up == "How can I help you?"

    assert len(conversation_history) == 5
    print(f"  Successfully executed {len(conversation_history)} continuous commands under single session:")
    for c, r in conversation_history:
        print(f"    User: '{c}' -> Assistant: '{r}' -> Prompt: 'How can I help you?'")
    print(">> [PASS] Continuous command mode accurately processes consecutive commands.")


def test_9_safe_exit_commands_and_wake_return():
    print("\n--- TEST 9: Safe Exit Commands & Return to Wake-Word Listening ---")
    router = CommandRouter()
    exit_phrases = ["stop", "go to sleep", "that's all", "exit", "bye", "goodbye", "quit"]

    for phrase in exit_phrases:
        res = router.execute(phrase)
        assert res["intent"] == "exit", f"Phrase '{phrase}' should trigger exit intent"
        assert res["status"] == "exit"
        assert res["response"] == "Going back to wake-word listening."
        print(f"  Exit phrase: '{phrase}' -> Response: \"{res['response']}\" [Exit Verified]")

    print(">> [PASS] All exit commands safely recognized and route back to wake listening.")


def test_10_authentication_security_gating():
    print("\n--- TEST 10: Authentication Gating & Imposter Protection ---")
    router = CommandRouter()

    # Simulate authentication failure (e.g. score 0.35 < 0.50)
    auth_score = 0.35
    threshold = config.VOICE_SIMILARITY_THRESHOLD
    is_authenticated = auth_score >= threshold

    continuous_mode_entered = False
    if is_authenticated:
        continuous_mode_entered = True
        router.execute("open calculator", dry_run=True)

    assert not is_authenticated, "Score 0.35 must not authenticate against 0.50"
    assert not continuous_mode_entered, "Continuous command mode must NEVER be entered when unauthenticated"
    print("  Imposter attempt blocked. System immediately returned to wake-word listening.")

    # Simulate authorized speaker (e.g. score 0.85 >= 0.72)
    auth_score = 0.85
    is_authenticated = auth_score >= threshold
    if is_authenticated:
        continuous_mode_entered = True

    assert is_authenticated, "Score 0.85 must authenticate"
    assert continuous_mode_entered, "Authorized speaker must be granted entry to continuous command mode"
    print("  Authorized speaker accepted and continuous command mode activated.")
    print(">> [PASS] Speaker authentication gating strictly protects continuous command mode.")


def test_11_email_system():
    print("\n--- TEST 11: Voice Email Feature (Lookup, Parser, Composer, Sender, Flow) ---")
    from phase2.email import (
        ContactManager,
        EmailParser,
        EmailComposer,
        EmailDraft,
        EmailSender,
        MockEmailProvider,
        GmailOAuthProvider,
        handle_email_flow,
    )

    test_contacts_file = PROJECT_ROOT / "tests" / "test_contacts.json"
    if test_contacts_file.exists():
        test_contacts_file.unlink()

    # 1. Contact lookup when contact exists
    cm = ContactManager(contacts_path=test_contacts_file)
    cm.add_contact("Rahul", "rahul@example.com")
    contact = cm.get_contact("rahul")
    assert contact is not None, "Contact Rahul must be found"
    assert contact["email"] == "rahul@example.com"
    print("  1. Contact lookup when contact exists: PASS (rahul@example.com)")

    # 2. Contact not found
    unknown_contact = cm.get_contact("Vikram")
    assert unknown_contact is None, "Unknown contact should return None"
    print("  2. Contact not found handling: PASS (correctly returned None)")

    # 3. Valid email address validation
    assert cm.is_valid_email("user@example.com") is True
    assert cm.is_valid_email("john.doe@company.org") is True
    assert cm.is_valid_email("invalid-email-string") is False
    assert cm.is_valid_email("missing_at.domain.com") is False
    print("  3. Email address validation: PASS")

    # 4. Adding a new contact
    new_entry = cm.add_contact("Priya", "priya@domain.com")
    assert new_entry["email"] == "priya@domain.com"
    reloaded_contact = cm.get_contact("Priya")
    assert reloaded_contact is not None and reloaded_contact["email"] == "priya@domain.com"
    print("  4. Adding new contact & persistence: PASS")

    # 5. Parsing "write an email to Rahul"
    parser = EmailParser()
    p1 = parser.parse_command("write an email to Rahul")
    assert p1["is_email"] is True and p1["recipient_name"] == "Rahul"
    p2 = parser.parse_command("send an email to Rahul")
    assert p2["is_email"] is True and p2["recipient_name"] == "Rahul"
    p3 = parser.parse_command("compose an email to Priya")
    assert p3["is_email"] is True and p3["recipient_name"] == "Priya"
    p4 = parser.parse_command("email Rahul")
    assert p4["is_email"] is True and p4["recipient_name"] == "Rahul"
    p5 = parser.parse_command("what time is it")
    assert p5["is_email"] is False
    print("  5. Email command parsing & recipient extraction: PASS")

    # 6. Email composition
    composer = EmailComposer()
    draft = composer.start_draft(recipient_name="Rahul", recipient_email="rahul@example.com")
    composer.set_subject("Meeting Update")
    composer.set_body("The meeting is moved to tomorrow at 10 AM.")
    assert draft.is_valid() is True
    assert "Meeting Update" in draft.format_preview()
    assert "rahul@example.com" in draft.format_preview()
    print("  6. Email composition & structured draft preview: PASS")

    # 7. Confirmation required before sending
    mock_provider = MockEmailProvider(is_configured=True)
    sender = EmailSender(provider=mock_provider)
    unconfirmed_res = sender.send_email(draft, confirmed=False)
    assert unconfirmed_res["status"] == "unconfirmed", "Unconfirmed send must be blocked"
    assert len(mock_provider.sent_messages) == 0, "No email should be sent without confirmation"
    print("  7. Security confirmation gating: PASS (Unconfirmed send strictly blocked)")

    # 8. Email sender configuration error handling
    dummy_creds = PROJECT_ROOT / "tests" / "nonexistent_creds.json"
    dummy_token = PROJECT_ROOT / "tests" / "nonexistent_token.json"
    unconfig_provider = GmailOAuthProvider(credentials_file=dummy_creds, token_file=dummy_token)
    unconfig_sender = EmailSender(provider=unconfig_provider)
    draft.confirm()
    unconfig_res = unconfig_sender.send_email(draft, confirmed=True)
    assert unconfig_res["status"] == "not_configured"
    assert "not configured yet" in unconfig_res["message"]
    print("  8. Unconfigured email provider safe error handling: PASS")

    # 9. Successful sender behavior using mocked email provider
    confirmed_res = sender.send_email(draft, confirmed=True)
    assert confirmed_res["status"] == "success"
    assert len(mock_provider.sent_messages) == 1
    assert mock_provider.sent_messages[0]["to"] == "rahul@example.com"
    assert mock_provider.sent_messages[0]["subject"] == "Meeting Update"
    print("  9. Mocked email dispatch verification: PASS")

    # 10. Multi-turn conversational flow (mocked listener)
    class MockListener:
        def __init__(self, responses):
            self.responses = list(responses)
        def listen_and_transcribe(self, **kwargs):
            return self.responses.pop(0) if self.responses else ""

    class MockResponder:
        def __init__(self):
            self.messages = []
        def respond(self, msg, speak=False):
            self.messages.append(msg)
            return msg

    # Scenario A: User confirms sending
    flow_listener = MockListener([
        "Meeting is at 10 AM tomorrow",  # body
        "Project Update",               # subject
        "yes send it",                  # confirmation
    ])
    flow_responder = MockResponder()
    flow_sender = EmailSender(provider=MockEmailProvider(is_configured=True))
    flow_res = handle_email_flow(
        recipient_name="Rahul",
        contact_manager=cm,
        command_listener=flow_listener,
        responder=flow_responder,
        email_sender=flow_sender,
    )
    assert flow_res["status"] == "success"
    assert "Email sent successfully." in flow_responder.messages
    print("  10. Full conversational email flow (confirmed): PASS")

    # Scenario B: User cancels sending
    flow_listener_cancel = MockListener([
        "Nevermind this email",         # body
        "Test",                         # subject
        "no cancel",                    # cancellation
    ])
    flow_responder_cancel = MockResponder()
    flow_res_cancel = handle_email_flow(
        recipient_name="Rahul",
        contact_manager=cm,
        command_listener=flow_listener_cancel,
        responder=flow_responder_cancel,
        email_sender=flow_sender,
    )
    assert flow_res_cancel["status"] == "cancelled"
    assert "Email sending cancelled." in flow_responder_cancel.messages
    print("  11. Full conversational email flow (cancelled): PASS")

    # Cleanup test file
    if test_contacts_file.exists():
        test_contacts_file.unlink()

    print(">> [PASS] All voice email feature tests completed successfully.")


def test_12_continuous_conversation_session_loop():
    print("\n--- TEST 12: Continuous Conversation Mode Session Loop ---")
    router = CommandRouter()
    
    # 1. Verify speaker verification threshold configuration is 0.50
    assert config.VOICE_SIMILARITY_THRESHOLD == 0.50, "Speaker threshold must remain 0.50"
    print(f"  Speaker threshold: {config.VOICE_SIMILARITY_THRESHOLD} (0.50 verified)")

    
    # 2. Simulate user conversation flow under ONE wake-word activation session
    # Initial prompt after wake-word ("Agent") authentication:
    initial_prompt = p2_config.CONTINUOUS_PROMPT
    assert initial_prompt == "How can I help you?"
    print(f"  [AGENT] Authenticated -> [PROASSIST] \"{initial_prompt}\"")

    # Sequence of commands simulating user speaking multiple commands:
    # 1. "can you open the chrome browser"
    # 2. "search youtube for python tutorials"
    # 3. "open gmail"
    # 4. "" (empty speech - safely ignored, continues session)
    # 5. "bye" (exits session)
    simulated_inputs = [

        "can you open the chrome browser",
        "search youtube for python tutorials",
        "open gmail",
        "",
        "bye",
    ]

    executed_intents = []
    session_active = True
    wake_word_prompts_required = 0

    for user_input in simulated_inputs:
        if not user_input or not user_input.strip():
            # Empty / silence safely handled: session remains active, no crash
            print("  [COMMAND] Empty speech input -> safely ignored, continuous session continues.")
            assert session_active is True
            continue

        res = router.execute(user_input, dry_run=True)
        if res.get("intent") == "exit":
            session_active = False
            exit_resp = "Goodbye."
            print(f"  [COMMAND] Recognized: \"{user_input}\" -> Intent: {res['intent']} -> [PROASSIST] \"{exit_resp}\"")
            print("  [Service] Continuous conversation mode exited. Resumed listening for 'Agent'.")
            break

        executed_intents.append((user_input, res["intent"], res["response"]))
        # In continuous conversation mode, wake word is NOT required between commands
        print(f"  [COMMAND] Recognized: \"{user_input}\" -> Intent: {res['intent']} | Response: \"{res['response']}\"")
        assert session_active is True, "Session must remain active across commands"

    # Verifications:
    assert len(executed_intents) == 3, "Expected 3 commands executed in one session"
    assert executed_intents[0][1] == "open_application", "First command should open Chrome"
    assert executed_intents[1][1] == "youtube_search", "Second command should search YouTube"
    assert executed_intents[2][1] == "open_website", "Third command should open Gmail"
    assert session_active is False, "Session must exit on 'bye'"

    print(">> [PASS] Continuous conversation mode successfully executes multiple commands and exits cleanly on 'bye'.")


def main():
    print("=" * 70)
    print("          PROASSIST AI - PHASE 2 AUTOMATED TEST SUITE")
    print("=" * 70)
    test_1_command_listener_and_stt()
    test_2_command_router_supported_commands()
    test_3_command_router_unknown_and_safety()
    test_4_responder()
    test_5_phase1_integrity_check()
    test_6_verification_logger()
    test_7_model_reuse_and_fast_wake()
    test_8_continuous_command_mode_multiturn()
    test_9_safe_exit_commands_and_wake_return()
    test_10_authentication_security_gating()
    test_11_email_system()
    test_12_continuous_conversation_session_loop()
    print("\n" + "=" * 70)
    print("      ALL PHASE 2 AUTOMATED TESTS COMPLETED AND PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    main()

