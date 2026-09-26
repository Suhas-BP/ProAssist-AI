import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
from typing import Any, Optional
import sys

try:
    from core.logger import scrub_secrets, scrub_text, _SENSITIVE_KEY_RE
except ImportError:
    base = Path(__file__).resolve().parent.parent
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    from core.logger import scrub_secrets, scrub_text, _SENSITIVE_KEY_RE


for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 380

# ── Why there are two very different numbers here ────────────────────────────
#
# There used to be one: MEMORY_MAX_CHARS = 2200, applied to the whole store. It
# was a *storage* limit, and it existed only because the entire memory was
# pasted into the system prompt on every connect — so growing the memory grew
# every single request. When it filled, _trim_to_limit() deleted the oldest
# entries and printed one line to a console nobody reads. A memory described as
# "deeply remembers projects, preferences and personal context" was in practice
# two pages long, and quietly forgot your sister's name after a few weeks.
#
# Storage and prompt budget are now separate concerns:
#
#   MEMORY_MAX_CHARS  — a runaway guard, not a feature limit. Nothing normal
#                       reaches it; a bug writing in a loop does.
#   PROMPT_CORE_CHARS — what actually rides in the system prompt every session.
#                       Smaller than the old whole-memory dump, so sessions
#                       start *faster* than before, not slower.
#
# Everything above the core stays on disk and is fetched on demand by the
# recall_memory tool — see search_memory() and format_memory_for_prompt().
MEMORY_MAX_CHARS  = 200_000
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
# Most entries any one category may contribute to the core block, so a person
# with forty stored preferences still gets their sister into the prompt.
PROMPT_MAX_PER_CATEGORY = 6

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }

_last_migration_log: list[dict] = []


def get_last_migration_log() -> list[dict]:
    """Return the redaction log from the most recent migration."""
    global _last_migration_log
    return list(_last_migration_log)


def scrub_memory_store_with_audit(memory: dict) -> tuple[dict, list[dict]]:
    """Scrub sensitive keys and secret values throughout the memory store,
    returning (sanitized_memory, redaction_log)."""
    import copy
    if not isinstance(memory, dict):
        return memory, []

    clean_mem = copy.deepcopy(memory)
    redaction_log: list[dict] = []

    # Check sessions
    if "sessions" in clean_mem and isinstance(clean_mem["sessions"], list):
        for idx, session in enumerate(clean_mem["sessions"]):
            if isinstance(session, dict) and "summary" in session:
                raw_sum = str(session["summary"])
                scrubbed = scrub_text(raw_sum)
                if scrubbed != raw_sum:
                    session["summary"] = scrubbed
                    redaction_log.append({
                        "location": f"sessions[{idx}].summary",
                        "reason": "Scrubbed secret pattern in session summary",
                        "original_snippet": raw_sum[:30] + "...",
                        "redacted_snippet": scrubbed[:30] + "...",
                    })

    # Check categories
    for cat, items in clean_mem.items():
        if cat == "sessions" or not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if _SENSITIVE_KEY_RE.search(str(key)):
                if isinstance(entry, dict) and "value" in entry:
                    if entry["value"] != "[REDACTED_SECRET]":
                        entry["value"] = "[REDACTED_SECRET]"
                        redaction_log.append({
                            "location": f"{cat}/{key}",
                            "reason": f"Sensitive key name matched {_SENSITIVE_KEY_RE.pattern}",
                            "redacted_to": "[REDACTED_SECRET]",
                        })
                elif isinstance(entry, str):
                    if entry != "[REDACTED_SECRET]":
                        items[key] = "[REDACTED_SECRET]"
                        redaction_log.append({
                            "location": f"{cat}/{key}",
                            "reason": f"Sensitive key name matched {_SENSITIVE_KEY_RE.pattern}",
                            "redacted_to": "[REDACTED_SECRET]",
                        })
            else:
                if isinstance(entry, dict) and "value" in entry:
                    val = entry["value"]
                    if isinstance(val, dict):
                        scrubbed_val = scrub_secrets(copy.deepcopy(val))
                        if scrubbed_val != val:
                            entry["value"] = scrubbed_val
                            redaction_log.append({
                                "location": f"{cat}/{key}.value",
                                "reason": "Scrubbed secrets within nested dictionary value",
                                "redacted_to": "[REDACTED_SECRET]",
                            })
                    else:
                        val_str = str(val)
                        scrubbed_val = scrub_text(val_str)
                        if scrubbed_val != val_str:
                            entry["value"] = scrubbed_val
                            redaction_log.append({
                                "location": f"{cat}/{key}.value",
                                "reason": "Scrubbed secret pattern in value",
                                "redacted_to": scrubbed_val,
                            })
                elif isinstance(entry, str):
                    scrubbed = scrub_text(entry)
                    if scrubbed != entry:
                        items[key] = scrubbed
                        redaction_log.append({
                            "location": f"{cat}/{key}",
                            "reason": "Scrubbed secret pattern in string entry",
                            "redacted_to": scrubbed,
                        })

    clean_mem = scrub_secrets(clean_mem)
    return clean_mem, redaction_log


