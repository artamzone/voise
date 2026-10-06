import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


class Microphone:
    def __init__(self, device=None, max_seconds=120):
        sd.check_input_settings(device=device, channels=1, dtype="float32", samplerate=SAMPLE_RATE)
        self._lock = threading.Lock()
        self._recording = False
        self._chunks = []
        self._samples = 0
        self._limit = int(max_seconds * SAMPLE_RATE)
        self._error = None
        self.stream = sd.InputStream(device=device, channels=1, samplerate=SAMPLE_RATE,
                                     dtype="float32", callback=self._callback)
        try:
            self.stream.start()
        except Exception:
            self.stream.close()
            raise

    def _callback(self, data, frames, timing, status):
        with self._lock:
            if not self._recording:
                return
            if status:
                self._error = str(status)
            count = min(frames, self._limit - self._samples)
            if count > 0:
                self._chunks.append(data[:count, 0].copy())
                self._samples += count

    def start(self):
        if not self.stream.active:
            raise RuntimeError("Microphone stream stopped; restart Pi Voice.")
        with self._lock:
            self._chunks = []
            self._samples = 0
            self._error = None
            self._recording = True

    def stop(self):
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
            error = self._error
        if error:
            raise RuntimeError(f"Microphone lost audio: {error}")
        return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)

    def close(self):
        with self._lock:
            self._recording = False
            self._chunks.clear()
        self.stream.stop()
        self.stream.close()
