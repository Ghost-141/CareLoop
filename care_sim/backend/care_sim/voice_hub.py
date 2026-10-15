"""MCP connection for the simulator. The bearer token is never sent to the browser."""
from __future__ import annotations
import asyncio
from typing import Any
from .voice_config import VoiceSimSettings
class CareLoopMCP:
    def __init__(self, settings: VoiceSimSettings): self.settings=settings; self.client=None; self.started=False
    def start(self):
        # The official MCP client is part of CareLoop's base dependency. Providers
        # (Strands/Ollama/OpenAI) are an optional planning layer, not the transport.
        self.started=True; return self
    def stop(self):
        self.started=False
    def call(self,name:str,args:dict[str,Any])->dict[str,Any]:
        if not self.started:self.start()
        return asyncio.run(self._call(name,args))
    async def _call(self,name:str,args:dict[str,Any])->dict[str,Any]:
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        client=create_mcp_http_client(headers={"Authorization":f"Bearer {self.settings.api_token}"})
        async with streamable_http_client(self.settings.careloop_mcp_url,http_client=client) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize(); result=await session.call_tool(name,args)
        data=getattr(result,"structuredContent",None) or {}; content=getattr(result,"content",[]) or []
        text=" ".join(getattr(x,"text","") for x in content)
        ok=not bool(getattr(result,"isError",False))
        return {"ok":ok,"data":data if ok else {},"message":data.get("message",text) if isinstance(data,dict) else text}
