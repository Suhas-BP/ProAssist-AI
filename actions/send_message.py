import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional
from core.tool import AgentTool

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.06
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

def _get_os() -> str:
    try:
        cfg = json.loads(
            (_base_dir() / "config" / "api_keys.json").read_text(encoding="utf-8")
        )
        return cfg.get("os_system", "windows").lower()
    except Exception:
        return "windows"


def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")


def _paste_text(text: str) -> None:
    _require_pyautogui()

    os_name = _get_os()
    paste_hotkey = ("command", "v") if os_name == "mac" else ("ctrl", "v")

    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey(*paste_hotkey)
        time.sleep(0.1)
    else:
        pyautogui.write(text, interval=0.03)


def _clear_and_paste(text: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    select_all = ("command", "a") if os_name == "mac" else ("ctrl", "a")
    pyautogui.hotkey(*select_all)
    time.sleep(0.1)
    pyautogui.press("delete")
    time.sleep(0.1)
    _paste_text(text)

def _open_app(app_name: str) -> bool:
    _require_pyautogui()
    os_name = _get_os()

    try:
        if os_name == "windows":
            pyautogui.press("win")
            time.sleep(0.5)
            _paste_text(app_name)
            time.sleep(0.6)
            pyautogui.press("enter")
            time.sleep(2.5)
            return True

        elif os_name == "mac":
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["open", "-a", f"{app_name}.app"],
                    capture_output=True, text=True, timeout=10,
                )
            time.sleep(2.5)
            return result.returncode == 0

        else: 
            launched = False
            for launcher in [
                ["gtk-launch", app_name.lower()],
                [app_name.lower()],
            ]:
                try:
                    subprocess.Popen(
                        launcher,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    launched = True
                    break
                except FileNotFoundError:
                    continue
            time.sleep(2.5)
            return launched

    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open {app_name}: {e}")
        return False


def _open_browser_url(url: str) -> bool:
    import webbrowser
    try:
        webbrowser.open(url)
        time.sleep(4.0) 
        return True
    except Exception as e:
        print(f"[SendMessage] ⚠️ Could not open browser: {e}")
        return False

def _search_in_app(query: str) -> None:
    _require_pyautogui()
    os_name = _get_os()
    search_hotkey = ("command", "f") if os_name == "mac" else ("ctrl", "f")

    pyautogui.hotkey(*search_hotkey)
    time.sleep(0.5)
    _clear_and_paste(query)
    time.sleep(1.0)

def _desktop_send(app_name: str, receiver: str, message: str) -> str:
    if not _open_app(app_name):
        return f"Could not open {app_name}."

    time.sleep(1.0)
    _search_in_app(receiver)
    pyautogui.press("enter")
    time.sleep(0.8)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)
    return f"Message sent to {receiver} via {app_name}."

def _send_whatsapp(receiver: str, message: str) -> str:
    return _desktop_send("WhatsApp", receiver, message)

def _send_telegram(receiver: str, message: str) -> str:
    return _desktop_send("Telegram", receiver, message)

def _send_signal(receiver: str, message: str) -> str:
    return _desktop_send("Signal", receiver, message)


def _send_discord(receiver: str, message: str) -> str:
    return _desktop_send("Discord", receiver, message)


def _send_instagram(receiver: str, message: str) -> str:
    _require_pyautogui()

    if not _open_browser_url("https://www.instagram.com/direct/new/"):
        return "Could not open Instagram in browser."

    _paste_text(receiver)
    time.sleep(1.5)

    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")   
    time.sleep(0.4)

    for _ in range(4):
        pyautogui.press("tab")
        time.sleep(0.15)
    pyautogui.press("enter")
    time.sleep(2.0)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)

    return f"Message sent to {receiver} via Instagram."


def _send_messenger(receiver: str, message: str) -> str:
    _require_pyautogui()

    if not _open_browser_url("https://www.messenger.com/"):
        return "Could not open Messenger in browser."


    _search_in_app(receiver)
    time.sleep(0.5)
    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(1.0)

    _paste_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)

    return f"Message sent to {receiver} via Messenger."

import difflib

_PLATFORM_MAP = [
    ({"whatsapp", "wp", "wapp"},              _send_whatsapp),
    ({"telegram", "tg"},                      _send_telegram),
    ({"instagram", "ig", "insta"},            _send_instagram),
    ({"signal"},                               _send_signal),
    ({"discord"},                              _send_discord),
    ({"messenger", "facebook", "fb"},         _send_messenger),
]


def _load_known_contacts() -> tuple[list[str], dict[str, str]]:
    """
    Load known contact names and alias-to-canonical mappings from local storage.
    Returns: (canonical_contacts_list, alias_to_canonical_map)
    """
    contact_files = [
        _base_dir() / "data" / "contacts.json",
        _base_dir() / "primary" / "data" / "contacts.json",
        _base_dir() / "config" / "contacts.json",
    ]
    canonical_contacts: list[str] = []
    alias_map: dict[str, str] = {}

    for cp in contact_files:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(v, dict):
                            canon_name = v.get("name") or k.title()
                            nickname = v.get("nickname")
                        else:
                            canon_name = str(v)
                            nickname = None

                        if canon_name and canon_name not in canonical_contacts:
                            canonical_contacts.append(canon_name)

                        # Register aliases pointing to canonical name
                        if canon_name:
                            alias_map[canon_name.lower().strip()] = canon_name
                            alias_map[k.lower().strip()] = canon_name
                            if nickname:
                                alias_map[nickname.lower().strip()] = canon_name
            except Exception:
                pass

    return canonical_contacts, alias_map


