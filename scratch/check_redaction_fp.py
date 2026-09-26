import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.logger import scrub_text, scrub_secrets

safe_samples = [
    "AGENTReminder_20260925_175222_9b39",
    "rem_20260925_175222_9b39",
    "PID 21964",
    "ref='PID 11148'",
    "pid_or_window='Target Service - Main Window'",
    r"C:\Users\santh\AppData\Local\Temp\test_downloads_zqz7ceul\Downloads\College",
    r"data/captures/capture_20260926_174000.jpg",
    "Desktop Archive 2026-09-26",
    "reminders.json",
    "https://example.com/images/nature_mountain.png",
    "Master volume is at 80%.",
    "Successfully opened Calculator (PID 21964).",
]

real_secrets = [
    "AIzaSyD-1234567890abcdefghijklmnopqrstuv",
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abcdefg12345",
    "sk-proj-abc123xyz45678901234567890",
    "4532-1234-5678-9012",
    "4532 1234 5678 9012",
    "api_key=my_super_secret_production_key_12345",
    "password='super_secure_password_99'",
]

print("--- TESTING SAFE SAMPLES ---")
fps = 0
for s in safe_samples:
    scrubbed = scrub_text(s)
    if scrubbed != s:
        print(f"FALSE POSITIVE: '{s}' -> '{scrubbed}'")
        fps += 1
    else:
        print(f"SAFE OK: '{s}'")

print(f"\nTotal False Positives: {fps}")

print("\n--- TESTING REAL SECRETS ---")
fn = 0
for s in real_secrets:
    scrubbed = scrub_text(s)
    if scrubbed == s:
        print(f"FALSE NEGATIVE (missed secret): '{s}'")
        fn += 1
    else:
        print(f"SECRET REDACTED OK: '{s}' -> '{scrubbed}'")

print(f"\nTotal False Negatives: {fn}")
