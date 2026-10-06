import threading
import unittest
from unittest.mock import Mock
import numpy as np

from pi_voice.controller import PushToTalk


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.recorder = Mock()
        self.recorder.stop.return_value = np.ones(16000, dtype=np.float32)
        self.recognizer = Mock()
        self.recognizer.transcribe.return_value = "Привет, мир"
        self.paste = Mock()
        self.ptt = PushToTalk(self.recorder, self.recognizer, self.paste, lambda: 123)

    def finish(self):
        self.ptt.worker.join(timeout=2)
        self.ptt.tick(0)

    def test_down_repeat_up_and_second_dictation(self):
        for _ in range(2):
            self.ptt.key_event("down")
            for _ in range(100):
                self.ptt.key_event("down")
            self.assertEqual(self.ptt.events.qsize(), 1)
            self.ptt.tick(0)
            self.ptt.key_event("up")
            self.ptt.tick(0)
            self.finish()
            self.assertEqual(self.ptt.state, "idle")
        self.assertEqual(self.recorder.start.call_count, 2)
        self.assertEqual(self.recognizer.transcribe.call_count, 2)
        self.paste.assert_called_with("Привет, мир", 123)

    def test_busy_press_is_not_started_when_result_arrives(self):
        entered, release = threading.Event(), threading.Event()
        def transcribe(audio):
            entered.set()
            release.wait(2)
            return "Текст"
        self.recognizer.transcribe.side_effect = transcribe
        self.ptt.handle("down", 123)
        self.ptt.handle("up")
        self.assertTrue(entered.wait(1))
        self.ptt.handle("down", 123)
        self.ptt.handle("up")
        self.recorder.start.assert_called_once()
        release.set()
        self.finish()
        self.recognizer.transcribe.assert_called_once()

    def test_short_clip_is_skipped(self):
        self.recorder.stop.return_value = np.zeros(100, dtype=np.float32)
        self.ptt.handle("down", 123)
        self.ptt.handle("up")
        self.assertEqual(self.ptt.state, "idle")
        self.recognizer.transcribe.assert_not_called()

    def test_recognition_error_recovers(self):
        self.recognizer.transcribe.side_effect = RuntimeError("CUDA failure")
        self.ptt.handle("down", 123)
        self.ptt.handle("up")
        self.finish()
        self.assertEqual(self.ptt.state, "idle")
        self.paste.assert_not_called()

    def test_empty_result_does_not_paste(self):
        self.ptt.handle("result", "")
        self.paste.assert_not_called()

    def test_paste_error_recovers(self):
        self.paste.side_effect = RuntimeError("focus changed")
        self.ptt.handle("result", "Текст")
        self.assertEqual(self.ptt.state, "idle")

    def test_microphone_errors_recover(self):
        self.recorder.start.side_effect = RuntimeError("unplugged")
        self.ptt.handle("down", 123)
        self.assertEqual(self.ptt.state, "idle")
        self.recorder.start.side_effect = None
        self.recorder.stop.side_effect = RuntimeError("overflow")
        self.ptt.handle("down", 123)
        self.ptt.handle("up")
        self.assertEqual(self.ptt.state, "idle")

    def test_time_limit_stops_once(self):
        self.ptt.handle("down", 123)
        self.ptt.started = 0
        self.ptt.tick(0)
        self.finish()
        self.ptt.handle("up")
        self.recorder.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