def scrub_memory_store(memory: dict) -> dict:
    """Scrub sensitive keys and secret values throughout the memory store."""
    sanitized, _ = scrub_memory_store_with_audit(memory)
    return sanitized


def load_memory() -> dict:
    global _last_migration_log
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            raw_text = MEMORY_PATH.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                sanitized, redaction_log = scrub_memory_store_with_audit(data)
                if redaction_log:
                    _last_migration_log = redaction_log
                    # (a) Proof a backup file was created matching pre-migration content exactly
                    backup_path = MEMORY_PATH.with_suffix(".json.bak")
                    backup_path.write_text(raw_text, encoding="utf-8")

                    # (b) Migration/redaction log file showing what was changed and why
                    log_file = MEMORY_PATH.parent / "migration_redaction.log"
                    ts = datetime.now().isoformat()
                    log_lines = [
                        json.dumps({"timestamp": ts, **entry}, ensure_ascii=False)
                        for entry in redaction_log
                    ]
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write("\n".join(log_lines) + "\n")
                    print(f"[Memory] 🛡️ Migration: Redacted {len(redaction_log)} secrets. Backup: {backup_path.name}")

                    # (c) Save back to disk so second load_memory does NOT re-trigger migration
                    MEMORY_PATH.write_text(
                        json.dumps(sanitized, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                return sanitized
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()


def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


# Set by main.py so a trim can reach the activity log. Deleting something a
# person told you and mentioning it only on stdout is how a memory loses trust.
_trim_notifier = None


def set_trim_notifier(fn) -> None:
    """Register a callable(str) that surfaces trims to the user."""
    global _trim_notifier
    _trim_notifier = fn


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    dropped = []
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        dropped.append(f"{cat}/{key}")
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    if dropped and _trim_notifier:
        try:
            _trim_notifier(
                f"SYS: Memory full — forgot {len(dropped)} oldest entries "
                f"({', '.join(dropped[:3])}{'…' if len(dropped) > 3 else ''})"
            )
        except Exception:
            pass
    return memory


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = scrub_memory_store(memory)
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            raw_val = value["value"] if isinstance(value, dict) else value
            if isinstance(raw_val, dict):
                clean_val = scrub_secrets(dict(raw_val))
                new_val   = clean_val
            else:
                raw_str   = str(raw_val)
                if _SENSITIVE_KEY_RE.search(str(key)):
                    clean_val = "[REDACTED_SECRET]"
                else:
                    clean_val = scrub_text(raw_str)
                new_val   = _truncate_value(clean_val)
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed



def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory

def _entry_value(entry) -> Any:
    """Accept both the {'value': ..., 'updated': ...} shape and a bare string,
    because early versions of the store wrote plain strings."""
    if isinstance(entry, dict):
        val = entry.get("value", "")
        if isinstance(val, dict):
            return val
        return str(val or "").strip()
    return str(entry or "").strip()


def _pretty(key: str) -> str:
    return key.replace("_", " ").strip()


# Identity is always in the prompt; these categories compete for the remaining
# budget by recency.
_CATEGORY_LABELS = {
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
}

_IDENTITY_FIELDS = ["name", "age", "birthday", "city", "job",
                    "language", "school", "nationality"]


def format_memory_for_prompt(memory: dict | None) -> str:
    """Build the memory block that goes into the system prompt.

    This used to dump everything. It now sends three things:

      1. IDENTITY  - always, in full. It is small, and it is wrong for the
         assistant to have to look up your name.
      2. RECENT    - the most recently updated entries from every other
         category, up to PROMPT_CORE_CHARS. Recency is the cheapest useful
         relevance signal available without embeddings.
      3. AN INDEX  - the *keys* of everything else, values omitted.

    Point 3 is what makes recall work at all. A model cannot decide to look
    something up if it does not know the thing exists: with only points 1 and 2,
    "who is Ayse?" would get "I don't know" while ayse_sister sat on disk
    unread. The index costs a few hundred characters and turns recall from a
    gamble into a lookup.

    Net effect on latency: this block is SMALLER than the old full dump, so
    every session connects with fewer tokens. Occasionally the model spends one
    extra round trip on recall_memory - covered by the acknowledgment it
    already speaks before any slow step."""
    if not memory:
        return ""

    core_lines: list[str] = []

    # 1. Identity - always, in full
    identity = memory.get("identity", {}) or {}
    for field in _IDENTITY_FIELDS:
        val = _entry_value(identity.get(field))
        if not val:
            continue
        if field == "language":
            # Labelled as an observation, not a setting. A bare "Language:
            # English" line written months ago reads like a standing order and
            # was one of the reasons a Turkish question came back in English.
            core_lines.append(
                f"Has spoken to you in: {val} (an observation about the past — "
                f"always answer in the language of their CURRENT message)")
        else:
            core_lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in _IDENTITY_FIELDS:
            continue
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}")

    # 2. Everything else, most recently updated first
    rest: list[tuple[str, str, str, str]] = []   # (updated, cat, key, value)
    for cat in _CATEGORY_LABELS:
        for key, entry in (memory.get(cat, {}) or {}).items():
            val = _entry_value(entry)
            if not val:
                continue
            updated = (entry.get("updated", "") if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}

    # Recency decides order, but no single category may take the whole budget.
    # Without the cap, someone with forty stored preferences gets a prompt that
    # is forty preferences and not one person's name — the categories that
    # matter most in conversation are also the ones that change least often, so
    # pure recency systematically buries them.
    per_cat_used: dict[str, int] = {}
    for _updated, cat, key, val in rest:
        if isinstance(val, dict):
            val_display = ", ".join(f"{k}={v}" for k, v in val.items())
        else:
            val_display = str(val)
        line = f"  - {_pretty(key).title()}: {val_display}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY
                and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(_pretty(key))

    # The index is a table of contents, so it is interleaved across categories
    # rather than continuing in recency order. Sorted by recency it would list
    # twenty-four preferences before the first relationship, and the one entry
    # the index exists for — the old fact the model has no other way to know
    # about — would fall off the end.
    indexed: list[str] = []
    if overflow:
        cats  = [c for c in _CATEGORY_LABELS if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    for cat, label in _CATEGORY_LABELS.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    if not core_lines and not indexed:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]",
        *core_lines,
    ]

    # 3. The index of what is on disk but not in this prompt
    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append(
                "[ALSO REMEMBERED — values not shown here. Call recall_memory "
                "with a keyword to read any of these before saying you do not know]"
            )
            out.append(", ".join(names)
                       + (f" (+{len(indexed) - len(names)} more)"
                          if len(indexed) > len(names) else ""))

    return "\n".join(out) + "\n"


