from fastapi.testclient import TestClient
from care_sim.voice_app import create_voice_app
from care_sim.voice_agent import CareLoopVoiceAgent, OllamaIntentRouter
from care_sim.voice_config import VoiceSimSettings
class DummyHub:
    started=True
    def start(self): return self
    def stop(self): self.started=False
    def call(self,*_): return {"ok":True,"data":{},"message":"ok"}

class TasksHub(DummyHub):
    def call(self,*_):
        return {"ok":True,"data":{"speakable":"You have 2 approved CareLoop tasks."},"message":"ok"}

class ObservationHub(DummyHub):
    def __init__(self): self.calls=[]
    def call(self,name,args):
        self.calls.append((name,args))
        return {"ok":True,"data":{"speakable":"Check-in recorded."},"message":"ok"}

class DirectRouter:
    def __init__(self, intent="tasks"): self.intent=intent; self.facts=[]
    def classify(self,_text): return self.intent
    def speak(self,_request,facts): self.facts.append(facts); return "Ollama wording: " + facts

def test_config_defaults_are_local_and_safe(monkeypatch):
    monkeypatch.setenv("CARELOOP_AGENT_LLM", "ollama")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    settings=VoiceSimSettings.from_env()
    assert settings.llm=="ollama" and settings.careloop_mcp_url.endswith("/mcp")

def test_config_honors_environment_overrides(monkeypatch):
    monkeypatch.setenv("CARELOOP_AGENT_LLM", "ollama")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    assert VoiceSimSettings.from_env().llm == "ollama"

def test_ollama_router_only_returns_an_allowed_intent():
    captured=[]
    def post(_url,body):
        captured.append(body)
        return b'{"message":{"content":"{\\"intent\\":\\"tasks\\"}"}}'
    settings=VoiceSimSettings(llm="ollama",llm_model="qwen3.5:4b-mlx")
    assert OllamaIntentRouter(settings,post=post).classify("What should I do today?")=="tasks"
    request=__import__("json").loads(captured[0])
    assert request["think"] is False and request["options"]["num_predict"]==24

def test_ollama_router_fails_closed_for_invalid_model_output():
    settings=VoiceSimSettings(llm="ollama",llm_model="qwen3.5:4b-mlx")
    assert OllamaIntentRouter(settings,post=lambda _url,_body:b'{"message":{"content":"{\\"intent\\":\\"diagnose\\"}"}}').classify("Diagnose me")=="unsupported"

def test_ollama_speaks_the_complete_model_response_without_truncating():
    spoken = "Your approved tasks are Take a short walk and complete the evening check-in."
    settings=VoiceSimSettings(llm="ollama",llm_model="qwen3.5:4b-mlx",llm_max_tokens=512)
    router=OllamaIntentRouter(settings,post=lambda _url,_body:('{"message":{"content":' + __import__("json").dumps(spoken) + '}}').encode())
    assert router.speak("show my tasks", "Two approved tasks are available.") == spoken

def test_ollama_agent_uses_the_model_spoken_response():
    class SpokenRouter:
        def classify(self,_text): return "tasks"
        def speak(self,_request,_safe_response): return "This is the complete model response."
    settings=VoiceSimSettings(llm="ollama",llm_model="qwen3.5:4b-mlx",llm_max_tokens=512)
    turn=CareLoopVoiceAgent(TasksHub(),settings,router=SpokenRouter()).respond("show my tasks")
    assert turn.reply == "This is the complete model response."

def test_ollama_greeting_uses_the_model_but_not_mcp():
    settings=VoiceSimSettings(llm="ollama",llm_model="qwen3.5:4b-mlx")
    router=DirectRouter()
    turn=CareLoopVoiceAgent(DummyHub(),settings,router=router).respond("hello")
    assert turn.reply.startswith("Ollama wording:") and router.facts and not turn.tools

def test_ollama_failure_becomes_a_safe_spoken_turn():
    class BrokenRouter:
        def classify(self,_text): raise TimeoutError("Ollama warming up")
    settings=VoiceSimSettings(llm="ollama",llm_model="qwen3.5:4b-mlx")
    turn=CareLoopVoiceAgent(DummyHub(),settings,router=BrokenRouter()).respond("what should I do today")
    assert "local voice model" in turn.reply and not turn.tools

def test_task_response_renders_mcp_task_results():
    router=DirectRouter()
    turn=CareLoopVoiceAgent(TasksHub(),VoiceSimSettings(llm="ollama",llm_model="local"),router=router).respond("show my tasks")
    assert turn.reply == "Ollama wording: You have 2 approved CareLoop tasks."

def test_empty_task_response_explains_how_to_continue():
    router=DirectRouter()
    turn=CareLoopVoiceAgent(DummyHub(),VoiceSimSettings(llm="ollama",llm_model="local"),router=router).respond("show my tasks")
    assert "safe task summary" in turn.reply

def test_supported_prompts_have_useful_next_steps():
    plan=CareLoopVoiceAgent(DummyHub(),VoiceSimSettings(llm="ollama",llm_model="local"),router=DirectRouter("handoff"))._plan("create a handoff")
    assert "start and end date" in plan.reply

def test_natural_pain_score_is_captured_and_sent_to_the_mcp_tool():
    hub=ObservationHub()
    turn=CareLoopVoiceAgent(hub,VoiceSimSettings(llm="ollama",llm_model="local"),router=DirectRouter()).respond("record the pain score as 8 out of 10", "maya")
    assert hub.calls[0][0]=="record_pain_observation"
    assert hub.calls[0][1]["pain_score"]==8
    assert hub.calls[0][1]["idempotency_key"].startswith("voice-maya-")
    assert turn.reply=="Ollama wording: Check-in recorded."

def test_natural_pain_score_bypasses_ollama_intent_classification():
    class Router:
        def classify(self,_): raise AssertionError("numeric score must be parsed before model routing")
        def speak(self,_request,facts): return facts
    hub=ObservationHub()
    turn=CareLoopVoiceAgent(hub,VoiceSimSettings(llm="ollama",llm_model="local"),router=Router()).respond("pain is eight out of ten")
    assert "recorded" in turn.reply.lower()

def test_app_has_private_generic_caregiver_reply(monkeypatch):
    class Agent:
        def __init__(self,*_): pass
        def respond(self,*_): return type("Turn",(),{"reply":"CareLoop update completed.","tools":[]})()
    monkeypatch.setattr("care_sim.voice_app.CareLoopVoiceAgent",Agent)
    app=create_voice_app(VoiceSimSettings(),hub=DummyHub())
    with TestClient(app) as client:
        assert client.get("/api/config").status_code==200
        out=client.post("/api/chat",json={"persona":"caregiver","text":"show my tasks"}).json()
    assert "No private care details" in out["reply"]

def test_streamed_reply_emits_progressive_events(monkeypatch):
    class Agent:
        def __init__(self,*_): pass
        def respond(self,*_): return type("Turn",(),{"reply":"Ollama response from approved facts.","tools":[]})()
    monkeypatch.setattr("care_sim.voice_app.CareLoopVoiceAgent",Agent)
    app=create_voice_app(VoiceSimSettings(),hub=DummyHub())
    with TestClient(app) as client:
        result=client.post("/api/chat/stream",json={"persona":"patient","text":"show my tasks"})
    assert result.status_code==200
    assert "assistant_delta" in result.text and "Ollama response" in result.text

def test_voice_code_has_no_legacy_project_refs():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    text="\n".join(p.read_text() for p in root.rglob("voice_*.py"))
    assert ("Family" + " Hub") not in text and ("family" + "_hub") not in text
