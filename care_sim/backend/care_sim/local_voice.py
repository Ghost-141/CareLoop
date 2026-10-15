"""Optional local Kokoro TTS and MLX Whisper STT; browser speech is always the fallback."""
from __future__ import annotations
import io, os, threading, urllib.request, wave
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

class WhisperListener:
    def __init__(self, model: str, prompt: str | None=None): self.model=model;self.prompt=prompt;self.lock=threading.Lock()
    def transcribe(self, pcm: bytes, rate: int=16000) -> str:
        try: import mlx_whisper; import numpy as np
        except ImportError as exc: raise VoiceUnavailable("Whisper is unavailable; run uv sync --extra voice on Apple Silicon") from exc
        audio=np.frombuffer(pcm,dtype="<i2").astype("float32")/32768
        if len(audio)<4000 or float(np.sqrt(np.mean(audio**2)))<.004:return ""
        # An optional initial prompt biases recognition toward demo vocabulary (wake word, names).
        with self.lock: result=mlx_whisper.transcribe(audio,path_or_hf_repo=self.model,condition_on_previous_text=False,temperature=0.0,initial_prompt=self.prompt)
        return " ".join(str(result.get("text","")).split())
