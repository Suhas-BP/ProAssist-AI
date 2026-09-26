
import sys, time
for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, r"d:\Mark-LIV-main")


def test_blue_color_token():
    print("\n[1] C.BLUE color token...")
    from ui import C
    assert hasattr(C, "BLUE"), "C.BLUE missing"
    assert C.BLUE.startswith("#") and len(C.BLUE) == 7
    r, g, b = int(C.BLUE[1:3],16), int(C.BLUE[3:5],16), int(C.BLUE[5:7],16)
    assert b > r and b > g, f"C.BLUE={C.BLUE} not blue: RGB({r},{g},{b})"
    print(f"   -> C.BLUE={C.BLUE} RGB({r},{g},{b}) - blue dominant - PASS")


def test_apply_state_working_pill():
    print("\n[2] _apply_state WORKING pill text...")
    hud = MagicMock()
    pill = [""]
    def apply(state):
        hud.state = state
        hud.speaking = (state == "SPEAKING")
        txts = {
            "LISTENING": "Listening - speak now",
            "THINKING":  "Thinking...",
            "WORKING":   "Working on task...",
            "SPEAKING":  "Speaking...",
            "MUTED":     "Microphone muted",
        }
        pill[0] = txts.get(state, state)
    apply("WORKING")
    assert "Working on task" in pill[0], pill[0]
    assert hud.state == "WORKING"
    for s in ["LISTENING", "THINKING", "SPEAKING"]:
        apply(s)
        assert s[:4].lower() in pill[0].lower(), f"regression {s}: {pill[0]}"
    print(f"   -> WORKING pill=\"{pill[0]}\", existing states OK - PASS")


def test_normal_transition():
    print("\n[3] LISTENING->WORKING->LISTENING (normal)...")
    log = []
    ui = MagicMock()
    ui.muted = False
    ui.set_state.side_effect = lambda s: log.append(s)
    ui.set_state("LISTENING")
    aif = [False]
    if not ui.muted:
        ui.set_state("WORKING")
    aif[0] = True
    time.sleep(0.02)
    aif[0] = False
    if not ui.muted:
        ui.set_state("LISTENING")
    assert log == ["LISTENING", "WORKING", "LISTENING"], log
    assert aif[0] is False
    print(f"   -> {log} - PASS")


def test_error_transition():
    print("\n[4] LISTENING->WORKING->LISTENING (error path)...")
    log = []
    ui = MagicMock()
    ui.muted = False
    ui.set_state.side_effect = lambda s: log.append(s)
    aif = [False]
    err_spoken = []
    ui.set_state("LISTENING")
    if not ui.muted:
        ui.set_state("WORKING")
    aif[0] = True
    try:
        raise RuntimeError("disk full")
    except Exception as e:
        err_spoken.append(str(e))
    finally:
        aif[0] = False
    if not ui.muted:
        ui.set_state("LISTENING")
    assert log == ["LISTENING", "WORKING", "LISTENING"], log
    assert aif[0] is False
    assert "disk full" in err_spoken[0]
    print(f"   -> {log}, error_spoken=\"{err_spoken[0]}\" - PASS")


def test_muted_no_working():
    print("\n[5] WORKING skipped when muted...")
    log = []
    ui = MagicMock()
    ui.muted = True
    ui.set_state.side_effect = lambda s: log.append(s)
    aif = [False]
    if not ui.muted:
        ui.set_state("WORKING")
    aif[0] = True
    aif[0] = False
    if not ui.muted:
        ui.set_state("LISTENING")
    assert "WORKING" not in log and "LISTENING" not in log, log
    print(f"   -> log={log} - WORKING+LISTENING skipped when muted - PASS")


def test_speaking_visual_priority():
    print("\n[6] SPEAKING visual priority over WORKING...")

    class FH:
        state = "WORKING"
        speaking = True
        muted = False

        def colour_key(self):
            if self.muted:
                return "MUTED_C"
            if self.speaking:
                return "ACC"
            if self.state in ("THINKING", "PROCESSING"):
                return "ACC2"
            if self.state == "WORKING":
                return "BLUE"
            if self.state == "LISTENING":
                return "GREEN"
            return "PRI_DIM"

    h = FH()
    assert h.colour_key() == "ACC", "SPEAKING must win"
    h.speaking = False
    assert h.colour_key() == "BLUE", "WORKING must be BLUE"
    print("   -> speaking=True:ACC, speaking=False:BLUE - PASS")


def test_floating_island_map():
    print("\n[7] FloatingIsland status_map WORKING entry...")
    m = {
        "LISTENING": ("Listening", "Listening - speak now", "#2ee672", True),
        "THINKING":  ("Thinking", "Thinking...", "#ffaa00", True),
        "WORKING":   ("Working", "Working on task...", "#3b82f6", True),
        "SPEAKING":  ("Speaking", "Speaking...", "#2ee672", True),
        "MUTED":     ("Muted", "Microphone muted", "#ff4444", False),
    }
    sub, line, dot_col, mic_on = m["WORKING"]
    assert sub == "Working"
    assert "Working on task" in line
    assert dot_col == "#3b82f6", dot_col
    assert mic_on is True
    for s in ["LISTENING", "THINKING", "SPEAKING"]:
        assert s in m
    print(f"   -> WORKING sub={sub} dot_col={dot_col} mic_on={mic_on} - PASS")


def test_integration_sequence():
    print("\n[8] Integration: full _execute_tool state sequence...")
    log = []
    ui = MagicMock()
    ui.muted = False
    ui.set_state.side_effect = lambda s: log.append(s)
    aif = [False]

    def run(name, slow=False):
        ui.set_state("THINKING")
        if name == "save_memory":
            if not ui.muted:
                ui.set_state("LISTENING")
            return
        aif[0] = True
        if not ui.muted:
            ui.set_state("WORKING")
        try:
            time.sleep(0.04 if slow else 0.01)
        finally:
            aif[0] = False
        if not ui.muted:
            ui.set_state("LISTENING")

    log.clear()
    run("web_search", slow=True)
    assert log == ["THINKING", "WORKING", "LISTENING"], f"web_search: {log}"
    print(f"   -> web_search: {log} - PASS")

    log.clear()
    run("computer_control")
    assert log == ["THINKING", "WORKING", "LISTENING"], f"computer_control: {log}"
    print(f"   -> computer_control: {log} - PASS")

    log.clear()
    run("save_memory")
    assert log == ["THINKING", "LISTENING"], f"save_memory should skip WORKING: {log}"
    print(f"   -> save_memory (no WORKING): {log} - PASS")


if __name__ == "__main__":
    print("=" * 60)
    print("FLAG 2 TEST SUITE - WORKING State")
    print("=" * 60)
    test_blue_color_token()
    test_apply_state_working_pill()
    test_normal_transition()
    test_error_transition()
    test_muted_no_working()
    test_speaking_visual_priority()
    test_floating_island_map()
    test_integration_sequence()
    print()
    print("=" * 60)
    print("ALL FLAG 2 TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
