from __future__ import annotations
import uvicorn
from .app import create_alexa_sim_app
from .config import AlexaSimSettings

def main() -> None:
    settings = AlexaSimSettings.from_env()
    uvicorn.run(create_alexa_sim_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
