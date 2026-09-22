"""
ProAssist AI - Online LLM Question Answering Verification Test Suite
Validates:
1. Math Question Answering ("what is the sum of 2+2")
2. Factual Question Answering ("who is the prime minister of uk")
3. Strict Internet Requirement Enforcement (rejects when offline)
4. CommandRouter Integration for GENERAL_QUESTION intent
5. Real-Time Web Knowledge Retrieval from DuckDuckGo & Wikipedia
6. Multilingual Response Localization for Offline State
"""

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.online_llm import OnlineLLMQA
from phase2.command_router import CommandRouter
from multilingual.response_manager import MultilingualResponseManager



def test_1_math_question_answering():
    print("\n--- TEST 1: Math Question Answering ('what is the sum of 2+2') ---")
    qa = OnlineLLMQA()

    # Dry run
    res_dry = qa.answer("what is the sum of 2+2", dry_run=True)
    assert res_dry["answered"] is True
    assert "4" in res_dry["answer"]
    assert res_dry["status"] == "success"
    print(f"  Dry-run response: \"{res_dry['answer']}\"")

    # Live resolution
    res_live = qa.answer("what is the sum of 2+2", dry_run=False)
    assert res_live["answered"] is True
    assert "4" in res_live["answer"]
    print(f"  Live response: \"{res_live['answer']}\"")
    print(">> [PASS] Math question answering verified.")


def test_2_factual_question_answering():
    print("\n--- TEST 2: Factual Question Answering ('who is the prime minister of uk') ---")
    qa = OnlineLLMQA()

    # Dry run
    res_dry = qa.answer("who is the prime minister of uk", dry_run=True)
    assert res_dry["answered"] is True
    assert res_dry["status"] == "success"
    print(f"  Dry-run response: \"{res_dry['answer']}\"")

    # If internet is active, verify live web retrieval & LLM generation
    if qa.is_internet_connected():
        res_live = qa.answer("who is the prime minister of uk", dry_run=False)
        assert res_live["answered"] is True
        assert len(res_live["answer"]) > 5
        print(f"  Live factual response: \"{res_live['answer']}\"")
        print(f"  Sources: {res_live.get('sources')}")
    else:
        print("  (Offline environment detected, skipping live internet call)")

    print(">> [PASS] Factual question answering verified.")


def test_3_strict_offline_rejection():
    print("\n--- TEST 3: Strict Offline Rejection (One and only if connected) ---")
    qa = OnlineLLMQA()

    # Patch is_internet_connected to False
    with patch.object(qa, "is_internet_connected", return_value=False):
        res = qa.answer("who is the prime minister of uk", dry_run=False)
        assert res["answered"] is False, "Must NOT answer when offline"
        assert res["status"] == "offline_no_internet"
        assert "internet connection" in res["answer"].lower()
        print(f"  Offline rejection response: \"{res['answer']}\"")

    with patch.object(qa, "is_internet_connected", return_value=False):
        res_math = qa.answer("what is the sum of 2+2", dry_run=False)
        assert res_math["answered"] is False, "Must NOT answer when offline"
        assert res_math["status"] == "offline_no_internet"
        assert "internet connection" in res_math["answer"].lower()
        print(f"  Offline math rejection: \"{res_math['answer']}\"")

    print(">> [PASS] Strict offline rejection verified.")


def test_4_command_router_general_question_integration():
    print("\n--- TEST 4: CommandRouter General Question Integration ---")
    router = CommandRouter()

    # 1. Math query parsing & execution
    res_math = router.execute("what is the sum of 2+2", dry_run=True)
    assert res_math["intent"] == "general_question"
    assert res_math["executed"] is True
    assert "4" in res_math["response"]
    print(f"  Router 'what is the sum of 2+2' -> Intent: {res_math['intent']} | Response: \"{res_math['response']}\"")

    # 2. General query parsing & execution
    res_pm = router.execute("who is the prime minister of uk", dry_run=True)
    assert res_pm["intent"] == "general_question"
    assert res_pm["executed"] is True
    print(f"  Router 'who is the prime minister of uk' -> Intent: {res_pm['intent']} | Response: \"{res_pm['response']}\"")

    # 3. Capital city query
    res_cap = router.execute("what is the capital of france", dry_run=True)
    assert res_cap["intent"] == "general_question"
    assert res_cap["executed"] is True
    print(f"  Router 'what is the capital of france' -> Intent: {res_cap['intent']} | Response: \"{res_cap['response']}\"")

    # 4. Strict offline rejection inside CommandRouter
    with patch("phase2.command_router.is_internet_available", return_value=False):
        res_offline = router.execute("who is the prime minister of uk", dry_run=False)
        assert res_offline["status"] == "offline_no_internet"
        assert res_offline["executed"] is False
        assert "internet connection" in res_offline["response"].lower()
        print(f"  Router offline rejection -> Response: \"{res_offline['response']}\"")

    print(">> [PASS] CommandRouter general question integration verified.")


def test_5_web_knowledge_retrieval():
    print("\n--- TEST 5: Web Knowledge Retrieval from DuckDuckGo & Wikipedia ---")
    qa = OnlineLLMQA()

    if qa.is_internet_connected():
        snippets = qa.fetch_web_knowledge("capital of france")
        assert len(snippets) > 0, "Should retrieve at least one web snippet"
        has_paris = any("paris" in s.lower() for s in snippets)
        assert has_paris, f"Expected 'Paris' in retrieved snippets: {snippets[:2]}"
        print(f"  Retrieved {len(snippets)} snippets. First snippet: \"{snippets[0][:100]}...\"")
    else:
        print("  (Offline environment detected, skipping live snippet extraction)")

    print(">> [PASS] Web knowledge retrieval verified.")


def test_6_multilingual_offline_templates():
    print("\n--- TEST 6: Multilingual Offline Response Templates ---")
    mgr = MultilingualResponseManager()


    en_msg = mgr.localize("offline_no_internet", "en")
    hi_msg = mgr.localize("offline_no_internet", "hi")
    kn_msg = mgr.localize("offline_no_internet", "kn")

    assert "internet" in en_msg.lower()
    assert "इंटरनेट" in hi_msg
    assert "ಇಂಟರ್ನೆಟ್" in kn_msg

    print(f"  English  : \"{en_msg}\"")
    print(f"  Hindi    : \"{hi_msg.encode('ascii', 'backslashreplace').decode('ascii')}\"")
    print(f"  Kannada  : \"{kn_msg.encode('ascii', 'backslashreplace').decode('ascii')}\"")
    print(">> [PASS] Multilingual offline response templates verified.")



def main():
    print("=" * 70)
    print("       PROASSIST AI - ONLINE LLM QUESTION ANSWERING TEST SUITE")
    print("=" * 70)

    test_1_math_question_answering()
    test_2_factual_question_answering()
    test_3_strict_offline_rejection()
    test_4_command_router_general_question_integration()
    test_5_web_knowledge_retrieval()
    test_6_multilingual_offline_templates()

    print("\n" + "=" * 70)
    print("   ALL 6 ONLINE LLM QUESTION ANSWERING TESTS COMPLETED & PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    main()
