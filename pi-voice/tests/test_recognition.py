from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import numpy as np

from pi_voice.recognition import Recognizer


class RecognitionTests(unittest.TestCase):
    def test_model_loaded_once_and_output_cannot_contain_newlines(self):
        with patch("pi_voice.runtime.configure_cuda"), \
             patch("ctranslate2.get_cuda_device_count", return_value=1), \
             patch("ctranslate2.get_supported_compute_types", return_value={"float16"}), \
             patch("faster_whisper.WhisperModel") as factory:
            model = factory.return_value
            model.transcribe.side_effect = lambda *a, **k: (iter([
                SimpleNamespace(text=" Привет\nмир "), SimpleNamespace(text=" снова\r\n ")]), None)
            recognizer = Recognizer()
            audio = np.ones(16000, dtype=np.float32)
            for _ in range(2):
                self.assertEqual(recognizer.transcribe(audio), "Привет мир снова")
            factory.assert_called_once()
            self.assertEqual(model.transcribe.call_count, 2)
            self.assertTrue(model.transcribe.call_args.kwargs["vad_filter"])
            self.assertEqual(model.transcribe.call_args.kwargs["language"], "ru")

    def test_no_silent_cpu_fallback(self):
        with patch("pi_voice.runtime.configure_cuda"), \
             patch("ctranslate2.get_cuda_device_count", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "CUDA GPU"):
                Recognizer()

    def test_cpu_defaults_to_int8(self):
        with patch("ctranslate2.get_supported_compute_types", return_value={"int8"}), \
             patch("faster_whisper.WhisperModel") as factory:
            Recognizer(device="cpu")
            self.assertEqual(factory.call_args.kwargs["compute_type"], "int8")
            self.assertEqual(factory.call_args.kwargs["device"], "cpu")


if __name__ == "__main__":
    unittest.main()
