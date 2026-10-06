from contextlib import nullcontext
import unittest
from unittest.mock import patch, Mock
import win32con

from pi_voice.windows import ClipboardPaste


class PasteTests(unittest.TestCase):
    def setUp(self):
        self.clip = patch("pi_voice.windows.clipboard").start()
        patch("pi_voice.windows.opened_clipboard", side_effect=lambda: nullcontext()).start()
        patch("pi_voice.windows.win32api.GetAsyncKeyState", return_value=0).start()
        self.focus = patch("pi_voice.windows.foreground", return_value=123).start()
        self.send = patch("pi_voice.windows.keyboard.send").start()
        patch("pi_voice.windows.time.sleep").start()
        self.addCleanup(patch.stopall)

    def test_unicode_single_line_and_no_enter(self):
        ClipboardPaste()("Привет\r\nмир\t!", 123)
        self.clip.SetClipboardText.assert_called_once_with("Привет мир !", win32con.CF_UNICODETEXT)
        self.send.assert_called_once_with("ctrl+v")

    def test_changed_focus_copies_without_sending_keys(self):
        self.focus.return_value = 456
        with self.assertRaisesRegex(RuntimeError, "window changed"):
            ClipboardPaste()("Текст", 123)
        self.clip.SetClipboardText.assert_called_once()
        self.send.assert_not_called()

    def test_empty_result_does_not_change_clipboard(self):
        ClipboardPaste()("  ", 123)
        self.clip.EmptyClipboard.assert_not_called()

    def test_opt_in_restores_plain_text(self):
        self.clip.EnumClipboardFormats.side_effect = [win32con.CF_UNICODETEXT, 0]
        self.clip.GetClipboardSequenceNumber.return_value = 100
        self.clip.GetClipboardData.side_effect = ["старый текст", "новый текст"]
        ClipboardPaste(restore=True)("новый текст", 123)
        self.assertEqual(self.clip.SetClipboardText.call_count, 2)
        self.clip.SetClipboardText.assert_called_with("старый текст", win32con.CF_UNICODETEXT)

    def test_concurrent_copy_is_not_overwritten(self):
        self.clip.EnumClipboardFormats.side_effect = [win32con.CF_UNICODETEXT, 0]
        self.clip.GetClipboardData.return_value = "старый текст"
        self.clip.GetClipboardSequenceNumber.side_effect = [100, 101]
        ClipboardPaste(restore=True)("новый текст", 123)
        self.clip.SetClipboardText.assert_called_once()

    def test_rich_clipboard_is_not_restored_as_plain_text(self):
        self.clip.EnumClipboardFormats.side_effect = [win32con.CF_UNICODETEXT, 9999, 0]
        ClipboardPaste(restore=True)("новый текст", 123)
        self.clip.SetClipboardText.assert_called_once()


if __name__ == "__main__":
    unittest.main()
