"""Unicode clipboard paste. No Enter; no automatic focus changes."""
from contextlib import contextmanager
import logging
import time

import keyboard
import win32api
import win32clipboard as clipboard
import win32con
import win32event
import win32gui
import winerror

LOG = logging.getLogger(__name__)


def foreground():
    return win32gui.GetForegroundWindow()


@contextmanager
def single_instance():
    handle = win32event.CreateMutex(None, False, "Local\\PiVoicePushToTalk")
    try:
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            raise RuntimeError("Pi Voice is already running.")
        yield
    finally:
        win32api.CloseHandle(handle)


@contextmanager
def opened_clipboard():
    # A real owner HWND is required by EmptyClipboard/SetClipboardData.
    owner = win32gui.CreateWindowEx(0, "STATIC", "Pi Voice clipboard", 0,
                                   0, 0, 0, 0, win32con.HWND_MESSAGE, 0, 0, None)
    opened = False
    try:
        for attempt in range(20):
            try:
                clipboard.OpenClipboard(owner)
                opened = True
                break
            except Exception:
                if attempt == 19:
                    raise
                time.sleep(0.025)
        yield
    finally:
        if opened:
            clipboard.CloseClipboard()
        win32gui.DestroyWindow(owner)


class ClipboardPaste:
    def __init__(self, restore=False):
        self.restore = restore

    def __call__(self, text, target):
        text = " ".join(text.split())
        if not text:
            return
        previous = None
        had_text = False
        with opened_clipboard():
            if self.restore:
                formats = []
                fmt = clipboard.EnumClipboardFormats(0)
                while fmt:
                    formats.append(fmt)
                    fmt = clipboard.EnumClipboardFormats(fmt)
                text_formats = {win32con.CF_UNICODETEXT, win32con.CF_TEXT,
                                win32con.CF_OEMTEXT, win32con.CF_LOCALE}
                if set(formats) <= text_formats and win32con.CF_UNICODETEXT in formats:
                    previous = clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    had_text = True
            clipboard.EmptyClipboard()
            clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            sequence = clipboard.GetClipboardSequenceNumber()
        # Copy still works when focus changed, but never paste into an unintended window.
        deadline = time.monotonic() + 1.0
        while any(win32api.GetAsyncKeyState(key) & 0x8000 for key in
                  (win32con.VK_CONTROL, win32con.VK_SHIFT, win32con.VK_MENU, win32con.VK_LWIN, win32con.VK_RWIN)):
            if time.monotonic() >= deadline:
                raise RuntimeError("Modifiers held: text is in clipboard; paste manually.")
            time.sleep(0.02)
        if not target or foreground() != target:
            raise RuntimeError("Active window changed: text is in clipboard; paste manually.")
        keyboard.send("ctrl+v")
        LOG.info("Ctrl+V sent; Enter not sent.")
        # Opt-in only: Windows has no acknowledgement that the app read the clipboard.
        if self.restore and had_text:
            time.sleep(0.5)
            with opened_clipboard():
                if (clipboard.GetClipboardSequenceNumber() == sequence
                        and clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
                        and clipboard.GetClipboardData(win32con.CF_UNICODETEXT) == text):
                    clipboard.EmptyClipboard()
                    clipboard.SetClipboardText(previous, win32con.CF_UNICODETEXT)
