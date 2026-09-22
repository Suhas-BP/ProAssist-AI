"""
======================================================================
         PROASSIST AI - PHASE 5 MULTILINGUAL AUTOMATED TEST SUITE
   Language Detection, Intent Understanding, Localization & Safety
======================================================================
"""

import sys
import io
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from multilingual.language_detector import LanguageDetector
from multilingual.intent_engine import MultilingualIntentEngine
from multilingual.response_manager import MultilingualResponseManager
from phase2.command_router import CommandRouter
from rag.retriever import Retriever


def test_1_english_language_detection():
    print("\n--- TEST 1: English Language Detection ---")
    detector = LanguageDetector()
    samples = [
        "Open Chrome",
        "What time is it",
        "Search YouTube for Python tutorials",
        "How can I help you today",
    ]
    for s in samples:
        res = detector.detect(s)
        print(f"  Input: '{s}' -> Language: {res['language']} (Confidence: {res['confidence']})")
        assert res["language"] == "en", f"Expected 'en' for '{s}', got '{res['language']}'"
    print(">> [PASS] English language detection verified.")


def test_2_hindi_language_detection():
    print("\n--- TEST 2: Hindi Language Detection ---")
    detector = LanguageDetector()
    samples = [
        "क्रोम खोलो",
        "समय क्या है",
        "यूट्यूब पर गाने चलाओ",
        "ProAssist AI की architecture क्या है?",
    ]
    for s in samples:
        res = detector.detect(s)
        print(f"  Input: '{s}' -> Language: {res['language']} (Confidence: {res['confidence']})")
        assert res["language"] == "hi", f"Expected 'hi' for '{s}', got '{res['language']}'"
    print(">> [PASS] Hindi language detection verified.")


def test_3_kannada_language_detection():
    print("\n--- TEST 3: Kannada Language Detection ---")
    detector = LanguageDetector()
    samples = [
        "ಕ್ರೋಮ್ ತೆರೆಯಿರಿ",
        "ಸಮಯ ಎಷ್ಟು",
        "ಯೂಟ್ಯೂಬ್‌ನಲ್ಲಿ ಹಾಡು ಹಾಕಿ",
        "ProAssist AI ಯ architecture ಏನು?",
    ]
    for s in samples:
        res = detector.detect(s)
        print(f"  Input: '{s}' -> Language: {res['language']} (Confidence: {res['confidence']})")
        assert res["language"] == "kn", f"Expected 'kn' for '{s}', got '{res['language']}'"
    print(">> [PASS] Kannada language detection verified.")


def test_4_multilingual_intent_equivalence():
    print("\n--- TEST 4: Multilingual Intent Equivalence ---")
    engine = MultilingualIntentEngine()

    # Application Launch Equivalence
    en_app = engine.parse_intent("Open Chrome")
    hi_app = engine.parse_intent("क्रोम खोलो")
    kn_app = engine.parse_intent("ಕ್ರೋಮ್ ತೆರೆಯಿರಿ")

    print(f"  EN 'Open Chrome'    -> Intent: {en_app['intent']} | Target: {en_app['target']}")
    print(f"  HI 'क्रोम खोलो'     -> Intent: {hi_app['intent']} | Target: {hi_app['target']}")
    print(f"  KN 'ಕ್ರೋಮ್ ತೆರೆಯಿರಿ' -> Intent: {kn_app['intent']} | Target: {kn_app['target']}")

    assert en_app["intent"] == "open_application" and en_app["target"] == "chrome"
    assert hi_app["intent"] == "open_application" and hi_app["target"] == "chrome"
    assert kn_app["intent"] == "open_application" and kn_app["target"] == "chrome"

    # Time Query Equivalence
    en_time = engine.parse_intent("What time is it")
    hi_time = engine.parse_intent("समय क्या है")
    kn_time = engine.parse_intent("ಸಮಯ ಎಷ್ಟು")

    assert en_time["intent"] == "get_time"
    assert hi_time["intent"] == "get_time"
    assert kn_time["intent"] == "get_time"

    # Search Equivalence
    en_yt = engine.parse_intent("Search YouTube for Believer")
    hi_yt = engine.parse_intent("यूट्यूब पर Believer खोजो")
    kn_yt = engine.parse_intent("ಯೂಟ್ಯೂಬ್‌ನಲ್ಲಿ Believer ಹುಡುಕಿ")

    assert en_yt["intent"] == "youtube_search"
    assert hi_yt["intent"] == "youtube_search"
    assert kn_yt["intent"] == "youtube_search"

    print(">> [PASS] Multilingual intent equivalence across English, Hindi, and Kannada verified.")


