from __future__ import annotations
import uvicorn
from .voice_app import create_voice_app
from .voice_config import VoiceSimSettings
def main():
    settings=VoiceSimSettings.from_env();uvicorn.run(create_voice_app(settings),host=settings.sim_host,port=settings.sim_port)
if __name__=="__main__":main()
