"""
Speaker Embedding Model (ONNX Neural Speaker Verifier)
Implements exact Kaldi-compatible 80-channel log-mel filterbank feature extraction,
adaptive silence trimming (VAD), and peak dynamic-range normalization.
Executes the ResNet34 ONNX backbone (pyannote/wespeaker-voxceleb-resnet34-LM)
to produce 256-dimensional L2-normalized speaker embeddings.
"""

from pathlib import Path
import numpy as np
import onnxruntime as ort
import config


def trim_silence_vad(audio: np.ndarray, sample_rate: int = 16000,
                     frame_ms: float = 20.0,
                     min_energy_threshold: float = 0.004) -> tuple[np.ndarray, dict]:
    """
    Trims leading and trailing silence/room noise from a speech recording.
    Removes dead silence frames that would otherwise distort per-bin mean subtraction
    and global average pooling in the ResNet backbone.
    """
    frame_len = int(sample_rate * frame_ms / 1000.0)
    num_frames = len(audio) // frame_len
    if num_frames == 0:
        return audio, {"trimmed": False, "active_ratio": 1.0}

    energies = np.array([
        np.sqrt(np.mean(audio[i * frame_len:(i + 1) * frame_len] ** 2))
        for i in range(num_frames)
    ], dtype=np.float32)

    noise_floor = float(np.percentile(energies, 20))
    peak_energy = float(np.max(energies))

    # Adaptive speech threshold
    if peak_energy > noise_floor:
        threshold = max(min_energy_threshold, noise_floor + 0.10 * (peak_energy - noise_floor))
    else:
        threshold = min_energy_threshold

    active_indices = np.where(energies > threshold)[0]
    if len(active_indices) == 0:
        return audio, {"trimmed": False, "active_ratio": 1.0, "threshold": threshold}

    # Safety margin around speech (150ms before and after)
    margin_frames = int(150.0 / frame_ms)
    start_frame = max(0, active_indices[0] - margin_frames)
    end_frame = min(num_frames, active_indices[-1] + margin_frames + 1)

    trimmed = audio[start_frame * frame_len:end_frame * frame_len]
    active_ratio = len(trimmed) / max(len(audio), 1)

    stats = {
        "trimmed": True,
        "original_samples": len(audio),
        "trimmed_samples": len(trimmed),
        "noise_floor": noise_floor,
        "peak_energy": peak_energy,
        "threshold": threshold,
        "active_ratio": active_ratio
    }
    return trimmed, stats


def normalize_audio_gain(audio: np.ndarray, target_peak: float = 0.70) -> np.ndarray:
    """
    Normalizes low-gain microphone recordings to standard speech amplitude range.
    Ensures input acoustic energy matches the training distribution of VoxCeleb models.
    """
    peak = float(np.max(np.abs(audio)))
    if 0.005 < peak < target_peak:
        scale = target_peak / peak
        return (audio * scale).astype(np.float32)
    return audio


