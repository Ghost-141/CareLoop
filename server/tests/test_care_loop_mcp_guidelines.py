"""MCP guideline checks: deployment guard, Host/Origin allowlist, tool titles, 2026-07-28 request envelope."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from care_loop.auth import LOCAL_CAREGIVER_TOKEN, LOCAL_DEMO_TOKEN
from care_loop.config import Settings
from care_loop.server import UnsafeDeploymentError, build_deps, check_deployment, create_app

HEADERS = {
    "Authorization": f"Bearer {LOCAL_DEMO_TOKEN}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "careloop-test", "version": "1"}}}
MODERN_META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
               "io.modelcontextprotocol/clientInfo": {"name": "careloop-test", "version": "1"},
               "io.modelcontextprotocol/clientCapabilities": {}}


def settings(tmp_path, **env) -> Settings:
    return Settings.from_env({"CARELOOP_DB_PATH": str(tmp_path / "t.db"), **env})


def rpc(client, method, params=None, id=1, headers=None):
    body = {"jsonrpc": "2.0", "id": id, "method": method, "params": {**(params or {}), "_meta": MODERN_META}}
    h = {**HEADERS, "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method, **(headers or {})}
    if method == "tools/call":
        h["Mcp-Name"] = params["name"]
    return client.post("/mcp", json=body, headers=h)


def payload(response):
    text = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        text = "".join(re.findall(r"^data: (.*)$", text, re.M))
    return json.loads(text)


# ---- 1. demo tokens are refused off loopback --------------------------------

def test_loopback_with_demo_tokens_starts(tmp_path) -> None:
    check_deployment(settings(tmp_path))


@pytest.mark.parametrize("env", [
    {"CARELOOP_HOST": "0.0.0.0"},
    {"CARELOOP_HOST": "0.0.0.0", "CARELOOP_API_TOKEN": "private-patient-token",
     "CARELOOP_CAREGIVER_TOKEN": LOCAL_CAREGIVER_TOKEN},  # a private patient token does not hide the demo caregiver one
])
def test_public_host_with_demo_tokens_is_refused(tmp_path, env) -> None:
    with pytest.raises(UnsafeDeploymentError, match="CARELOOP_API_TOKEN"):
        check_deployment(settings(tmp_path, **env))


def test_public_host_with_private_tokens_starts(tmp_path) -> None:
    check_deployment(settings(tmp_path, CARELOOP_HOST="0.0.0.0", CARELOOP_API_TOKEN="a-private-token",
                              CARELOOP_CAREGIVER_TOKEN="another-private-token"))


def test_explicit_opt_in_allows_demo_tokens_on_a_local_network(tmp_path) -> None:
    check_deployment(settings(tmp_path, CARELOOP_HOST="0.0.0.0", CARELOOP_ALLOW_DEMO_TOKENS="true"))


def test_create_app_applies_the_guard(tmp_path) -> None:
    deps = build_deps(settings(tmp_path, CARELOOP_HOST="0.0.0.0"))
    with pytest.raises(UnsafeDeploymentError):
        create_app(deps)


# ---- 2. Host and Origin allowlist -------------------------------------------

def app_for(tmp_path, **env):
    env = {"CARELOOP_HOST": "0.0.0.0", "CARELOOP_API_TOKEN": "a-private-token",
           "CARELOOP_CAREGIVER_TOKEN": "another-private-token", **env}
    return create_app(build_deps(settings(tmp_path, **env)))


def test_allowlisted_tunnel_host_is_accepted_even_when_bound_to_all_interfaces(tmp_path) -> None:
    app = app_for(tmp_path, CARELOOP_ALLOWED_HOSTS="demo.example.test")
    with TestClient(app, base_url="http://demo.example.test") as client:
        r = client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer a-private-token"})
    assert r.status_code == 200, r.text


def test_unknown_host_is_rejected_even_when_bound_to_all_interfaces(tmp_path) -> None:
    with TestClient(app_for(tmp_path), base_url="http://evil.example.test") as client:
        r = client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer a-private-token"})
    assert r.status_code in (400, 421), r.text


def test_foreign_browser_origin_is_rejected(tmp_path) -> None:
    with TestClient(create_app(build_deps(settings(tmp_path))), base_url="http://127.0.0.1:8010") as client:
        r = client.post("/mcp", json=INIT, headers={**HEADERS, "Origin": "https://evil.example.test"})
    assert r.status_code in (400, 403), r.text


def test_local_origin_is_accepted(tmp_path) -> None:
    with TestClient(create_app(build_deps(settings(tmp_path))), base_url="http://127.0.0.1:8010") as client:
        r = client.post("/mcp", json=INIT, headers={**HEADERS, "Origin": "http://localhost:3000"})
    assert r.status_code == 200, r.text


# ---- 2026-07-28 request envelope (items 3 and 5) -----------------------------

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(build_deps(settings(tmp_path))), base_url="http://127.0.0.1:8010") as c:
        yield c


def test_server_discover_under_2026_07_28(client) -> None:
    r = rpc(client, "server/discover")
    assert r.status_code == 200, r.text
    result = payload(r)["result"]
    assert "2026-07-28" in result["supportedVersions"]
    assert "tools" in result["capabilities"]
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "careloop"


def test_every_tool_has_a_title_and_annotations(client) -> None:
    result = payload(rpc(client, "tools/list"))["result"]
    tools = result["tools"]
    assert len(tools) == 30
    for tool in tools:
        assert tool.get("title", "").strip(), tool["name"]
        assert tool.get("annotations", {}).get("readOnlyHint") is not None, tool["name"]
    assert len({t["title"] for t in tools}) == len(tools)


def test_tool_call_under_2026_07_28(client) -> None:
    r = rpc(client, "tools/call", {"name": "list_care_tasks", "arguments": {}})
    assert r.status_code == 200, r.text
    body = payload(r)
    assert "error" not in body, body
    assert "speakable" in json.dumps(body["result"])


def test_elicitation_tools_fail_cleanly_under_2026_07_28_known_limit(client) -> None:
    """Friction log F-28: ctx.elicit() needs a server-to-client request, which the stateless revision removed.

    The tool must fail with the generic error and record nothing. When the tools move to the input-required
    pattern, replace this test with one that completes a check-in.
    """
    meta = {**MODERN_META, "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}}}
    assert "error" not in payload(rpc(client, "tools/call", {"name": "accept_data_use", "arguments": {}}))  # consent first
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "start_daily_checkin", "arguments": {}, "_meta": meta}}
    r = client.post("/mcp", json=body, headers={**HEADERS, "MCP-Protocol-Version": "2026-07-28",
                                               "Mcp-Method": "tools/call", "Mcp-Name": "start_daily_checkin"})
    result = payload(r)["result"]
    assert result["isError"] is True
    assert "Nothing was recorded" in json.dumps(result)
