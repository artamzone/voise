import argparse
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

# Disable Hugging Face telemetry before importing model libraries.
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
LOG = logging.getLogger("pi_voice")
ROOT = Path(__file__).resolve().parents[2]


def parser():
    p = argparse.ArgumentParser(description="Pi Voice: hold F8, speak, release. No Enter.")
    p.add_argument("--model", default="large-v3-turbo", help="Whisper alias or local model folder")
    p.add_argument("--language", default="ru")
    p.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    p.add_argument("--compute-type", help="Default: float16 for GPU, int8 for CPU")
    p.add_argument("--microphone", type=int, help="Input device index from --list-microphones")
    p.add_argument("--model-dir", type=Path, default=ROOT / "models")
    p.add_argument("--offline", action="store_true", help="Do not download models")
    p.add_argument("--restore-clipboard", action="store_true", help="Best-effort text-only restore after 0.5 s")
    p.add_argument("--max-seconds", type=int, default=120)
    p.add_argument("--list-microphones", action="store_true")
    p.add_argument("--diagnose", action="store_true", help="Test GPU, DLLs and microphone for 0.5 s")
    p.add_argument("--check-model", action="store_true", help="Load model and run actual inference, then exit")
    p.add_argument("--transcribe-file", type=Path, help="Transcribe a local test file without pasting")
    return p


def diagnose(args):
    import ctypes
    import numpy as np
    import sounddevice as sd
    from .runtime import configure_cuda
    print("Python:", sys.version.split()[0], "executable:", sys.executable)
    print("Local NVIDIA DLL directories:", *configure_cuda(), sep="\n  ")
    result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                            capture_output=True, text=True, check=True)
    print("NVIDIA:", result.stdout.strip())
    for dll in ("cublas64_12.dll", "cudnn64_9.dll"):
        ctypes.WinDLL(dll)
        print(dll, "OK")
    import ctranslate2
    print("CTranslate2:", ctranslate2.__version__, "CUDA GPUs:", ctranslate2.get_cuda_device_count())
    print("CUDA compute types:", sorted(ctranslate2.get_supported_compute_types("cuda")))
    print("Microphone:", sd.query_devices(args.microphone, "input")["name"])
    from .audio import Microphone
    mic = Microphone(args.microphone)
    try:
        mic.start()
        time.sleep(0.5)
        audio = mic.stop()
        if not audio.size:
            raise RuntimeError("Microphone returned no samples")
        print("Microphone frames:", audio.size, "RMS:", round(float(np.sqrt(np.mean(audio ** 2))), 6))
    finally:
        mic.close()


def load_model(args):
    from .recognition import Recognizer
    recognizer = Recognizer(args.model, args.device, args.compute_type, args.language,
                            args.model_dir, args.offline)
    import numpy as np
    # Force real kernels (including cuDNN), rather than testing only GPU enumeration.
    started = time.perf_counter()
    segments, _ = recognizer.model.transcribe(np.zeros(16000, dtype=np.float32),
                                            language=args.language, beam_size=1, vad_filter=False)
    list(segments)
    LOG.info("Inference warm-up OK: %.3f s", time.perf_counter() - started)
    return recognizer


def run(args):
    import keyboard
    from .audio import Microphone
    from .controller import PushToTalk
    from .windows import ClipboardPaste, foreground, single_instance
    with single_instance():
        recognizer = load_model(args)
        mic = Microphone(args.microphone, args.max_seconds)
        controller = PushToTalk(mic, recognizer, ClipboardPaste(args.restore_clipboard),
                                foreground, args.max_seconds)
        hook = None
        try:
            hook = keyboard.hook_key("f8", lambda event: controller.key_event(event.event_type), suppress=True)
            LOG.info("Ready. Hold F8. Ctrl+C in this console to quit.")
            while True:
                controller.tick()
        except KeyboardInterrupt:
            LOG.info("Stopping (waiting for pending inference; no paste on shutdown)...")
        finally:
            if hook is not None:
                keyboard.unhook(hook)
            controller.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    # Download URLs may contain signed credentials; do not log HTTP requests.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    p = parser()
    args = p.parse_args()
    if args.max_seconds < 1 or args.max_seconds > 600:
        p.error("--max-seconds must be between 1 and 600")
    if sys.platform != "win32":
        p.error("Pi Voice requires Windows")
    try:
        if args.list_microphones:
            import sounddevice as sd
            for index, device in enumerate(sd.query_devices()):
                if device["max_input_channels"]:
                    print(f"{index}: {device['name']} ({sd.query_hostapis(device['hostapi'])['name']})")
        elif args.diagnose:
            diagnose(args)
        elif args.check_model:
            load_model(args)
        elif args.transcribe_file:
            recognizer = load_model(args)
            from faster_whisper.audio import decode_audio
            print(recognizer.transcribe(decode_audio(str(args.transcribe_file))))
        else:
            run(args)
    except Exception:
        LOG.exception("Pi Voice failed. Check microphone permissions, DLLs and model cache; see README.md.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
