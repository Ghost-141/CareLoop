"""Optional local Kokoro TTS and Whisper STT (MLX on Apple Silicon, faster-whisper elsewhere); browser speech is always the fallback."""
from __future__ import annotations
import io, os, platform, sys, threading, urllib.request, wave
from pathlib import Path

class VoiceUnavailable(RuntimeError): pass
_ROOT = Path.home() / ".cache" / "careloop" / "voice"
_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"

class KokoroVoice:
    media_type = "audio/wav"
    def __init__(self, voice="af_heart", speed=1.0, models_dir: Path | None=None):
        self.voice, self.speed, self.models_dir, self.engine, self.lock = voice, speed, models_dir or _ROOT, None, threading.Lock()
    def _load(self):
        if self.engine is None:
            try:
                import espeakng_loader
                from kokoro_onnx import EspeakConfig, Kokoro
            except ImportError as exc: raise VoiceUnavailable("Kokoro is unavailable; run uv sync --extra voice") from exc
            self.models_dir.mkdir(parents=True, exist_ok=True); files=[]
            for name in ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin"):
                path=self.models_dir/name
                if not path.exists(): urllib.request.urlretrieve(_BASE+name, path)  # fixed HTTPS model source
                files.append(path)
            self.engine=Kokoro(str(files[0]),str(files[1]),espeak_config=EspeakConfig(data_path=str(espeakng_loader.get_data_path())))
        return self.engine
    def synthesize(self, text: str) -> bytes:
        samples, rate=self._load().create(text[:1000], voice=self.voice, speed=self.speed, lang="en-us")
        import numpy as np
        buf=io.BytesIO()
        with wave.open(buf,"wb") as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate);out.writeframes((np.clip(samples,-1,1)*32767).astype("<i2").tobytes())
        return buf.getvalue()

def apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def mlx_model_name(model: str) -> str:
    """A short size name ("small.en"), a Hugging Face repo, or a local path, as an MLX Whisper model."""
    if "/" in model or os.path.exists(model):
        return model
    return f"mlx-community/whisper-{model}-mlx"


def faster_model_name(model: str) -> str:
    """The faster-whisper name for a setting that may be written for MLX ("mlx-community/whisper-small.en-mlx")."""
    if model.startswith("mlx-community/whisper-"):
        name = model.removeprefix("mlx-community/whisper-")
        return name.removesuffix("-mlx")
    return model


class WhisperListener:
    """Local speech recognition that works on any system.

    Apple Silicon uses MLX Whisper. Every other system (Windows, Linux, Intel Macs) uses faster-whisper,
    on a CPU or an NVIDIA GPU. Both download their model on first use. ``WHISPER_BACKEND=mlx|faster``
    forces one. ``model`` may be a size name such as ``small.en`` (works on both) or a repo for one engine.
    """

    def __init__(self, model: str, prompt: str | None = None, backend: str | None = None) -> None:
        self.model, self.prompt, self.lock = model, prompt, threading.Lock()
        self.forced = (backend or os.environ.get("WHISPER_BACKEND", "")).strip().lower() or None
        self.backend: str | None = None
        self._engine = None

    def _order(self) -> list[str]:
        if self.forced in {"mlx", "faster"}:
            return [self.forced]
        return ["mlx", "faster"] if apple_silicon() else ["faster"]

    def _load(self):
        """Pick the first engine that is installed and load it once."""
        if self.backend is not None:
            return self._engine
        problems = []
        for name in self._order():
            try:
                if name == "mlx":
                    import mlx_whisper
                    self._engine, self.backend = mlx_whisper, "mlx"
                else:
                    from faster_whisper import WhisperModel
                    self._engine = WhisperModel(faster_model_name(self.model), device="auto", compute_type="auto")
                    self.backend = "faster"
                return self._engine
            except ImportError as exc:
                problems.append(f"{name}: {exc.name or exc}")
        raise VoiceUnavailable("Whisper is unavailable; run uv sync --extra voice (" + "; ".join(problems) + ")")

    def warm(self) -> str:
        """Load the engine and its model now, so the first spoken request is not slow. Returns the engine used."""
        import numpy as np
        with self.lock:
            self._load()
            self._run(np.zeros(16_000, dtype="float32"))
        return self.backend or ""

    def _run(self, audio) -> str:
        if self.backend == "mlx":
            result = self._engine.transcribe(audio, path_or_hf_repo=mlx_model_name(self.model), condition_on_previous_text=False,
                                             temperature=0.0, initial_prompt=self.prompt)
            return str(result.get("text", ""))
        segments, _info = self._engine.transcribe(audio, language="en", beam_size=1, temperature=0.0,
                                                  condition_on_previous_text=False, initial_prompt=self.prompt)
        return " ".join(segment.text for segment in segments)

    def transcribe(self, pcm: bytes, rate: int = 16000) -> str:
        import numpy as np
        audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768
        if len(audio) < 4000 or float(np.sqrt(np.mean(audio ** 2))) < .004:
            return ""
        # An optional initial prompt biases recognition toward demo vocabulary (wake word, names).
        with self.lock:
            self._load()
            return " ".join(self._run(audio).split())
