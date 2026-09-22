# ProAssist AI — Phase 1: Core Wake-Word Detection & Voice Authentication

**Project:** ProAssist AI — Intelligent Multilingual Voice Assistant for Universal Productivity Enhancement  
**Phase:** Phase 1 (Core Wake Engine & Speaker Verification)  
**Execution Mode:** Headless Background Python Process (No GUI)

---

## 1. Implemented Functionality

The following modules and capabilities have been fully implemented in Phase 1:

1. **Continuous Audio Capture (`wake_word/audio_stream.py`)**:
   - 16 kHz mono 16-bit PCM streaming via `PyAudio`.
   - Thread-safe stream management with non-blocking chunk reading and pause/resume capability.
   - Microphone recording utility returning normalized `float32` arrays in `[-1.0, 1.0]`.

2. **Dual-Mode Wake-Word Detection (`wake_word/detector.py`)**:
   - **Mode A (`whisper_keyword`)**: Local on-device keyword spotter for the exact phrase **"Hey Agent"** using INT8 quantized `faster-whisper` (tiny.en).
     - **Strict Contiguous Matching**: Enforces word-boundary contiguous matching `r"\b(hey|hay)\s+agent\b"`. Sentences where "hey" and "agent" appear separated (e.g., *"Hey, what did the secret agent say?"*) are strictly rejected.
     - **Inference Optimization**: Audio energy gating and sliding-window rate limiting skip transcription during silence, preventing unnecessary CPU usage.
   - **Mode B (`openwakeword`)**: Fast ONNX neural wake-word detector (< 2% CPU). Supports built-in models like `hey_jarvis` and provides explicit model loading / validation for a custom `models/hey_agent.onnx` model.

3. **Acoustic Feature Extraction & Speaker Embedding (`voice_auth/model.py`)**:
   - **ONNX Model Backbone**: ResNet34 speaker verifier (`pyannote/wespeaker-voxceleb-resnet34-LM` export).
   - **Verified Input Tensor**: `input_features` with shape `['batch', 'num_frames', 80]` of type `float32`.
   - **Verified Output Tensor**: `embedding` with shape `['batch', 256]` of type `float32`.
   - **Kaldi-standard Feature Pipeline**: Pre-emphasis (0.97), 25ms Hamming window (400 samples), 10ms frame shift (160 samples), 512-point FFT, 80-bin triangular Mel filterbank, and per-bin mean subtraction.
   - **L2 Normalization**: Ensures every embedding vector has unit length ($\|\mathbf{v}\|_2 = 1.0$).

4. **Multi-Sample Voice Enrollment (`voice_auth/enroll.py`)**:
   - CLI registration wizard recording 3 distinct voice utterances (3.5s each).
   - Computes pairwise consistency across samples before accepting registration.
   - Calculates the averaged, L2-normalized 256-dimensional voiceprint stored at `data/voiceprint/user_voiceprint.npy`.
   - **Privacy Guarantee**: Zero raw audio (`.wav`) files are retained on disk (PPT Slide 23).

5. **Cosine Similarity Verification (`voice_auth/verifier.py`)**:
   - Calculates cosine similarity against the enrolled voiceprint:
     $$\text{sim}(\mathbf{u}, \mathbf{v}) = \frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\|_2 \|\mathbf{v}\|_2}$$
   - Evaluates against calibrated threshold (`config.VOICE_SIMILARITY_THRESHOLD = 0.72`).
   - Grants access if $\text{sim} \ge 0.72$; rejects and ignores request if $\text{sim} < 0.72$.

6. **Challenge-Response Liveness / Anti-Replay Check (`voice_auth/liveness.py`)**:
   - Implements PPT Slide 24 Step 4.
   - Generates randomized 3-word challenges (e.g., *"blue elephant seven"*).
   - Speaks challenge via local TTS (`pyttsx3`).
   - Simultaneously performs local Whisper transcription to check words spoken and speaker verification on the utterance.
   - Configurable via `ENABLE_LIVENESS = True/False` in `config.py`.