def test_5_code_switching_and_mixed_commands():
    print("\n--- TEST 5: Code-Switching & Mixed Commands ---")
    engine = MultilingualIntentEngine()

    # Mixed Hindi + English
    m1 = engine.parse_intent("Chrome kholo")
    print(f"  'Chrome kholo' -> Intent: {m1['intent']} | Target: {m1['target']} | Lang: {m1['language']}")
    assert m1["intent"] == "open_application"
    assert m1["target"] == "chrome"
    assert m1["language"] == "hi"

    # Mixed Kannada + English
    m2 = engine.parse_intent("YouTube ನಲ್ಲಿ Python tutorials search ಮಾಡಿ")
    print(f"  'YouTube ನಲ್ಲಿ Python tutorials search ಮಾಡಿ' -> Intent: {m2['intent']} | Lang: {m2['language']}")
    assert m2["intent"] == "youtube_search"
    assert m2["language"] == "kn"

    print(">> [PASS] Practical code-switching and mixed commands accurately handled.")


def test_6_response_localization_and_tts():
    print("\n--- TEST 6: Response Localization & Runtime TTS ---")
    resp_mgr = MultilingualResponseManager(enable_tts=False)

    # Localized responses for Open Chrome
    en_resp = resp_mgr.localize("open_application", "en", {"target": "chrome"}, "Opening Chrome.")
    hi_resp = resp_mgr.localize("open_application", "hi", {"target": "chrome"}, "Opening Chrome.")
    kn_resp = resp_mgr.localize("open_application", "kn", {"target": "chrome"}, "Opening Chrome.")

    print(f"  EN Response: {en_resp}")
    print(f"  HI Response: {hi_resp}")
    print(f"  KN Response: {kn_resp}")

    assert en_resp == "Opening Chrome."
    assert "क्रोम खोल रहा हूँ" in hi_resp
    assert "ಕ್ರೋಮ್ ತೆರೆಯುತ್ತಿದ್ದೇನೆ" in kn_resp

    # Verify voice detection and graceful fallback
    assert resp_mgr._available_voices is not None
    voice_en = resp_mgr.get_voice_for_language("en")
    assert voice_en is not None, "English SAPI5 voice must be available"

    # Ensure speak_multilingual handles missing voices without exception
    resp_mgr.speak_multilingual("नमस्ते", "hi")
    resp_mgr.speak_multilingual("ನಮಸ್ಕಾರ", "kn")

    print(">> [PASS] Response localization and runtime TTS voice handling verified.")


def test_7_rag_multilingual_retrieval():
    print("\n--- TEST 7: Multilingual RAG Retrieval ---")
    retriever = Retriever()

    # English retrieval
    en_chunks = retriever.retrieve("What is the architecture of the major project?", top_k=2)
    assert len(en_chunks) > 0, "English retrieval must succeed"
    print(f"  EN Query Top Match: {en_chunks[0]['chunk_id']} (Score: {en_chunks[0]['score']})")

    # Hindi retrieval
    hi_chunks = retriever.retrieve("ProAssist AI की architecture क्या है?", top_k=2)
    assert len(hi_chunks) > 0, "Hindi retrieval must succeed"
    print(f"  HI Query Top Match: {hi_chunks[0]['chunk_id']} (Score: {hi_chunks[0]['score']})")

    # Kannada retrieval
    kn_chunks = retriever.retrieve("ProAssist AI ಯ architecture ಏನು?", top_k=2)
    assert len(kn_chunks) > 0, "Kannada retrieval must succeed"
    print(f"  KN Query Top Match: {kn_chunks[0]['chunk_id']} (Score: {kn_chunks[0]['score']})")

    print(">> [PASS] Multilingual RAG context retrieval verified.")


def test_8_existing_security_and_allowlist_enforcement():
    print("\n--- TEST 8: Existing Security & Allowlist Enforcement ---")
    router = CommandRouter()

    # Phase 1 constants intact
    assert config.VOICE_SIMILARITY_THRESHOLD == 0.50
    assert config.WAKE_PHRASE == "agent"



    # Dangerous commands in Hindi and Kannada must be safely blocked as unknown
    hi_threat = router.execute("ड्राइव सी की सभी फाइलें हटाओ", dry_run=True)
    assert hi_threat["executed"] is False
    assert hi_threat["status"] == "unknown"

    kn_threat = router.execute("ಫೈಲ್‌ಗಳನ್ನು ಅಳಿಸಿ", dry_run=True)
    assert kn_threat["executed"] is False
    assert kn_threat["status"] == "unknown"

    print("  Hindi threat blocked: PASS (status=unknown, executed=False)")
    print("  Kannada threat blocked: PASS (status=unknown, executed=False)")
    print(">> [PASS] Existing security thresholds and application allowlists strictly preserved.")


