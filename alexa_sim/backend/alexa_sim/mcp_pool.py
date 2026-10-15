"""Account-scoped persistent Streamable HTTP MCP sessions.

Each linked account owns one long-lived worker task.  The MCP transport and
``ClientSession`` are entered *and* exited inside that task (anyio requires
cancel scopes to close in the task that opened them); requests reach the
session through a queue.  Results are normalized to plain JSON-shaped dicts so
the rest of the host never depends on SDK attribute spelling.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


Trace = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class Question:
    """An MCP elicitation the server asked mid-tool-call, waiting for the person's answer."""
    account_id: str
    message: str
    schema: dict[str, Any]
    answer: asyncio.Future  # resolves to {"action": ..., "content": {...}}

# Elicitation handler: (account_id, message, requested_schema) -> {"action", "content"}
ElicitHandler = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]


def _field(obj: Any, snake: str, camel: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(camel, obj.get(snake, default))
    value = getattr(obj, snake, None)
    if value is None:
        value = getattr(obj, camel, None)
    return default if value is None else value


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    return value


def normalize_tool(tool: Any) -> dict[str, Any]:
    return {
        "name": _field(tool, "name", "name", ""),
        "description": _field(tool, "description", "description", "") or "",
        "inputSchema": _dump(_field(tool, "input_schema", "inputSchema", {})) or {},
        "annotations": _dump(_field(tool, "annotations", "annotations", {})) or {},
        "_meta": _dump(_field(tool, "meta", "_meta", {})) or {},
    }


def normalize_result(result: Any) -> dict[str, Any]:
    content = [_dump(item) for item in (_field(result, "content", "content", []) or [])]
    text = " ".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
    structured = _dump(_field(result, "structured_content", "structuredContent"))
    return {
        "isError": bool(_field(result, "is_error", "isError", False)),
        "structuredContent": structured if isinstance(structured, dict) else None,
        "content": content,
        "text": text,
    }


def is_app_only(tool: dict[str, Any]) -> bool:
    visibility = ((tool.get("_meta") or {}).get("ui") or {}).get("visibility")
    return isinstance(visibility, list) and "model" not in visibility and "app" in visibility


class _SessionWorker:
    def __init__(self, url: str, token: str, elicit: Callable[[Any, Any], Awaitable[Any]] | None = None) -> None:
        self.url, self.token, self.elicit = url, token, elicit
        self.queue: asyncio.Queue = asyncio.Queue()
        self.ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        try:
            client = create_mcp_http_client(headers={"Authorization": f"Bearer {self.token}"})
            async with streamable_http_client(self.url, http_client=client) as streams:
                async with ClientSession(*streams, elicitation_callback=self.elicit) as session:
                    await session.initialize()
                    self.ready.set_result(True)
                    running: set[asyncio.Task] = set()
                    try:
                        while True:
                            item = await self.queue.get()
                            if item is None:
                                return
                            # Requests run concurrently on the one session, so a tool that is
                            # waiting on an elicitation answer never blocks other calls.
                            task = asyncio.create_task(self._serve(session, *item))
                            running.add(task)
                            task.add_done_callback(running.discard)
                    finally:
                        for task in running:
                            task.cancel()
        except BaseException as exc:
            if not self.ready.done():
                self.ready.set_exception(exc if isinstance(exc, Exception) else RuntimeError("MCP session stopped"))
            # Fail anything still queued so callers never hang.
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item and not item[1].done():
                    item[1].set_exception(RuntimeError("MCP session closed"))
            if not isinstance(exc, Exception):
                raise

    @staticmethod
    async def _serve(session: Any, operation: Callable[[Any], Awaitable[Any]], future: asyncio.Future) -> None:
        try:
            result = await operation(session)
            if not future.done():
                future.set_result(result)
        except Exception as exc:  # delivered to the caller, not swallowed
            if not future.done():
                future.set_exception(exc)
        except asyncio.CancelledError:
            if not future.done():
                future.set_exception(RuntimeError("MCP session closed"))
            raise

    async def run(self, operation: Callable[[Any], Awaitable[Any]]) -> Any:
        if self.task.done():
            raise RuntimeError("MCP session closed")
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((operation, future))
        return await future

    async def close(self) -> None:
        if not self.task.done():
            await self.queue.put(None)
        try:
            await asyncio.wait_for(self.task, timeout=5)
        except (Exception, asyncio.TimeoutError):
            self.task.cancel()


@dataclass
class AccountSession:
    account_id: str
    worker: Any
    tools: list[dict[str, Any]] = field(default_factory=list)

    @property
    def model_tools(self) -> list[dict[str, Any]]:
        """Tools the assistant model may see: MCP Apps app-only tools are hidden."""
        return [tool for tool in self.tools if not is_app_only(tool)]


class MCPClientPool:
    """A session is initialized once and reused until the account unlinks."""

    def __init__(self, url: str, trace: Trace | None = None, *, elicit_timeout: float = 120.0) -> None:
        self.url, self.trace, self.elicit_timeout = url, trace, elicit_timeout
        self.accounts: dict[str, AccountSession] = {}
        # Questions the server asked, per account, for the turn loop to put to the person.
        self.questions: dict[str, asyncio.Queue[Question]] = {}

    def linked(self, account_id: str | None) -> bool:
        return account_id in self.accounts

    async def link(self, account_id: str, token: str) -> AccountSession:
        if account_id in self.accounts:
            return self.accounts[account_id]
        await self._log({"direction": "out", "method": "initialize", "account": account_id})
        self.questions[account_id] = asyncio.Queue()
        worker = _SessionWorker(self.url, token, self._elicitation_callback(account_id))
        try:
            await worker.ready
        except Exception:
            await worker.close()
            raise
        account = AccountSession(account_id, worker)
        self.accounts[account_id] = account
        await self.refresh_tools(account_id)
        return account

    def _elicitation_callback(self, account_id: str):
        from mcp import types

        async def callback(_context: Any, params: Any) -> Any:
            message = str(_field(params, "message", "message", ""))
            schema = _dump(_field(params, "requested_schema", "requestedSchema", {})) or {}
            if not schema:  # URL-mode elicitation is not part of this voice demo
                return types.ElicitResult(action="decline")
            await self._log({"direction": "in", "method": "elicitation/create", "account": account_id, "message": message})
            question = Question(account_id, message, schema, asyncio.get_running_loop().create_future())
            await self.questions[account_id].put(question)
            try:
                answer = await asyncio.wait_for(question.answer, timeout=self.elicit_timeout)
            except asyncio.TimeoutError:
                answer = {"action": "cancel"}
            await self._log({"direction": "out", "method": "elicitation/create", "account": account_id,
                             "action": answer.get("action")})
            return types.ElicitResult(action=answer["action"], content=answer.get("content"))
        return callback

    async def unlink(self, account_id: str) -> None:
        self.questions.pop(account_id, None)
        account = self.accounts.pop(account_id, None)
        if account:
            await account.worker.close()

    async def close(self) -> None:
        for account_id in list(self.accounts):
            await self.unlink(account_id)

    async def refresh_tools(self, account_id: str) -> list[dict[str, Any]]:
        account = self.accounts[account_id]
        await self._log({"direction": "out", "method": "tools/list", "account": account_id})
        response = await account.worker.run(lambda session: session.list_tools())
        account.tools = [normalize_tool(tool) for tool in _field(response, "tools", "tools", [])]
        await self._log({"direction": "in", "method": "tools/list", "account": account_id,
                         "tools": [tool["name"] for tool in account.tools]})
        return account.tools

    async def call_tool(self, account_id: str, name: str, arguments: dict[str, Any], *, source: str = "model") -> dict[str, Any]:
        account = self.accounts[account_id]
        await self._log({"direction": "out", "method": "tools/call", "account": account_id, "source": source,
                         "name": name, "arguments": arguments})
        result = normalize_result(await account.worker.run(lambda session: session.call_tool(name, arguments)))
        logged = {"isError": result["isError"]}
        # App-only data is private detail; the inspector shows that it flowed, not what it was.
        logged |= {"structuredContent": result["structuredContent"]} if source == "model" else {"redacted": True}
        await self._log({"direction": "in", "method": "tools/call", "account": account_id, "name": name, "result": logged})
        return result

    async def read_resource(self, account_id: str, uri: str) -> str:
        account = self.accounts[account_id]
        await self._log({"direction": "out", "method": "resources/read", "account": account_id, "uri": uri})
        response = await account.worker.run(lambda session: session.read_resource(uri))
        contents = _field(response, "contents", "contents", []) or []
        html = str(_field(contents[0], "text", "text", "")) if contents else ""
        await self._log({"direction": "in", "method": "resources/read", "account": account_id, "uri": uri, "bytes": len(html)})
        return html

    async def _log(self, entry: dict[str, Any]) -> None:
        if self.trace:
            await self.trace(entry)