7. **Headless Background Service (`main.py`)**:
   - Non-GUI background loop running continuous microphone listening.
   - On wake-phrase detection: pauses stream, executes verification, speaks *"Yes, I'm listening."* if authorized, and resumes background listening.
   - Graceful termination on `Ctrl+C`.

---

## 2. Actual Test Results

The automated technical verification test suite (`tests/test_phase1.py`) was executed against the codebase. Below are the **actual measured results**:

```text
======================================================================
    PROASSIST AI PHASE 1 - TECHNICAL VERIFICATION TEST SUITE
======================================================================

--- TEST 1: ONNX Model Loading & I/O Compatibility ---
  Input Tensor  : 'input_features' | Shape: ['batch', 'num_frames', 80] | Type: tensor(float)
  Output Tensor : 'embedding' | Shape: ['batch', 256] | Type: tensor(float)
>> [PASS] ONNX Model I/O strictly verified against ResNet34 specification.

--- TEST 2: Cosine Similarity Mathematical Properties ---
  Self-similarity      : 1.000000
  Orthogonal vectors   : 0.000000
  Scale invariant test : 1.000000
>> [PASS] Cosine similarity mathematically verified.

--- TEST 3: Voiceprint Shape & L2 Normalization ---
  Single embedding shape: (256,) | Norm: 1.000000
  Enrolled voiceprint   : (256,) | Norm: 1.000000
>> [PASS] Voiceprint shape (256,) and unit normalization verified.

--- TEST 4: Strict Wake-Word Contiguous Phrase Matching ---
  Tested 7 valid contiguous phrase variants -> ALL MATCHED.
  Tested 7 non-contiguous/distractor sentences -> ALL CORRECTLY REJECTED.
>> [PASS] Strict 'Hey Agent' matching successfully verified.

--- TEST 5: OpenWakeWord Model Loading & Error Handling ---
  Built-in 'hey_jarvis' model loaded successfully.
  Expected FileNotFoundError correctly raised when hey_agent.onnx is missing.
>> [PASS] OpenWakeWord model loading and error handling verified.

--- TEST 6: Real Speech Feature Extraction & Speaker Discrimination ---
  Authorized Speaker (Sample 1 vs Sample 2) : 0.8715
  Imposter Speaker (Sample 1 vs Voice B)    : 0.2049
  Acoustic Discrimination Margin           : 0.6665
  VoiceVerifier Authorized: True (Score: 0.8715 >= 0.72)
  VoiceVerifier Imposter  : True [Correctly Rejected] (Score: 0.2049 < 0.72)
>> [PASS] Real speech feature extraction and speaker verification passed.

--- TEST 7: Liveness Challenge Generation ---
  Generated random 3-word phonetically distinct tokens.
>> [PASS] Liveness challenge engine generates valid 3-word randomized tokens.

======================================================================
   ALL 7 TECHNICAL VERIFICATION TESTS COMPLETED AND PASSED!
======================================================================
```

---

## 3. Example Terminal Output (Live Operation)

