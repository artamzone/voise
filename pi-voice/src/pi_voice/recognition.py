import logging
import time

LOG = logging.getLogger(__name__)


class Recognizer:
    def __init__(self, model="large-v3-turbo", device="cuda", compute_type=None,
                 language="ru", cache=None, offline=False):
        from .runtime import configure_cuda
        if device == "cuda":
            configure_cuda()
        import ctranslate2
        from faster_whisper import WhisperModel
        compute_type = compute_type or ("float16" if device == "cuda" else "int8")
        if device == "cuda" and not ctranslate2.get_cuda_device_count():
            raise RuntimeError("CTranslate2 cannot see a CUDA GPU. Use --device cpu explicitly.")
        supported = ctranslate2.get_supported_compute_types(device)
        if compute_type not in supported:
            raise ValueError(f"Unsupported compute type {compute_type}; supported: {sorted(supported)}")
        LOG.info("Loading %s on %s (%s); model is loaded once.", model, device, compute_type)
        self.language = language
        self.model = WhisperModel(model, device=device, device_index=0, compute_type=compute_type,
                                  download_root=str(cache) if cache else None,
                                  local_files_only=offline)
        LOG.info("Model loaded: device=%s, compute_type=%s", self.model.model.device,
                 self.model.model.compute_type)

    def transcribe(self, audio):
        started = time.perf_counter()
        segments, _ = self.model.transcribe(audio, language=self.language, beam_size=1,
                                            vad_filter=True, condition_on_previous_text=False)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        # Never send model-produced line breaks / Enter to a terminal.
        text = " ".join(text.split())
        LOG.info("Recognition: %.3f s; audio: %.2f s; characters: %d",
                 time.perf_counter() - started, len(audio) / 16000, len(text))
        return text