class SpeakerEmbeddingModel:
    """Neural Speaker Embedding Extractor for Voice Authentication."""

    def __init__(self, model_path: Path = config.SPEAKER_MODEL_PATH):
        self.model_path = Path(model_path)
        self.sample_rate = config.SAMPLE_RATE
        self.num_mel_bins = config.NUM_MEL_BINS
        self.frame_length_ms = config.FRAME_LENGTH_MS
        self.frame_shift_ms = config.FRAME_SHIFT_MS
        self.preemph_coeff = config.PREEMPH_COEFF
        self.n_fft = config.N_FFT

        self._ensure_model_exists()

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(self.model_path), sess_options=sess_options)

        self.input_info = self.session.get_inputs()[0]
        self.output_info = self.session.get_outputs()[0]
        self.input_name = self.input_info.name
        self.output_name = self.output_info.name

        out_dim = self.output_info.shape[-1]
        self.embedding_dim = out_dim if isinstance(out_dim, int) else config.EMBEDDING_DIM

        # Frame parameters
        self.frame_length = int(self.sample_rate * self.frame_length_ms / 1000.0)  # 400
        self.frame_shift = int(self.sample_rate * self.frame_shift_ms / 1000.0)    # 160

        # Kaldi-standard Hamming window: 0.54 - 0.46 * cos(2*pi*i / (N-1))
        i_arr = np.arange(self.frame_length, dtype=np.float32)
        self.window = (0.54 - 0.46 * np.cos(2.0 * np.pi * i_arr / (self.frame_length - 1))).astype(np.float32)

        # Precompute Kaldi-standard Mel filterbank matrix (padded at Nyquist)
        self.mel_filterbank = self._create_kaldi_mel_filterbank().astype(np.float32)

    def _ensure_model_exists(self):
        if not self.model_path.exists():
            from huggingface_hub import hf_hub_download
            import shutil
            downloaded = hf_hub_download(repo_id="Alkd/speaker-embedding-onnx", filename="model.onnx")
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(downloaded, self.model_path)

    def _create_kaldi_mel_filterbank(self) -> np.ndarray:
        """
        Creates Kaldi-standard 80-bin triangular Mel filterbank matrix of shape (80, n_fft//2 + 1).
        Nyquist bin is zero-padded as per Kaldi specifications.
        """
        low_freq = 20.0
        high_freq = self.sample_rate / 2.0  # 8000 Hz

        def hz_to_mel(hz):
            return 1127.0 * np.log(1.0 + hz / 700.0)

        mel_low = hz_to_mel(low_freq)
        mel_high = hz_to_mel(high_freq)
        mel_delta = (mel_high - mel_low) / (self.num_mel_bins + 1)

        bin_arr = np.arange(self.num_mel_bins)[:, None]  # (80, 1)
        left_mel = mel_low + bin_arr * mel_delta
        center_mel = mel_low + (bin_arr + 1.0) * mel_delta
        right_mel = mel_low + (bin_arr + 2.0) * mel_delta

        num_fft_bins = self.n_fft // 2  # 256
        fft_bin_width = self.sample_rate / self.n_fft  # 31.25 Hz
        fft_freqs = fft_bin_width * np.arange(num_fft_bins)
        mel_fft = hz_to_mel(fft_freqs)[None, :]  # (1, 256)

        up_slope = (mel_fft - left_mel) / (center_mel - left_mel)
        down_slope = (right_mel - mel_fft) / (right_mel - center_mel)
        bins = np.maximum(0.0, np.minimum(up_slope, down_slope))  # (80, 256)

        # Pad Nyquist bin 256 with zero -> (80, 257)
        bins = np.pad(bins, ((0, 0), (0, 1)), mode="constant", constant_values=0.0)
        return bins

    def extract_features(self, audio: np.ndarray, apply_vad: bool = True) -> tuple[np.ndarray, dict]:
        """
        Extracts Kaldi-standard 80-channel log-mel filterbank features.
        Returns:
            (features, diag_stats)
            features: shape (1, num_frames, 80) float32
        """
        raw_rms = float(np.sqrt(np.mean(audio ** 2)))
        raw_peak = float(np.max(np.abs(audio)))
        raw_duration = len(audio) / self.sample_rate

        # 1. Voice Activity Detection & Silence Trimming
        if apply_vad:
            proc_audio, vad_stats = trim_silence_vad(audio, sample_rate=self.sample_rate)
        else:
            proc_audio, vad_stats = audio, {"trimmed": False}

        # 2. Dynamic range peak normalization
        proc_audio = normalize_audio_gain(proc_audio, target_peak=0.70)
        proc_rms = float(np.sqrt(np.mean(proc_audio ** 2)))
        proc_peak = float(np.max(np.abs(proc_audio)))
        proc_duration = len(proc_audio) / self.sample_rate

        # 3. Waveform scaling to Kaldi range [-32768, 32767]
        if np.max(np.abs(proc_audio)) <= 1.0:
            waveform = (proc_audio * 32768.0).astype(np.float32)
        else:
            waveform = proc_audio.astype(np.float32)

        num_samples = len(waveform)
        if num_samples < self.frame_length:
            waveform = np.pad(waveform, (0, self.frame_length - num_samples))
            num_samples = len(waveform)

        # 4. Framing
        num_frames = 1 + (num_samples - self.frame_length) // self.frame_shift
        frames = np.empty((num_frames, self.frame_length), dtype=np.float32)
        for i in range(num_frames):
            start = i * self.frame_shift
            frames[i] = waveform[start:start + self.frame_length]

        # 5. Remove DC offset per frame (BEFORE pre-emphasis, matching Kaldi specification)
        row_means = np.mean(frames, axis=1, keepdims=True)
        frames -= row_means

        # 6. Pre-emphasis per frame with edge replication
        if self.preemph_coeff > 0.0:
            offset = np.pad(frames, ((0, 0), (1, 0)), mode="edge")[:, :-1]
            frames -= self.preemph_coeff * offset

        # 7. Apply Hamming window
        frames *= self.window

        # 8. Zero-pad columns to n_fft (512)
        pad_cols = self.n_fft - self.frame_length
        if pad_cols > 0:
            frames = np.pad(frames, ((0, 0), (0, pad_cols)), mode="constant", constant_values=0.0)

        # 9. Real FFT & Power Spectrum
        spectrum = np.abs(np.fft.rfft(frames, n=self.n_fft)) ** 2  # (num_frames, 257)

        # 10. Mel Filterbank Projection
        mel_energies = np.dot(spectrum, self.mel_filterbank.T)  # (num_frames, 80)

        # 11. Log Mel with float epsilon floor (1.1920929e-07)
        mel_energies = np.log(np.maximum(mel_energies, 1.1920929e-07))

        # 12. Per-bin mean subtraction: feats -= feats.mean(axis=0)
        feats = mel_energies - np.mean(mel_energies, axis=0, keepdims=True)

        features_tensor = np.expand_dims(feats.astype(np.float32), axis=0)

        diag_stats = {
            "raw_rms": raw_rms,
            "raw_peak": raw_peak,
            "raw_duration": raw_duration,
            "proc_rms": proc_rms,
            "proc_peak": proc_peak,
            "proc_duration": proc_duration,
            "num_frames": num_frames,
            "feature_shape": features_tensor.shape,
            "feature_mean": float(np.mean(feats)),
            "feature_std": float(np.std(feats)),
            "vad_stats": vad_stats
        }

        return features_tensor, diag_stats

    def generate_embedding(self, audio: np.ndarray, apply_vad: bool = True) -> tuple[np.ndarray, dict]:
        """
        Generates an L2-normalized 256-dimensional speaker embedding vector.
        audio: 1D float32 numpy array sampled at 16 kHz.
        Returns:
            (embedding, diagnostic_stats)
        """
        features, diag = self.extract_features(audio, apply_vad=apply_vad)
        outputs = self.session.run(None, {self.input_name: features})
        raw_emb = outputs[0][0]  # Shape: (256,)

        raw_norm = float(np.linalg.norm(raw_emb))
        if raw_norm > 1e-6:
            normalized_emb = raw_emb / raw_norm
        else:
            normalized_emb = raw_emb

        diag["raw_embedding_norm"] = raw_norm
        diag["final_embedding_norm"] = float(np.linalg.norm(normalized_emb))
        diag["embedding_dim"] = len(normalized_emb)

        return normalized_emb.astype(np.float32), diag


def compute_cosine_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Computes cosine similarity between two unit vectors."""
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(np.dot(emb1, emb2) / (norm1 * norm2))