def test_9_language_switch_and_thank_you_localization():
    print("\n--- TEST 9: Language Switch & Thank You Localization ---")
    resp_mgr = MultilingualResponseManager(enable_tts=False)

    # Language switch responses
    en_sw = resp_mgr.localize("language_switch", "en")
    hi_sw = resp_mgr.localize("language_switch", "hi")
    kn_sw = resp_mgr.localize("language_switch", "kn")

    print(f"  EN language_switch: {en_sw}")
    print(f"  HI language_switch: {hi_sw}")
    print(f"  KN language_switch: {kn_sw}")

    assert en_sw == "Switched to English.", f"Expected English switch message, got: {en_sw}"
    assert "हिंदी" in hi_sw, f"Expected Hindi switch message, got: {hi_sw}"
    assert "ಕನ್ನಡ" in kn_sw, f"Expected Kannada switch message, got: {kn_sw}"

    # Thank you responses
    en_ty = resp_mgr.localize("thank_you", "en")
    hi_ty = resp_mgr.localize("thank_you", "hi")
    kn_ty = resp_mgr.localize("thank_you", "kn")

    print(f"  EN thank_you: {en_ty}")
    print(f"  HI thank_you: {hi_ty}")
    print(f"  KN thank_you: {kn_ty}")

    assert "welcome" in en_ty.lower(), f"Expected English thank_you response, got: {en_ty}"
    assert "स्वागत" in hi_ty, f"Expected Hindi thank_you response, got: {hi_ty}"
    assert "ಸ್ವಾಗತ" in kn_ty, f"Expected Kannada thank_you response, got: {kn_ty}"

    print(">> [PASS] Language switch and thank_you localization verified for all 3 languages.")


def test_10_indic_normalize_text_preservation():
    print("\n--- TEST 10: Indic Script Preservation in normalize_text ---")
    from phase2.command_listener import CommandListener

    # Hindi text must be returned unchanged (only punctuation stripped)
    hi_input = "क्रोम खोलो!"
    hi_out = CommandListener.normalize_text(hi_input)
    print(f"  Hindi '{hi_input}' -> '{hi_out}'")
    assert "क्रोम" in hi_out, f"Hindi script should be preserved in output: '{hi_out}'"
    assert "खोलो" in hi_out, f"Hindi verb should be preserved in output: '{hi_out}'"
    assert "!" not in hi_out, "Exclamation mark should be stripped"

    # Kannada text must be returned unchanged
    kn_input = "ಸಮಯ ಎಷ್ಟು?"
    kn_out = CommandListener.normalize_text(kn_input)
    print(f"  Kannada '{kn_input}' -> '{kn_out}'")
    assert "ಸಮಯ" in kn_out, f"Kannada script should be preserved in output: '{kn_out}'"
    assert "?" not in kn_out, "Question mark should be stripped"

    # English text must still be normalized correctly
    en_input = "What's the time?"
    en_out = CommandListener.normalize_text(en_input)
    print(f"  English '{en_input}' -> '{en_out}'")
    assert "what is" in en_out.lower(), f"English contraction should be expanded: '{en_out}'"

    print(">> [PASS] Indic script preserved through normalize_text; English normalization intact.")


def run_all_tests():
    print("=" * 70)
    print("          PROASSIST AI - PHASE 5 MULTILINGUAL TEST SUITE")
    print("=" * 70)

    test_1_english_language_detection()
    test_2_hindi_language_detection()
    test_3_kannada_language_detection()
    test_4_multilingual_intent_equivalence()
    test_5_code_switching_and_mixed_commands()
    test_6_response_localization_and_tts()
    test_7_rag_multilingual_retrieval()
    test_8_existing_security_and_allowlist_enforcement()
    test_9_language_switch_and_thank_you_localization()
    test_10_indic_normalize_text_preservation()

    print("\n" + "=" * 70)
    print("      ALL 10 PHASE 5 MULTILINGUAL TESTS COMPLETED AND PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()

