"""Regression test for the mounted Streamable HTTP MCP transport lifecycle."""
from fastapi.testclient import TestClient

from care_loop.server import create_app


def test_mcp_transport_initializes_when_mounted_under_the_private_portal() -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "careloop-test", "version": "1"},
        },
    }
    with TestClient(create_app(), base_url="http://127.0.0.1:8010") as client:
        response = client.post("/mcp", json=request, headers={
            "Authorization": "Bearer careloop-local-demo-token",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        })
    assert response.status_code == 200
    assert '"serverInfo"' in response.text and '"name":"careloop"' in response.text