# ── Recall ────────────────────────────────────────────────────────────────────

def _score(query_words: list[str], cat: str, key: str, value: str) -> int:
    """Cheap lexical relevance. No embeddings, no network, no model call - this
    runs in well under a millisecond, which is the entire point: recall must
    cost one model round trip, never two."""
    hay_key = _pretty(key).lower()
    hay_val = value.lower()
    score   = 0
    for w in query_words:
        if not w:
            continue
        if w == hay_key:
            score += 10
        elif w in hay_key:
            score += 6
        if w in hay_val:
            score += 3
        if w in cat:
            score += 1
    return score


def search_memory(query: str, limit: int = 8) -> str:
    """Find stored facts matching `query`. Backs the recall_memory tool.

    An empty query is treated as "show me everything you know", capped - the
    model asks that when the user says "what do you remember about me?"."""
    memory = load_memory()
    words  = [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) > 1]

    rows: list[tuple[int, str, str, str]] = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue                     # skip 'sessions', which is a list
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            s = _score(words, cat, key, val) if words else 1
            if s > 0:
                rows.append((s, cat, key, val))

    if not rows:
        return (f"Nothing stored about '{query}'." if query
                else "I have not stored anything about this person yet.")

    rows.sort(key=lambda r: (-r[0], r[2]))
    lines = [f"{cat}/{_pretty(key)}: {val}" for _s, cat, key, val in rows[:max(1, limit)]]
    head  = (f"Stored facts matching '{query}':" if query
             else "Everything currently stored:")
    more  = (f"\n(+{len(rows) - len(lines)} more — search with a narrower keyword)"
             if len(rows) > len(lines) else "")
    return head + "\n" + "\n".join(lines) + more


