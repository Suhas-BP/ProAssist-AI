"""
Audio Stream and Recording Utilities for ProAssist AI
Provides thread-safe microphone streaming and precise audio recording.
"""

import queue
import threading
import time
import pyaudio
import numpy as np
import config


class MicrophoneStream:
    """Continuous microphone stream for wake-word detection with background worker thread."""

    def __init__(self, sample_rate=config.SAMPLE_RATE, chunk_size=config.CHUNK_SIZE,
                 channels=config.CHANNELS, device_index=config.AUDIO_DEVICE_INDEX):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.device_index = device_index
        self.pyaudio_instance = None
        self.stream = None
        self._is_running = False
        self._audio_queue = queue.Queue(maxsize=200)
        self._worker_thread = None

    def get_device_info(self) -> dict:
        """Retrieves hardware and driver metadata for the input device."""
        try:
            p = self.pyaudio_instance or pyaudio.PyAudio()
            if self.device_index is None:
                info = p.get_default_input_device_info()
            else:
                info = p.get_device_info_by_host_api_device_index(0, self.device_index)
            if self.pyaudio_instance is None:
                p.terminate()
            return info
        except Exception:
            return {"name": "Default Audio Input", "index": self.device_index}

    def _capture_worker(self):
        """Continuously reads audio from the PyAudio stream without blocking the main thread."""
        while self._is_running and self.stream is not None:
            try:
                pcm_bytes = self.stream.read(self.chunk_size, exception_on_overflow=False)
                if not pcm_bytes:
                    time.sleep(0.005)
                    continue
                pcm_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
                if len(pcm_int16) == 0:
                    time.sleep(0.005)
                    continue
                if self._audio_queue.full():
                    try:
                        self._audio_queue.get_nowait()
                    except queue.Empty:
                        pass
                self._audio_queue.put((pcm_bytes, pcm_int16))
            except (IOError, OSError):
                if not self._is_running:
                    break
                time.sleep(0.01)
            except Exception:
                if not self._is_running:
                    break
                time.sleep(0.01)

    def start(self):
        if self._is_running:
            return

        self.pyaudio_instance = pyaudio.PyAudio()
        try:
            self.stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk_size
            )
            self._is_running = True

            # Clear queue of any stale items
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

            # Start background reader thread
            self._worker_thread = threading.Thread(target=self._capture_worker, daemon=True)
            self._worker_thread.start()
        except Exception as e:
            self.stop()
            raise RuntimeError(f"Failed to open microphone stream: {e}")

    @property
    def is_running(self) -> bool:
        return self._is_running

    def read_chunk(self, timeout: float = 0.2):
        """
        Retrieves audio from the stream queue.
        Drains all accumulated chunks to ensure zero frame loss during Whisper inference.
        Returns (pcm_bytes, pcm_int16).
        """
        if not self._is_running:
            return None, None

        try:
            item = self._audio_queue.get(timeout=timeout)
            byte_chunks = [item[0]]
            int16_chunks = [item[1]]

            # Drain any remaining accumulated chunks so the main loop stays real-time
            while not self._audio_queue.empty():
                try:
                    extra = self._audio_queue.get_nowait()
                    byte_chunks.append(extra[0])
                    int16_chunks.append(extra[1])
                except queue.Empty:
                    break

            if len(int16_chunks) == 1:
                return byte_chunks[0], int16_chunks[0]
            else:
                return b"".join(byte_chunks), np.concatenate(int16_chunks)
        except queue.Empty:
            return b"\x00" * (self.chunk_size * 2), np.zeros(self.chunk_size, dtype=np.int16)

    def stop(self):
        self._is_running = False
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)
            self._worker_thread = None

        if self.stream is not None:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if self.pyaudio_instance is not None:
            try:
                self.pyaudio_instance.terminate()
            except Exception:
                pass
            self.pyaudio_instance = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def record_audio(duration_seconds: float, sample_rate: int = config.SAMPLE_RATE,
                 channels: int = config.CHANNELS, device_index=config.AUDIO_DEVICE_INDEX) -> np.ndarray:
    """
    Records audio from microphone for specified duration.
    Flushes hardware startup transient and returns normalized float32 array in [-1.0, 1.0].
    """
    p = pyaudio.PyAudio()
    chunk_size = 1024
    total_samples = int(sample_rate * duration_seconds)

    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=chunk_size
        )
    except Exception as e:
        p.terminate()
        raise RuntimeError(f"Could not open microphone for recording: {e}")

    frames = []
    recorded_samples = 0
    try:
        # Flush initial buffer to eliminate hardware spin-up artifacts
        _ = stream.read(chunk_size, exception_on_overflow=False)

        while recorded_samples < total_samples:
            samples_to_read = min(chunk_size, total_samples - recorded_samples)
            data = stream.read(samples_to_read, exception_on_overflow=False)
            frames.append(data)
            recorded_samples += samples_to_read
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

    raw_bytes = b"".join(frames)
    audio_int16 = np.frombuffer(raw_bytes, dtype=np.int16)
    audio_float32 = (audio_int16 / 32768.0).astype(np.float32)
    return audio_float32