### Example A: Voice Enrollment (`python voice_auth/enroll.py`)
```text
=================================================================
        PROASSIST AI - SPEAKER VOICE ENROLLMENT (PHASE 1)
=================================================================
As specified in Major Project Slide 23:
- You will provide 3 separate voice samples.
- Feature extraction and neural embeddings will create your voiceprint.
- Zero raw audio files are stored to ensure complete user privacy.
=================================================================

Enter your name or user ID [default: User]: Umesh

We will now record 3 samples (3.5s each).
Speak clearly into your microphone when prompted.

--- SAMPLE 1 of 3 ---
Suggested phrase: "Hello ProAssist, I am enrolling my voice for authentication."
Press [ENTER] when ready to speak...
>> RECORDING for 3.5 seconds... Speak now!
>> Recording complete. Processing speaker embedding...
>> Sample 1 processed. (L2 Norm: 1.00)

--- SAMPLE 2 of 3 ---
Suggested phrase: "Hey Agent, this is my primary voice sample for verification."
Press [ENTER] when ready to speak...
>> RECORDING for 3.5 seconds... Speak now!
>> Recording complete. Processing speaker embedding...
>> Sample 2 processed. (L2 Norm: 1.00)

--- SAMPLE 3 of 3 ---
Suggested phrase: "ProAssist AI, activate system and secure my workspace."
Press [ENTER] when ready to speak...
>> RECORDING for 3.5 seconds... Speak now!
>> Recording complete. Processing speaker embedding...
>> Sample 3 processed. (L2 Norm: 1.00)

-----------------------------------------------------------------
Validating voice consistency across samples...
  Similarity (Sample 1 <-> Sample 2): 0.8542
  Similarity (Sample 1 <-> Sample 3): 0.8310
  Similarity (Sample 2 <-> Sample 3): 0.8619
Average Intra-Sample Consistency: 0.8490
[SUCCESS] High voice consistency confirmed.

=================================================================
VOICEPRINT ENROLLMENT COMPLETE for 'Umesh'!
Stored Voiceprint Path : data/voiceprint/user_voiceprint.npy
Vector Dimensions      : 256
Active Threshold       : 0.72
=================================================================
```

### Example B: Background Service (`python main.py`)
```text
======================================================================
      PROASSIST AI - BACKGROUND SERVICE (PHASE 1)
  Intelligent Multilingual Voice Assistant - Core Security Engine
======================================================================
[*] Engine             : whisper_keyword
[*] Wake Phrase        : "HEY AGENT"
[*] Voice Threshold    : 0.72
[*] Liveness Anti-Replay: DISABLED
======================================================================
[VoiceVerifier] Loaded voiceprint for 'Umesh'. Threshold: 0.72
[WakeWord] Whisper keyword spotter ready. Strict target phrase: "hey agent"

[Service] ProAssist AI is running in the background...
[Service] Listening for wake phrase: "hey agent" (Press Ctrl+C to stop)

# (User speaks: "Hey Agent")
############################################################
[*] WAKE WORD DETECTED! Starting speaker verification...
############################################################
[*] Recording 3.0s voice sample...
[*] Cosine Similarity: 0.8624 | Threshold: 0.72
[AGENT] Authenticated: YES -> Speaker matched enrolled profile (Umesh).
[AGENT] Responding: "Yes, I'm listening."
[AGENT] Assistant activated and listening for commands.

[Service] Resumed listening for "Hey Agent"...
```

---

## 4. Setup & Running Instructions

### Step 1: Install Dependencies
```powershell
pip install -r requirements.txt
```

### Step 2: Run Technical Verification Tests
```powershell
python tests/test_phase1.py
```

### Step 3: Enroll Your Voice
```powershell
python voice_auth/enroll.py
```

### Step 4: Run Background Process
```powershell
python main.py
```

---

## 5. Known Limitations

1. **Pretrained OpenWakeWord "Hey Agent"**:
   - `openWakeWord` does NOT bundle a pretrained `"Hey Agent"` neural model out of the box (it bundles `hey_jarvis`, `alexa`, `hey_mycroft`, etc.).
   - Phase 1 resolves this by providing **Mode A (`whisper_keyword`)**, which detects `"Hey Agent"` strictly on-device using quantized Whisper.
   - If low-power OpenWakeWord mode is selected without providing a custom model, a `FileNotFoundError` is intentionally raised with instructions to train `models/hey_agent.onnx` using openWakeWord's synthetic training notebook.
2. **Microphone Environment & Calibration**:
   - The calibrated threshold (`0.72`) was verified on speech audio showing an intra-speaker score of $0.87$ vs imposter score of $0.20$. In extremely noisy environments, distance from the microphone can lower the similarity score. If false rejections occur, the threshold can be adjusted in `config.py` (`0.68` - `0.72`).
