"""Unity MCP client with a hard action allowlist (LLD 3.11b, 3.8.2).

The Python agent talks to the MCP for Unity server over HTTP. Only a few read-only tools and
three menu items (import, import all, save prefabs) can be called; everything else is refused
before it leaves this process, so a bug or a bad plan can never delete scripts or assets or touch
objects outside RigAgent_Output. Prefabs are the one thing written elsewhere, and only into the
folder the user chose.
"""

import asyncio
import json
from collections.abc import Coroutine, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self, TypeVar

from mcp import Client

from rig_agent.config import settings
from rig_agent.unity.contract import (
    IMPORT_ALL_MENU,
    IMPORT_ANIMATION_MENU,
    IMPORT_MENU,
    SAVE_PREFABS_MENU,
)

T = TypeVar("T")

ALLOWED_MENU_ITEMS = frozenset(
    {IMPORT_MENU, IMPORT_ALL_MENU, SAVE_PREFABS_MENU, IMPORT_ANIMATION_MENU}
)
# tool name -> the argument names it may be called with
ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    "execute_menu_item": frozenset({"menu_path"}),
    "read_console": frozenset({"action", "types", "count", "filter_text", "format"}),
    "refresh_unity": frozenset({"mode", "scope", "compile", "wait_for_ready"}),
    "manage_scene": frozenset({"action", "max_depth", "max_nodes", "include_transform"}),
    "find_gameobjects": frozenset({"search_term", "search_method", "page_size"}),
}
SCENE_READ_ACTIONS = frozenset({"get_hierarchy", "get_active", "get_loaded_scenes"})
CONSOLE_ACTIONS = frozenset({"get", "clear"})
STATE_URI = "mcpforunity://editor/state"


class UnityMcpError(RuntimeError):
    """Talking to Unity failed, or Unity reported an error."""


class UnityUnavailable(UnityMcpError):
    """The MCP server cannot be reached. The JSON is still delivered (LLD 3.13)."""


class ActionNotAllowed(UnityMcpError):
    """The call is outside the allowlist and was refused before being sent."""


def check_allowed(tool: str, arguments: dict[str, Any] | None = None) -> None:
    """Raise ActionNotAllowed unless this exact call is on the allowlist."""
    args = arguments or {}
    if tool not in ALLOWED_TOOLS:
        raise ActionNotAllowed(f"the Unity tool '{tool}' is not on the allowlist")
    extra = set(args) - ALLOWED_TOOLS[tool]
    if extra:
        raise ActionNotAllowed(f"'{tool}' may not be called with {sorted(extra)}")
    if tool == "execute_menu_item" and args.get("menu_path") not in ALLOWED_MENU_ITEMS:
        raise ActionNotAllowed(f"the menu item '{args.get('menu_path')}' is not on the allowlist")
    if tool == "manage_scene" and args.get("action") not in SCENE_READ_ACTIONS:
        raise ActionNotAllowed(f"manage_scene may only read: {sorted(SCENE_READ_ACTIONS)}")
    if tool == "read_console" and args.get("action", "get") not in CONSOLE_ACTIONS:
        raise ActionNotAllowed(f"read_console may only use {sorted(CONSOLE_ACTIONS)}")


def _leaves(error: BaseException) -> Iterable[BaseException]:
    """The real exceptions inside (possibly nested) exception groups."""
    if isinstance(error, BaseExceptionGroup):
        for inner in error.exceptions:
            yield from _leaves(inner)
    else:
        yield error


_CONNECT_FAILURES = {"ConnectError", "ConnectTimeout", "ConnectionError", "OSError"}


def _is_connect_failure(error: BaseException) -> bool:
    """True for 'nothing is listening' style failures. The MCP SDK ships its own httpx fork
    (httpx2), so this checks the class names rather than importing either httpx."""
    return any(cls.__name__ in _CONNECT_FAILURES for cls in type(error).__mro__)


def _translate(error: BaseException, url: str) -> UnityMcpError:
    leaves = list(_leaves(error))
    for leaf in leaves:
        if isinstance(leaf, UnityMcpError):
            return leaf
    for leaf in leaves:
        if _is_connect_failure(leaf):
            return UnityUnavailable(
                f"cannot reach the Unity MCP server at {url}. Is Unity open with the MCP for "
                f"Unity server started? ({leaf})"
            )
    if any(isinstance(leaf, TimeoutError | asyncio.TimeoutError) for leaf in leaves):
        return UnityMcpError(f"the Unity MCP server at {url} did not answer in time")
    return UnityMcpError("; ".join(str(leaf) or type(leaf).__name__ for leaf in leaves))


@contextmanager
def _translated(url: str) -> Iterator[None]:
    """Turn any transport failure (often an exception group) into a UnityMcpError."""
    try:
        yield
    except UnityMcpError:
        raise
    except Exception as error:  # noqa: BLE001 - every failure here is reported as a UnityMcpError
        raise _translate(error, url) from None


