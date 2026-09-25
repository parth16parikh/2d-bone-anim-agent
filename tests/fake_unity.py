"""An in-process stand-in for the MCP for Unity server, for tests that must not need Unity."""

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

READY = {
    "advice": {"ready_for_tools": True, "blocking_reasons": []},
    "unity": {"unity_version": "6000.4.0f1", "instance_id": "fake@1"},
    "editor": {"active_scene": {"name": "SampleScene"}},
}


class FakeUnity:
    """Records every call it receives, so tests can prove what did (not) reach Unity."""

    def __init__(self, tools: tuple[str, ...] | None = None):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.state: dict[str, Any] = json.loads(json.dumps(READY))
        self.not_ready_reads = 0  # the next N state reads say "compiling"
        self.reply: dict[str, Any] | None = None  # force every tool reply
        self.console: list[str] = []
        self.on_menu = None  # called when execute_menu_item runs (simulates the importer)
        self.menus: dict[str, Any] = {}  # menu path -> handler, tried before on_menu
        self.on_refresh = None  # called when refresh_unity runs (simulates a compile)
        self.server = MCPServer("fake-unity")
        self._register(set(tools) if tools else None)

    def _register(self, only: set[str] | None) -> None:
        server = self.server

        def on(name: str) -> bool:
            return only is None or name in only

        def answer(name: str, args: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((name, args))
            return self.reply if self.reply is not None else default

        if on("read_console"):

            @server.tool()
            def read_console(
                action: str = "get",
                types: list[str] | None = None,
                count: int = 10,
                format: str = "plain",
            ) -> dict:
                if action == "clear":
                    self.console.clear()
                return answer("read_console", {"action": action, "types": types, "count": count},
                              {"success": True, "data": list(self.console)})  # fmt: skip

        if on("execute_menu_item"):

            @server.tool()
            def execute_menu_item(menu_path: str) -> dict:
                reply = answer("execute_menu_item", {"menu_path": menu_path}, {"success": True})
                handler = self.menus.get(menu_path) or self.on_menu
                if handler and reply.get("success"):
                    handler()
                return reply

        if on("refresh_unity"):

            @server.tool()
            def refresh_unity(
                mode: str = "if_dirty",
                scope: str = "all",
                compile: str = "none",
                wait_for_ready: bool = False,
            ) -> dict:
                reply = answer(
                    "refresh_unity", {"mode": mode, "compile": compile}, {"success": True}
                )
                if self.on_refresh:
                    self.on_refresh()
                return reply

        if on("manage_scene"):

            @server.tool()
            def manage_scene(action: str) -> dict:
                return answer(
                    "manage_scene", {"action": action}, {"success": True, "data": {"items": []}}
                )

        if on("find_gameobjects"):

            @server.tool()
            def find_gameobjects(search_term: str, search_method: str = "by_name") -> dict:
                return answer(
                    "find_gameobjects",
                    {"search_term": search_term},
                    {"success": True, "data": {"ids": []}},
                )

        if on("delete_script"):

            @server.tool()
            def delete_script(path: str) -> dict:
                return answer("delete_script", {"path": path}, {"success": True})

        @server.resource("mcpforunity://editor/state")
        def editor_state() -> str:
            payload = json.loads(json.dumps(self.state))
            if self.not_ready_reads > 0:
                self.not_ready_reads -= 1
                payload["advice"] = {"ready_for_tools": False, "blocking_reasons": ["compiling"]}
            return json.dumps({"success": True, "data": payload})
