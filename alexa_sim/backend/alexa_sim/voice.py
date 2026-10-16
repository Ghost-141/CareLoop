"""Local speech for the simulator: Kokoro TTS and Whisper STT (MLX or faster-whisper), with browser fallback.

Models load in a background thread at startup so the first spoken reply is not slow.
The browser falls back to its own speech engines whenever these report unavailable.
"""
from __future__ import annotations

import threading
from typing import Any

from .config import AlexaSimSettings

WHISPER_PROMPT = "Alexa, CareLoop, check-in, care plan, Maya, Sam, caregiver, handoff, appointment, pain score."


class VoiceEngines:
    def __init__(self, settings: AlexaSimSettings) -> None:
        self.settings = settings
        self.tts: Any = None
        self.stt: Any = None
        self.status = {"tts": "browser", "stt": "browser"}
        self.errors: dict[str, str] = {}
        self.engine_name = ""
        try:
            from .local_voice import KokoroVoice, WhisperListener
        except ImportError:
            return
        if settings.voice == "kokoro":
            self.tts = KokoroVoice(settings.kokoro_voice, settings.kokoro_speed, settings.voice_models_dir)
            self.status["tts"] = "loading"
        if settings.stt == "whisper":
            self.stt = WhisperListener(settings.whisper_model, WHISPER_PROMPT)
            self.status["stt"] = "loading"

    def warm_in_background(self) -> None:
        if self.tts is not None or self.stt is not None:
            threading.Thread(target=self._warm, name="voice-warmup", daemon=True).start()

    def _warm(self) -> None:
        if self.tts is not None:
            try:
                self.tts.synthesize("Ready.")
                self.status["tts"] = "kokoro"
            except Exception as exc:  # missing extra, download failure, etc.
                self.tts, self.status["tts"], self.errors["tts"] = None, "browser", type(exc).__name__
        if self.stt is not None:
            try:
                self.engine_name = self.stt.warm()  # "mlx" or "faster", whichever this system can run
                self.status["stt"] = "whisper"
            except Exception as exc:
                self.stt, self.status["stt"], self.errors["stt"] = None, "browser", type(exc).__name__

    def describe(self) -> dict[str, Any]:
        return {**self.status, "errors": self.errors, "kokoro_voice": self.settings.kokoro_voice,
                "whisper_model": self.settings.whisper_model if self.stt is not None else None,
                "whisper_engine": self.engine_name or None}