def _parse(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"success": True, "message": text}
    return data if isinstance(data, dict) else {"success": True, "data": data}


class UnityMcpClient:
    """An async client. `target` is the MCP URL, or an in-process MCPServer for tests."""

    def __init__(self, target: Any = None, *, timeout: float | None = None):
        self.target = target if target is not None else settings.unity_mcp_url
        self.timeout = timeout if timeout is not None else settings.unity_timeout
        self._client: Client | None = None

    @property
    def url(self) -> str:
        return self.target if isinstance(self.target, str) else "the in-process server"

    async def __aenter__(self) -> Self:
        client = Client(self.target, read_timeout_seconds=self.timeout)
        with _translated(self.url):
            await client.__aenter__()
        self._client = client
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        client, self._client = self._client, None
        if client is not None:
            if exc_type is None:
                with _translated(self.url):
                    await client.__aexit__(exc_type, exc, tb)
            else:  # already failing: do not let a cleanup error hide the original one
                try:
                    await client.__aexit__(exc_type, exc, tb)
                except Exception:  # noqa: BLE001, S110
                    pass

    def _connected(self) -> Client:
        if self._client is None:
            raise UnityMcpError("the client is not connected; use it as `async with`")
        return self._client

    @property
    def server_name(self) -> str:
        info = getattr(self._connected(), "server_info", None)
        return f"{info.name} {info.version}".strip() if info else ""

    async def list_tools(self) -> list[str]:
        with _translated(self.url):
            return [t.name for t in (await self._connected().list_tools()).tools]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call an allowlisted tool and return its parsed JSON reply."""
        check_allowed(name, arguments)
        with _translated(self.url):
            result = await self._connected().call_tool(name, arguments or {})
        text = "".join(getattr(part, "text", "") for part in result.content)
        data = _parse(text)
        if result.is_error or data.get("success") is False:
            raise UnityMcpError(
                f"{name} failed: {data.get('error') or data.get('message') or text}"
            )
        return data

    async def read_resource(self, uri: str) -> dict[str, Any]:
        if not uri.startswith("mcpforunity://"):
            raise ActionNotAllowed(f"only mcpforunity:// resources can be read, not '{uri}'")
        with _translated(self.url):
            result = await self._connected().read_resource(uri)
        return _parse("".join(getattr(part, "text", "") for part in result.contents))

    async def editor_state(self) -> dict[str, Any]:
        # while Unity recompiles the reply can carry "data": null; that just means "not ready"
        return (await self.read_resource(STATE_URI)).get("data") or {}

    async def wait_until_ready(self, timeout: float = 60.0, poll: float = 0.5) -> dict[str, Any]:
        """Wait until Unity says tools can be used (not compiling, no domain reload)."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            state = await self.editor_state()
            advice = state.get("advice") or {}
            if advice.get("ready_for_tools"):
                return state
            if asyncio.get_running_loop().time() >= deadline:
                reasons = advice.get("blocking_reasons") or ["unknown"]
                raise UnityMcpError(f"Unity was not ready after {timeout:.0f}s: {reasons}")
            await asyncio.sleep(poll)

    async def console_messages(self, types: list[str], count: int = 50) -> list[str]:
        data = await self.call_tool(
            "read_console", {"action": "get", "types": types, "count": count, "format": "plain"}
        )
        items = data.get("data") or []
        return [item if isinstance(item, str) else json.dumps(item) for item in items]

    async def clear_console(self) -> None:
        await self.call_tool("read_console", {"action": "clear"})


def run_sync(coroutine: Coroutine[Any, Any, T]) -> T:
    """Run an async call from ordinary synchronous code."""
    return asyncio.run(coroutine)


NEEDED_TOOLS = tuple(ALLOWED_TOOLS)


@dataclass
class UnityStatus:
    url: str
    server: str = ""
    unity_version: str = ""
    instance: str = ""
    scene: str = ""
    ready: bool = False
    blocking: list[str] = field(default_factory=list)
    tool_count: int = 0
    missing_tools: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ready and not self.missing_tools


async def _check(target: Any) -> UnityStatus:
    async with UnityMcpClient(target) as client:
        tools = await client.list_tools()
        state = await client.editor_state()
        unity = state.get("unity", {})
        advice = state.get("advice", {})
        scene = state.get("editor", {}).get("active_scene", {})
        return UnityStatus(
            url=client.url,
            server=client.server_name,
            unity_version=unity.get("unity_version", ""),
            instance=unity.get("instance_id", ""),
            scene=scene.get("name", ""),
            ready=bool(advice.get("ready_for_tools")),
            blocking=list(advice.get("blocking_reasons") or []),
            tool_count=len(tools),
            missing_tools=[t for t in NEEDED_TOOLS if t not in tools],
        )


def check_unity(target: Any = None) -> UnityStatus:
    """Connect, and report what Unity offers. Raises UnityUnavailable if nothing answers."""
    return run_sync(_check(target if target is not None else settings.unity_mcp_url))
