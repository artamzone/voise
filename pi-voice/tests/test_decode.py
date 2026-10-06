"""Compatibility regression: faster-whisper calls PyAV's metadata_errors API."""
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np
from faster_whisper.audio import decode_audio


class DecodeTests(unittest.TestCase):
    def test_local_wav_can_be_decoded_and_removed(self):
        with tempfile.TemporaryDirectory(prefix="pi-voice-decode-") as directory:
            path = Path(directory) / "test.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(np.zeros(16000, dtype=np.int16).tobytes())
            result = decode_audio(str(path))
            self.assertEqual(result.shape, (16000,))
            self.assertEqual(result.dtype, np.float32)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
