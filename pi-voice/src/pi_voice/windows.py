"""Unicode clipboard paste. No Enter; no automatic focus changes."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
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


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    # Include all members: omitting MOUSEINPUT gives an invalid INPUT size on x64.
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", _INPUTUNION)]


_SEND_INPUT = ctypes.WinDLL("user32", use_last_error=True).SendInput
_SEND_INPUT.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_SEND_INPUT.restype = wintypes.UINT
_KEYEVENTF_SCANCODE = 0x0008


def _send_key_events(events):
    inputs = []
    for key, up in events:
        scan = win32api.MapVirtualKey(key, 0)
        if not scan:
            raise RuntimeError(f"Cannot map virtual key {key} to a scan code")
        flags = _KEYEVENTF_SCANCODE
        if key == win32con.VK_INSERT:
            flags |= win32con.KEYEVENTF_EXTENDEDKEY  # Main Insert, not numpad 0.
        if up:
            flags |= win32con.KEYEVENTF_KEYUP
        inputs.append(_INPUT(1, _INPUTUNION(ki=_KEYBDINPUT(0, scan, flags, 0, 0))))
    packet = (_INPUT * len(inputs))(*inputs)
    ctypes.set_last_error(0)
    sent = _SEND_INPUT(len(packet), packet, ctypes.sizeof(_INPUT))
    if sent != len(packet):
        error = ctypes.get_last_error()
        raise OSError(error, f"SendInput sent {sent}/{len(packet)} events (Win32 error {error}). "
                      "Input may be blocked by Windows/UIPI; check equal privilege levels. "
                      "Text remains in clipboard; no paste retry was attempted.")


def send_shift_insert():
    # Exactly one Insert DOWN. No retry if Windows accepts only part of a packet.
    try:
        _send_key_events(((win32con.VK_LSHIFT, False), (win32con.VK_INSERT, False)))
    finally:
        try:
            _send_key_events(((win32con.VK_INSERT, True),))
        finally:
            _send_key_events(((win32con.VK_LSHIFT, True),))


def _paste_keys_held():
    # Suppressed F8 may not appear in GetAsyncKeyState; also check the hook.
    return (keyboard.is_pressed("f8") or
            any(win32api.GetAsyncKeyState(key) & 0x8000 for key in
                (win32con.VK_F8, win32con.VK_INSERT, win32con.VK_CONTROL,
                 win32con.VK_SHIFT, win32con.VK_MENU, win32con.VK_LWIN, win32con.VK_RWIN)))


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
        LOG.info("Recognized: %s", text)
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
        LOG.info("Clipboard updated")
        # Copy still works when focus changed, but never paste into an unintended window.
        deadline = time.monotonic() + 1.0
        while _paste_keys_held():
            if time.monotonic() >= deadline:
                raise RuntimeError("Keys held (F8/Insert/modifiers): text is in clipboard; paste manually.")
            time.sleep(0.02)
        # Let F8 UP complete in the OS/hook before inserting the next combination.
        time.sleep(0.05)
        if _paste_keys_held():
            raise RuntimeError("Keys held again: text is in clipboard; paste manually.")
        LOG.info("F8 released")
        if not target or foreground() != target:
            raise RuntimeError("Active window changed: text is in clipboard; paste manually.")
        LOG.info("Sending Shift+Insert via SendInput")
        send_shift_insert()
        LOG.info("Paste sent; Enter not sent.")
        # Opt-in only: Windows has no acknowledgement that the app read the clipboard.
        if self.restore and had_text:
            time.sleep(0.5)
            with opened_clipboard():
                if (clipboard.GetClipboardSequenceNumber() == sequence
                        and clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
                        and clipboard.GetClipboardData(win32con.CF_UNICODETEXT) == text):
                    clipboard.EmptyClipboard()
                    clipboard.SetClipboardText(previous, win32con.CF_UNICODETEXT)
