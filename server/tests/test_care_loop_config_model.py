"""The eval scripts take their default Ollama model from .env, else gemma4:e4b."""
import pytest

from care_loop import config
from care_loop.config import default_llm_model


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(config, "_load_dotenv", lambda: None)  # never read the developer's real .env
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("CARELOOP_INTAKE_MODEL", raising=False)


def test_falls_back_to_gemma4_e4b() -> None:
    assert default_llm_model() == "gemma4:e4b"
    assert default_llm_model(intake=True) == "gemma4:e4b"


def test_uses_the_model_named_in_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", " my-model:latest ")
    assert default_llm_model() == "my-model:latest"


def test_intake_prefers_its_own_setting_then_the_planner_model(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "planner:1")
    assert default_llm_model(intake=True) == "planner:1"
    monkeypatch.setenv("CARELOOP_INTAKE_MODEL", "reader:2")
    assert default_llm_model(intake=True) == "reader:2"
    assert default_llm_model() == "planner:1"  # the planner ignores the intake setting
