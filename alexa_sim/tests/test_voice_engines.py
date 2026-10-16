"""Local Whisper picks its engine by platform: MLX on Apple Silicon, faster-whisper everywhere else."""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from alexa_sim import local_voice
from alexa_sim.local_voice import VoiceUnavailable, WhisperListener, faster_model_name, mlx_model_name


def loud_pcm(seconds: float = 0.5) -> bytes:
    rng = np.random.default_rng(1)
    return (rng.uniform(-0.5, 0.5, int(16_000 * seconds)) * 32767).astype("<i2").tobytes()


class FakeFasterModule(types.ModuleType):
    """Stands in for faster_whisper so the test needs no download."""
    def __init__(self) -> None:
        super().__init__("faster_whisper")
        self.created: list[str] = []
        outer = self

        class WhisperModel:
            def __init__(self, name, device="auto", compute_type="default"):
                outer.created.append(name)

            def transcribe(self, audio, **kwargs):
                outer.last_kwargs = kwargs
                return iter([types.SimpleNamespace(text=" Alexa,"), types.SimpleNamespace(text=" show my tasks ")]), None

        self.WhisperModel = WhisperModel


@pytest.mark.parametrize("setting, mlx, faster", [
    ("small.en", "mlx-community/whisper-small.en-mlx", "small.en"),
    ("mlx-community/whisper-small.en-mlx", "mlx-community/whisper-small.en-mlx", "small.en"),
    ("mlx-community/whisper-large-v3-mlx", "mlx-community/whisper-large-v3-mlx", "large-v3"),
    ("Systran/faster-whisper-small.en", "Systran/faster-whisper-small.en", "Systran/faster-whisper-small.en"),
])
def test_one_model_setting_works_on_both_engines(setting, mlx, faster) -> None:
    assert mlx_model_name(setting) == mlx
    assert faster_model_name(setting) == faster


def test_engine_order_follows_the_platform(monkeypatch) -> None:
    monkeypatch.delenv("WHISPER_BACKEND", raising=False)
    monkeypatch.setattr(local_voice, "apple_silicon", lambda: True)
    assert WhisperListener("small.en")._order() == ["mlx", "faster"]
    monkeypatch.setattr(local_voice, "apple_silicon", lambda: False)
    assert WhisperListener("small.en")._order() == ["faster"]
    assert WhisperListener("small.en", backend="mlx")._order() == ["mlx"]
    monkeypatch.setenv("WHISPER_BACKEND", "faster")
    monkeypatch.setattr(local_voice, "apple_silicon", lambda: True)
    assert WhisperListener("small.en")._order() == ["faster"]


def test_windows_and_linux_use_faster_whisper_with_a_translated_model_name(monkeypatch) -> None:
    fake = FakeFasterModule()
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.delenv("WHISPER_BACKEND", raising=False)
    monkeypatch.setattr(local_voice, "apple_silicon", lambda: False)
    listener = WhisperListener("mlx-community/whisper-small.en-mlx", "Alexa, CareLoop")
    assert listener.transcribe(loud_pcm()) == "Alexa, show my tasks"
    assert listener.backend == "faster" and fake.created == ["small.en"]
    assert fake.last_kwargs["initial_prompt"] == "Alexa, CareLoop" and fake.last_kwargs["language"] == "en"
    assert listener.warm() == "faster" and fake.created == ["small.en"]  # the model is loaded once


def test_apple_silicon_falls_back_to_faster_whisper_when_mlx_is_missing(monkeypatch) -> None:
    fake = FakeFasterModule()
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)  # makes "import mlx_whisper" raise ImportError
    monkeypatch.delenv("WHISPER_BACKEND", raising=False)
    monkeypatch.setattr(local_voice, "apple_silicon", lambda: True)
    listener = WhisperListener("small.en")
    assert listener.transcribe(loud_pcm()).startswith("Alexa")
    assert listener.backend == "faster"


def test_no_engine_installed_is_reported_so_the_browser_can_take_over(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    monkeypatch.delenv("WHISPER_BACKEND", raising=False)
    with pytest.raises(VoiceUnavailable, match="uv sync --extra voice"):
        WhisperListener("small.en").transcribe(loud_pcm())


def test_silence_is_not_sent_to_any_engine(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # would raise if an engine were loaded
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    assert WhisperListener("small.en").transcribe(np.zeros(16_000, dtype="<i2").tobytes()) == ""
