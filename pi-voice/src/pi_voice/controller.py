"""Serial state machine; keyboard callbacks only enqueue edges."""
import logging
from queue import Queue, Empty
import threading
import time

LOG = logging.getLogger(__name__)


class PushToTalk:
    def __init__(self, recorder, recognizer, paste, foreground, max_seconds=120):
        self.recorder = recorder
        self.recognizer = recognizer
        self.paste = paste
        self.foreground = foreground
        self.max_seconds = max_seconds
        self.events = Queue()
        self.state = "idle"
        self.held = False
        self.target = None
        self.started = 0.0
        self.worker = None
        self._edge_lock = threading.Lock()
        self._key_down = False

    def key_event(self, event_type):
        # Filter OS auto-repeat before the queue can grow.
        with self._edge_lock:
            down = event_type == "down"
            if down == self._key_down:
                return
            self._key_down = down
            target = self.foreground() if down else None
            self.events.put((event_type, target))

    def handle(self, kind, value=None):
        if kind == "down":
            self.held = True
            if self.state != "idle":
                LOG.info("Busy: F8 ignored; release and press again when ready.")
                return
            try:
                self.recorder.start()
            except Exception:
                LOG.exception("Cannot start microphone")
                return
            self.target = value
            self.started = time.monotonic()
            self.state = "recording"
            LOG.info("Recording; release F8 to transcribe.")
        elif kind == "up":
            self.held = False
            if self.state == "recording":
                self.finish_recording()
        elif kind == "result":
            try:
                if value:
                    self.paste(value, self.target)
                else:
                    LOG.info("No speech detected.")
            except Exception:
                LOG.exception("Paste failed; no Enter was sent.")
            finally:
                self.state = "idle"
                LOG.info("Ready. Hold F8.")
        elif kind == "error":
            LOG.error("Recognition failed: %s", value)
            self.state = "idle"
            LOG.info("Ready. Hold F8.")

    def finish_recording(self):
        try:
            audio = self.recorder.stop()
        except Exception:
            self.state = "idle"
            LOG.exception("Recording failed")
            return
        if audio.size < 3200:
            self.state = "idle"
            LOG.info("Recording shorter than 0.2 s; skipped.")
            return
        self.state = "transcribing"
        LOG.info("Transcribing locally...")
        self.worker = threading.Thread(target=self._recognize, args=(audio,), daemon=True)
        self.worker.start()

    def _recognize(self, audio):
        try:
            text = self.recognizer.transcribe(audio)
            self.events.put(("result", text))
        except Exception as error:
            self.events.put(("error", str(error)))
        # Audio is only an in-memory array, released with this thread.

    def tick(self, timeout=0.1):
        try:
            self.handle(*self.events.get(timeout=timeout))
        except Empty:
            pass
        if self.state == "recording" and time.monotonic() - self.started >= self.max_seconds:
            LOG.warning("Recording limit reached (%s s).", self.max_seconds)
            self.finish_recording()

    def close(self):
        # Do not paste an unfinished result during shutdown.
        self.recorder.close()
        if self.worker is not None:
            self.worker.join()