def _resolve_contact(query: str, known_contacts: list[str] | None = None) -> tuple[str, float, str]:
    """
    Fuzzy-matches a spoken/parsed contact name against known contacts and aliases.
    Returns: (resolved_name, confidence_score, status)
    status is one of:
      - 'EXACT': exact match (score 1.0)
      - 'CONFIDENT': high confidence match with clear margin over runner-up
      - 'AMBIGUOUS': multiple candidates with close scores (narrow margin)
      - 'DIRECT': unlisted contact / no contacts database found, direct pass-through
      - 'UNKNOWN': potential match with borderline confidence
    """
    if not query:
        return "", 0.0, "UNKNOWN"

    q_lower = query.lower().strip()

    if known_contacts is not None:
        contacts = known_contacts
        alias_map = {c.lower().strip(): c for c in contacts}
    else:
        contacts, alias_map = _load_known_contacts()

    if not contacts and not alias_map:
        return query.strip(), 1.0, "DIRECT"

    # 1. Exact alias/name match check
    if q_lower in alias_map:
        return alias_map[q_lower], 1.0, "EXACT"

    # 2. Score against all registered alias variations, grouped by canonical name
    scored: list[tuple[str, float]] = []
    for alias, canon in alias_map.items():
        sm_ratio = difflib.SequenceMatcher(None, q_lower, alias).ratio()
        q_tokens = set(q_lower.split())
        a_tokens = set(alias.split())
        token_ratio = len(q_tokens & a_tokens) / max(len(q_tokens | a_tokens), 1) if (q_tokens or a_tokens) else 0.0
        score = max(sm_ratio, token_ratio)
        scored.append((canon, score))

    # Deduplicate by canonical name, taking the best score among its aliases
    best_per_canon: dict[str, float] = {}
    for canon, score in scored:
        if canon not in best_per_canon or score > best_per_canon[canon]:
            best_per_canon[canon] = score

    ranked = sorted(best_per_canon.items(), key=lambda x: x[1], reverse=True)

    # If top score is low (< 0.50), the query does not match any local contact.
    # Treat it as a direct contact name to search in the target messaging app.
    if not ranked or ranked[0][1] < 0.50:
        return query.strip(), 1.0, "DIRECT"

    best_name, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    # Ambiguity check: if margin between top 2 distinct candidates is narrow (< 15%) and best_score < 0.95
    if len(ranked) > 1 and (best_score - second_score) < 0.15 and best_score < 0.95:
        return best_name, best_score, "AMBIGUOUS"

    if best_score >= 0.70:
        return best_name, best_score, "CONFIDENT"

    return best_name, best_score, "UNKNOWN"


def _resolve_platform(platform_str: str):
    key = platform_str.lower().strip()
    for keywords, handler in _PLATFORM_MAP:
        if any(k in key for k in keywords):
            return handler
    return lambda r, m: _desktop_send(platform_str.strip().title(), r, m)


def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params       = parameters or {}
    receiver_raw = params.get("receiver", "").strip()
    message_text = params.get("message_text", "").strip()
    platform     = params.get("platform", "whatsapp").strip()

    if not receiver_raw:
        return "Please specify a recipient."
    if not message_text:
        return "Please specify the message content."
    if not _PYAUTOGUI:
        return "PyAutoGUI is not installed — cannot control the desktop."

    # Resolve contact with fuzzy matching and confidence checks
    resolved_contact, score, status = _resolve_contact(receiver_raw)

    # Log ASR-transcribed name alongside resolved contact at send time
    print(f"[SendMessage] [MATCH] ASR transcribed: '{receiver_raw}' -> Resolved: '{resolved_contact}' (Score: {score:.0%}, Status: {status})")
    if player:
        player.write_log(f"[msg] ASR: '{receiver_raw}' -> '{resolved_contact}' ({score:.0%})")

    # Ambiguity guard: If ambiguous or low confidence on configured contacts, confirm before sending
    if status == "AMBIGUOUS":
        return f"Did you mean to message '{resolved_contact}'? Please confirm the contact name."
    if status == "UNKNOWN":
        return f"Could not find contact '{receiver_raw}' with high confidence. Did you mean to message '{resolved_contact}'?"

    preview = message_text[:50] + ("..." if len(message_text) > 50 else "")
    print(f"[SendMessage] [SEND] {platform} -> {resolved_contact}: {preview}")
    if player:
        player.write_log(f"[msg] {platform} -> {resolved_contact}")

    try:
        handler = _resolve_platform(platform)
        result  = handler(resolved_contact, message_text)
    except Exception as e:
        result = f"Could not send message: {e}"

    print(f"[SendMessage] [RESULT] {result}")
    if player:
        player.write_log(f"[msg] {result}")

    return result


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
class SendMessageTool(AgentTool):
    @property
    def name(self) -> str:
        return "send_message"

    @property
    def description(self) -> str:
        return "Sends a text message via WhatsApp, Telegram, or other messaging platform."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "receiver": {
                    "type": "STRING",
                    "description": "Recipient contact name"
                },
                "message_text": {
                    "type": "STRING",
                    "description": "The message to send"
                },
                "platform": {
                    "type": "STRING",
                    "description": "Platform: WhatsApp, Telegram, etc."
                }
            },
            "required": [
                "receiver",
                "message_text",
                "platform"
            ]
        }

    def execute(self, parameters: Optional[Dict[str, Any]] = None, **context) -> Any:
        return send_message(
            parameters=parameters or {},
            response=context.get("response"),
            player=context.get("player"),
            session_memory=context.get("session_memory"),
        )


ACTION = SendMessageTool()
TOOL = ACTION.to_tool_dict()