def all_entries_for_ui() -> list[dict]:
    """Flat list for the memory panel: what AGENT knows, and when it learned it.
    Sorted newest first so the panel opens on what changed most recently."""
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            rows.append({
                "category": cat,
                "key":      key,
                "value":    ", ".join(f"{k}={v}" for k, v in val.items()) if isinstance(val, dict) else str(val),
                "updated":  (entry.get("updated", "") if isinstance(entry, dict) else ""),
            })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows

def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

_SESSION_MAX = 3   # safety cap — in practice 0-1 entries after pop


def save_session_summary(summary: str, language: str = "") -> None:
    """Append a 1-2 sentence session summary to long_term.json['sessions']."""
    summary = scrub_text((summary or "").strip())
    if not summary:
        return
    memory   = load_memory()
    sessions = memory.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    entry: dict = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "summary": summary[:280],
    }
    if language:
        entry["language"] = language
    sessions.append(entry)
    memory["sessions"] = sessions[-_SESSION_MAX:]
    save_memory(memory)
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    """
    Return AND remove the most recent session entry.
    Calling this consumes the entry so it is never repeated in future briefings.
    """
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory   = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            entry = sessions.pop()          # remove the last entry
            memory["sessions"] = sessions
            MEMORY_PATH.write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return entry
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            return None


# ── Extended Preference Tracking (Item 2) ─────────────────────────────────────

def get_preferred_download_dir() -> Path:
    """Return the user's preferred download directory from memory,
    falling back to ~/Downloads if none is configured or directory is invalid."""
    memory = load_memory()
    stored = memory.get("preferences", {}).get("preferred_download_dir")
    val = _entry_value(stored)
    if val:
        try:
            p = Path(val).expanduser().resolve()
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass
    default_dir = Path.home() / "Downloads"
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


def set_preferred_download_dir(path: Path | str) -> str:
    """Persist the user's preferred download directory in memory."""
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    update_memory({"preferences": {"preferred_download_dir": {"value": str(p)}}})
    return str(p)


def record_app_launch(app_name: str) -> None:
    """Increment launch frequency for an application in memory (capped to top 15 apps)."""
    app_name = (app_name or "").strip()
    if not app_name:
        return
    memory = load_memory()
    stored = memory.get("preferences", {}).get("app_usage_frequency")
    val = _entry_value(stored)
    counts: dict[str, int] = {}
    if val:
        try:
            counts = json.loads(val)
            if not isinstance(counts, dict):
                counts = {}
        except Exception:
            for part in val.split(","):
                if ":" in part:
                    k, v = part.split(":", 1)
                    try:
                        counts[k.strip().lower()] = int(v.strip())
                    except ValueError:
                        pass

    key = app_name.lower()
    counts[key] = counts.get(key, 0) + 1
    # Keep top 15 most frequent
    top_counts = dict(sorted(counts.items(), key=lambda item: item[1], reverse=True)[:15])
    update_memory({"preferences": {"app_usage_frequency": {"value": json.dumps(top_counts)}}})


def get_frequently_used_apps(limit: int = 5) -> list[str]:
    """Return the top most frequently launched applications from memory."""
    memory = load_memory()
    stored = memory.get("preferences", {}).get("app_usage_frequency")
    val = _entry_value(stored)
    if not val:
        return []
    try:
        counts = json.loads(val)
        if isinstance(counts, dict):
            sorted_apps = sorted(counts.items(), key=lambda item: item[1], reverse=True)
            return [app for app, _ in sorted_apps[:limit]]
    except Exception:
        pass
    return []


def get_automation_preference(key: str, default: Any = None) -> Any:
    """Retrieve an automation preference value from memory."""
    memory = load_memory()
    stored = memory.get("preferences", {}).get("automation_preferences")
    val = _entry_value(stored)
    if val is None:
        return default
    if isinstance(val, dict):
        return val.get(key, default)
    if isinstance(val, str) and val:
        try:
            prefs = json.loads(val)
            if isinstance(prefs, dict):
                return prefs.get(key, default)
        except Exception:
            pass
    return default


def set_automation_preference(key: str, value: Any) -> None:
    """Persist an automation preference option in memory as structured nested JSON."""
    memory = load_memory()
    stored = memory.get("preferences", {}).get("automation_preferences")
    val = _entry_value(stored)
    prefs: dict[str, Any] = {}
    if isinstance(val, dict):
        prefs = dict(val)
    elif isinstance(val, str) and val:
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                prefs = parsed
        except Exception:
            pass
    prefs[key] = value
    update_memory({"preferences": {"automation_preferences": {"value": prefs}}})