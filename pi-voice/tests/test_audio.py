import unittest
from unittest.mock import Mock, patch
import numpy as np

from pi_voice.audio import Microphone


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.stream = Mock(active=True)
        self.settings = patch("pi_voice.audio.sd.check_input_settings").start()
        self.factory = patch("pi_voice.audio.sd.InputStream", return_value=self.stream).start()
        self.addCleanup(patch.stopall)
        self.mic = Microphone(max_seconds=1)
        self.callback = self.factory.call_args.kwargs["callback"]
        self.addCleanup(self.mic.close)

    def test_only_records_between_start_and_stop(self):
        chunk = np.ones((160, 1), dtype=np.float32)
        self.callback(chunk, 160, None, None)
        self.mic.start()
        self.callback(chunk, 160, None, None)
        chunk.fill(0)
        result = self.mic.stop()
        np.testing.assert_equal(result, np.ones(160, dtype=np.float32))
        self.mic.start()
        self.assertEqual(self.mic.stop().size, 0)

    def test_memory_is_bounded(self):
        self.mic.start()
        chunk = np.zeros((16000, 1), dtype=np.float32)
        for _ in range(4):
            self.callback(chunk, 16000, None, None)
        self.assertEqual(self.mic.stop().size, 16000)

    def test_input_overflow_is_not_silenced(self):
        self.mic.start()
        self.callback(np.zeros((10, 1)), 10, None, "input overflow")
        with self.assertRaisesRegex(RuntimeError, "input overflow"):
            self.mic.stop()


if __name__ == "__main__":
    unittest.main()
