r"""Opt-in Windows integration check: synthetic Russian speech + private test window.
Run from the project: .venv\Scripts\python.exe tests\local_smoke.py
No speech is uploaded. The temporary SAPI WAV is deleted in all cases.
"""
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"

import keyboard
import pythoncom
import win32api
import win32com.client
import win32con
import win32gui
import win32process
import tkinter as tk

from pi_voice.__main__ import parser, load_model
from pi_voice.controller import PushToTalk
from pi_voice.windows import ClipboardPaste, foreground, opened_clipboard, clipboard

PHRASE = "Посмотри текущий проект и проверь, почему не работает тёмная тема."


def russian_audio():
    from faster_whisper.audio import decode_audio
    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voices = voice.GetVoices()
        russian = [v for v in voices if v.GetAttribute("Language").lower() == "419"]
        if not russian:
            raise RuntimeError("No local Russian SAPI voice; benchmark needs a local test WAV.")
        voice.Voice = russian[0]
        print("Synthetic voice:", russian[0].GetDescription())
        with tempfile.TemporaryDirectory(prefix="pi-voice-smoke-") as directory:
            path = Path(directory) / "synthetic.wav"
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Open(str(path), 3)
            try:
                voice.AudioOutputStream = stream
                voice.Speak(PHRASE)
            finally:
                stream.Close()
                voice.AudioOutputStream = None
            audio = decode_audio(str(path))
        assert not path.exists(), "Temporary WAV left behind"
        print("Temporary audio removed: OK")
        return audio
    finally:
        pythoncom.CoUninitialize()


class TestClip:
    def __init__(self, audio):
        self.audio = audio
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1
        return self.audio.copy()

    def close(self):
        pass


def main():
    args = parser().parse_args(["--offline"])
    recognizer = load_model(args)
    print("Model:", args.model, "device:", recognizer.model.model.device,
          "compute:", recognizer.model.model.compute_type)
    audio = russian_audio()
    durations = []
    for _ in range(3):
        start = time.perf_counter()
        text = recognizer.transcribe(audio)
        durations.append(time.perf_counter() - start)
        if "проект" not in text.lower() or "тем" not in text.lower():
            raise AssertionError(f"Russian recognition mismatch: {text!r}")
    print("Recognized:", text)
    print("Audio duration:", round(len(audio) / 16000, 3), "s")
    print("Recognition runs:", [round(d, 3) for d in durations], "s; mean:", round(statistics.mean(durations), 3), "s")

    old_window = foreground()
    with opened_clipboard():
        old_text = clipboard.GetClipboardData(win32con.CF_UNICODETEXT) if clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT) else None
    root = tk.Tk()
    root.title("Pi Voice local test (closes automatically)")
    field = tk.Text(root, width=65, height=5)
    field.pack()
    root.update()
    root.lift()
    field.focus_force()
    top_window = win32gui.GetAncestor(root.winfo_id(), 2)  # GA_ROOT; Tk ID is a child HWND.
    try:
        if foreground() != top_window:
            win32gui.SetForegroundWindow(top_window)
        root.update()
        test_target = foreground()
    except Exception:
        root.destroy()
        raise
    # Only inject keys into this newly created test window.
    if win32process.GetWindowThreadProcessId(test_target)[1] != os.getpid():
        root.destroy()
        raise RuntimeError("Test window could not acquire focus; no keys sent")
    recording = TestClip(audio)
    ptt = PushToTalk(recording, recognizer, ClipboardPaste(), foreground)
    hook = keyboard.hook_key("f8", lambda event: ptt.key_event(event.event_type), suppress=True)
    last_text = None
    try:
        for iteration in range(2):
            # keyboard.press marks its own events as replayed and bypasses hooks.
            scan = win32api.MapVirtualKey(win32con.VK_F8, 0)
            win32api.keybd_event(win32con.VK_F8, scan, 0, 0)
            win32api.keybd_event(win32con.VK_F8, scan, 0, 0)
            until = time.monotonic() + 0.3
            while time.monotonic() < until:
                root.update()
                ptt.tick(0.01)
            assert ptt.state == "recording", "F8 DOWN did not reach hook"
            win32api.keybd_event(win32con.VK_F8, scan, win32con.KEYEVENTF_KEYUP, 0)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                root.update()
                ptt.tick(0.01)
                if ptt.state == "idle" and recording.stops == iteration + 1:
                    break
            else:
                raise AssertionError("F8 UP/recognition timed out")
            until = time.monotonic() + 0.5
            while time.monotonic() < until:
                root.update()
                time.sleep(0.01)
            inserted = field.get("1.0", "end-1c")
            assert inserted and "проект" in inserted.lower(), "Unicode paste failed"
            assert "\n" not in inserted, "Unexpected Enter/newline"
            print(f"F8 cycle {iteration + 1}: hook, recognition, Unicode paste, no Enter: OK")
            last_text = inserted
            field.delete("1.0", "end")
        assert recording.starts == 2 and recording.stops == 2, "Auto-repeat started extra capture"
        print("Repeated dictation without model reload: OK")
    finally:
        keyboard.release("f8")
        keyboard.unhook(hook)
        ptt.close()
        root.destroy()
        if old_text is not None:
            with opened_clipboard():
                if clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT) and clipboard.GetClipboardData(win32con.CF_UNICODETEXT) == last_text:
                    clipboard.EmptyClipboard()
                    clipboard.SetClipboardText(old_text, win32con.CF_UNICODETEXT)
        if win32gui.IsWindow(old_window) and foreground() != old_window:
            win32gui.SetForegroundWindow(old_window)


if __name__ == "__main__":
    main()
