from contextlib import nullcontext
import ctypes
import unittest
from unittest.mock import patch, call
import win32con

from pi_voice import windows
from pi_voice.windows import ClipboardPaste, send_shift_insert


class PasteTests(unittest.TestCase):
    def setUp(self):
        self.clip = patch("pi_voice.windows.clipboard").start()
        patch("pi_voice.windows.opened_clipboard", side_effect=lambda: nullcontext()).start()
        self.key_state = patch("pi_voice.windows.win32api.GetAsyncKeyState", return_value=0).start()
        self.f8_pressed = patch("pi_voice.windows.keyboard.is_pressed", return_value=False).start()
        self.focus = patch("pi_voice.windows.foreground", return_value=123).start()
        self.send = patch("pi_voice.windows.keyboard.send").start()
        self.press = patch("pi_voice.windows.keyboard.press").start()
        self.release = patch("pi_voice.windows.keyboard.release").start()
        self.native = patch("pi_voice.windows._SEND_INPUT", side_effect=self.accept_input).start()
        self.sleep = patch("pi_voice.windows.time.sleep").start()
        self.packets = []
        self.return_counts = []
        self.addCleanup(patch.stopall)

    def accept_input(self, count, packet, size):
        self.assertEqual(size, ctypes.sizeof(windows._INPUT))
        events = []
        for item in packet:
            self.assertEqual(item.type, 1)  # INPUT_KEYBOARD only.
            events.append((item.data.ki.wVk, item.data.ki.wScan, item.data.ki.dwFlags))
        self.packets.append(events)
        result = self.return_counts.pop(0) if self.return_counts else count
        if result != count:
            ctypes.set_last_error(5)
        return result

    def assert_native_sequence(self):
        self.assertEqual(self.packets, [[(0, 0x2A, 0x0008), (0, 0x52, 0x0009)],
                                      [(0, 0x52, 0x000B)], [(0, 0x2A, 0x000A)]])
        # No Unicode injection, Ctrl+V, keyboard.send/press/release or Enter.
        self.send.assert_not_called()
        self.press.assert_not_called()
        self.release.assert_not_called()

    def test_input_structure_matches_windows_abi(self):
        self.assertEqual(ctypes.sizeof(windows._INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        self.assertEqual(ctypes.sizeof(windows._KEYBDINPUT), 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)

    def test_unicode_single_line_and_no_enter(self):
        ClipboardPaste()("Привет\r\nмир\t!", 123)
        self.clip.SetClipboardText.assert_called_once_with("Привет мир !", win32con.CF_UNICODETEXT)
        self.assert_native_sequence()
        self.sleep.assert_called_once_with(0.05)

    def test_changed_focus_copies_without_sending_keys(self):
        self.focus.return_value = 456
        with self.assertRaisesRegex(RuntimeError, "window changed"):
            ClipboardPaste()("Текст", 123)
        self.clip.SetClipboardText.assert_called_once()
        self.native.assert_not_called()
        self.press.assert_not_called()
        self.release.assert_not_called()

    def test_waits_for_suppressed_f8_release(self):
        self.f8_pressed.side_effect = [True, False, False]
        ClipboardPaste()("Текст", 123)
        self.assertEqual(self.f8_pressed.call_count, 3)
        self.assertEqual(self.sleep.call_args_list, [call(0.02), call(0.05)])
        self.assert_native_sequence()

    def test_waits_for_windows_f8_release(self):
        f8_states = iter([0x8000, 0, 0])
        self.key_state.side_effect = lambda key: next(f8_states) if key == win32con.VK_F8 else 0
        ClipboardPaste()("Текст", 123)
        self.assertEqual(self.sleep.call_args_list, [call(0.02), call(0.05)])
        self.assert_native_sequence()

    def test_f8_still_held_leaves_text_in_clipboard_without_pasting(self):
        self.f8_pressed.return_value = True
        with patch("pi_voice.windows.time.monotonic", side_effect=[0, 1]):
            with self.assertRaisesRegex(RuntimeError, "Keys held"):
                ClipboardPaste()("Текст", 123)
        self.clip.SetClipboardText.assert_called_once_with("Текст", win32con.CF_UNICODETEXT)
        self.native.assert_not_called()

    def test_repress_during_settle_delay_does_not_paste(self):
        self.f8_pressed.side_effect = [False, True]
        with self.assertRaisesRegex(RuntimeError, "Keys held"):
            ClipboardPaste()("Текст", 123)
        self.sleep.assert_called_once_with(0.05)
        self.native.assert_not_called()

    def test_settle_delay_precedes_native_input(self):
        actions = []
        self.sleep.side_effect = lambda seconds: actions.append(("sleep", seconds))
        def accept(count, packet, size):
            actions.append(("send", count))
            return self.accept_input(count, packet, size)
        self.native.side_effect = accept
        ClipboardPaste()("Текст", 123)
        self.assertEqual(actions, [("sleep", 0.05), ("send", 2), ("send", 1), ("send", 1)])

    def test_diagnostic_logs(self):
        with self.assertLogs("pi_voice.windows", level="INFO") as logged:
            ClipboardPaste()("Привет", 123)
        messages = [record.getMessage() for record in logged.records]
        self.assertEqual(messages, ["Recognized: Привет", "Clipboard updated", "F8 released",
                                    "Sending Shift+Insert via SendInput", "Paste sent; Enter not sent."])

    def test_releases_both_keys_if_sendinput_is_blocked(self):
        self.return_counts = [0, 1, 1]
        with self.assertRaisesRegex(OSError, "SendInput sent 0/2.*Win32 error 5"):
            send_shift_insert()
        self.assert_native_sequence()

    def test_partial_send_is_not_retried_and_both_keys_are_released(self):
        self.return_counts = [1, 1, 1]
        with self.assertRaisesRegex(OSError, "SendInput sent 1/2"):
            send_shift_insert()
        self.assert_native_sequence()
        self.assertEqual(self.native.call_count, 3)

    def test_attempts_shift_release_even_if_insert_release_fails(self):
        self.return_counts = [2, 0, 1]
        with self.assertRaisesRegex(OSError, "SendInput sent 0/1"):
            send_shift_insert()
        self.assert_native_sequence()

    def test_reports_shift_release_failure(self):
        self.return_counts = [2, 1, 0]
        with self.assertRaisesRegex(OSError, "SendInput sent 0/1"):
            send_shift_insert()
        self.assert_native_sequence()

    def test_empty_result_does_not_change_clipboard(self):
        ClipboardPaste()("  ", 123)
        self.clip.EmptyClipboard.assert_not_called()
        self.native.assert_not_called()

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
