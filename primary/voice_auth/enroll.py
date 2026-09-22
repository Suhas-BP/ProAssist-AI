"""
Voice Enrollment Module for ProAssist AI
Guides the user through multi-sample voice registration (PPT Slide 23).
Processes recordings into 256-dimensional speaker embeddings, averages them,
and saves a single normalized voiceprint locally. Never stores raw audio.
Includes diagnostic logging for audio RMS, peak, features, and pairwise similarities.
"""


"""
Voice Enrollment Module for ProAssist AI
...
"""

import sys
from pathlib import Path
import time
import json
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import config
from wake_word.audio_stream import record_audio
from voice_auth.model import SpeakerEmbeddingModel, compute_cosine_similarity


def run_enrollment():
    print("=" * 70)
    print("        PROASSIST AI - SPEAKER VOICE ENROLLMENT (PHASE 1)")
    print("=" * 70)
    print("As specified in Major Project Slide 23:")
    print("- You will provide 3 separate voice samples.")
    print("- Feature extraction and neural embeddings will create your voiceprint.")
    print("- Zero raw audio files are stored to ensure complete user privacy.")
    print("=" * 70)

    model = SpeakerEmbeddingModel()
    user_name = input("\nEnter your name or user ID [default: User]: ").strip() or "User"
    sample_count = config.ENROLLMENT_SAMPLES_COUNT
    sample_duration = config.ENROLLMENT_SAMPLE_DURATION

    prompts = [
        "Hello ProAssist, I am enrolling my voice for authentication.",
        "Hey Agent, this is my primary voice sample for verification.",
        "ProAssist AI, activate system and secure my workspace."
    ]

    embeddings = []
    diagnostics = []

    print(f"\nWe will now record {sample_count} samples ({sample_duration}s each).")
    print("Speak clearly into your microphone when prompted.\n")

    i = 0
    while i < sample_count:
        prompt_text = prompts[i % len(prompts)]
        print(f"\n" + "-" * 60)
        print(f"--- SAMPLE {i + 1} of {sample_count} ---")
        print(f"Target Phrase: \"{prompt_text}\"")
        input("Press [ENTER] when ready to speak...")

        print(f">> RECORDING for {sample_duration} seconds... Speak now!")
        try:
            audio_data = record_audio(duration_seconds=sample_duration)
            print(">> Recording complete. Processing acoustic features & embedding...")
        except Exception as e:
            print(f"[ERROR] Microphone capture failed: {e}")
            return False

        # Generate embedding with detailed diagnostic stats
        emb, diag = model.generate_embedding(audio_data, apply_vad=True)

        if diag['raw_peak'] < 0.02 or diag['raw_rms'] < 0.001:
            print(f"  [!] Audio level too quiet or silent (Peak: {diag['raw_peak']:.4f}, RMS: {diag['raw_rms']:.5f}).")
            print("  [!] Please speak louder or closer to the microphone. Retrying this sample...")
            continue

        embeddings.append(emb)
        diagnostics.append(diag)

        # DIAGNOSTIC LOGGING (as requested)
        print(f"\n  [DIAGNOSTICS - SAMPLE {i + 1}]")
        print(f"  * Audio Duration       : {diag['raw_duration']:.2f}s (Active Speech: {diag['proc_duration']:.2f}s)")
        print(f"  * Recorded Audio RMS   : {diag['raw_rms']:.5f} (Active Speech RMS: {diag['proc_rms']:.5f})")
        print(f"  * Peak Amplitude       : {diag['raw_peak']:.5f} (Normalized Peak: {diag['proc_peak']:.5f})")
        print(f"  * Feature Tensor Shape : {diag['feature_shape']} (Frames: {diag['num_frames']}, Mel Bins: 80)")
        print(f"  * Feature Mean / Std   : Mean = {diag['feature_mean']:.6f}, Std = {diag['feature_std']:.6f}")
        print(f"  * Raw Embedding Norm   : {diag['raw_embedding_norm']:.4f}")
        print(f"  * Unit-Norm Embedding  : {diag['final_embedding_norm']:.6f} (Dim: {diag['embedding_dim']})")

        if diag['raw_peak'] < 0.05:
            print("  [TIP] Microphone input level is low. Speaking closer to the mic may improve SNR.")

        i += 1
        time.sleep(0.5)

    # Calculate and display pairwise cosine similarities
    print("\n" + "=" * 70)
    print("PAIRWISE INTRA-SPEAKER COSINE SIMILARITIES:")
    print("=" * 70)
    pair_sims = []
    pairs = [
        (0, 1, "Sample 1 <-> Sample 2"),
        (0, 2, "Sample 1 <-> Sample 3"),
        (1, 2, "Sample 2 <-> Sample 3")
    ]
    for idx1, idx2, label in pairs:
        sim = compute_cosine_similarity(embeddings[idx1], embeddings[idx2])
        pair_sims.append(sim)
        print(f"  * {label:25s} : {sim:.4f}")

    avg_consistency = float(np.mean(pair_sims)) if pair_sims else 1.0
    print(f"\n  * Average Intra-Speaker Similarity  : {avg_consistency:.4f}")
    print(f"  * Configured Security Threshold     : {config.VOICE_SIMILARITY_THRESHOLD:.2f}")

    if avg_consistency >= config.VOICE_SIMILARITY_THRESHOLD:
        print("\n>> [STATUS: PASS] High consistency confirmed across all 3 voice samples!")
    elif avg_consistency >= 0.65:
        print("\n>> [STATUS: ACCEPTABLE] Voice consistency is sufficient, but could be improved.")
    else:
        print("\n>> [STATUS: WARNING] Voice consistency is lower than expected.")
        print("   Consider re-running enrollment in a quieter room speaking at a consistent volume.")

    # Compute averaged and L2-normalized voiceprint
    stacked = np.array(embeddings)
    mean_embedding = np.mean(stacked, axis=0)
    norm = np.linalg.norm(mean_embedding)
    final_voiceprint = (mean_embedding / norm).astype(np.float32)

    # Save voiceprint vector to local disk
    config.VOICEPRINT_DIR.mkdir(parents=True, exist_ok=True)
    np.save(config.VOICEPRINT_PATH, final_voiceprint)

    # Save enrollment metadata
    meta = {
        "user_name": user_name,
        "enrolled_at": datetime.now().isoformat(),
        "sample_count": sample_count,
        "sample_duration_seconds": sample_duration,
        "embedding_dimensions": len(final_voiceprint),
        "intra_sample_consistency": round(avg_consistency, 4),
        "threshold": config.VOICE_SIMILARITY_THRESHOLD,
        "diagnostics": {
            f"sample_{i+1}": {
                "raw_rms": diag["raw_rms"],
                "raw_peak": diag["raw_peak"],
                "active_duration": diag["proc_duration"],
                "feature_std": diag["feature_std"]
            }
            for i, diag in enumerate(diagnostics)
        }
    }
    with open(config.VOICEPRINT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("\n" + "=" * 70)
    print(f"VOICEPRINT ENROLLMENT COMPLETE for '{user_name}'!")
    print(f"Stored Voiceprint Path : {config.VOICEPRINT_PATH}")
    print(f"Vector Dimensions      : {final_voiceprint.shape[0]}")
    print(f"Final Voiceprint Norm  : {np.linalg.norm(final_voiceprint):.6f}")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_enrollment()
    sys.exit(0 if success else 1)
