import pytest

from fake_unity import FakeUnity
from rig_agent.unity.contract import IMPORT_MENU
from rig_agent.unity.mcp_client import (
    ALLOWED_TOOLS,
    ActionNotAllowed,
    UnityMcpClient,
    UnityMcpError,
    UnityUnavailable,
    check_allowed,
    check_unity,
)

# ---- the allowlist -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("execute_menu_item", {"menu_path": IMPORT_MENU}),
        ("read_console", {"action": "get", "types": ["error"], "count": 5}),
        ("read_console", {}),
        ("read_console", {"action": "clear"}),
        (
            "refresh_unity",
            {"mode": "force", "scope": "all", "compile": "request", "wait_for_ready": True},
        ),
        ("manage_scene", {"action": "get_hierarchy", "max_depth": 3}),
        ("manage_scene", {"action": "get_active"}),
        ("find_gameobjects", {"search_term": "RigAgent_Output", "search_method": "by_name"}),
    ],
)
def test_allowed_calls_pass(tool, args):
    check_allowed(tool, args)


@pytest.mark.parametrize(
    "tool",
    [
        "delete_script", "create_script", "manage_asset", "manage_gameobject", "execute_code",
        "manage_prefabs", "apply_text_edits", "script_apply_edits", "manage_editor", "manage_packages",
        "execute_custom_tool", "batch_execute", "manage_components", "generate_image",
    ],
)  # fmt: skip
def test_every_other_unity_tool_is_refused(tool):
    with pytest.raises(ActionNotAllowed, match="not on the allowlist"):
        check_allowed(tool, {})


def test_only_the_import_menu_item_may_run():
    with pytest.raises(ActionNotAllowed, match="Assets/Delete"):
        check_allowed("execute_menu_item", {"menu_path": "Assets/Delete"})
    with pytest.raises(ActionNotAllowed):
        check_allowed("execute_menu_item", {})


@pytest.mark.parametrize(
    "action", ["create", "load", "save", "close_scene", "move_to_scene", "validate"]
)
def test_scene_changes_are_refused(action):
    with pytest.raises(ActionNotAllowed, match="may only read"):
        check_allowed("manage_scene", {"action": action})
    with pytest.raises(ActionNotAllowed):
        check_allowed("manage_scene", {})


def test_unknown_arguments_are_refused():
    with pytest.raises(ActionNotAllowed, match="may not be called with"):
        check_allowed("find_gameobjects", {"search_term": "x", "delete": True})
    with pytest.raises(ActionNotAllowed):
        check_allowed("read_console", {"action": "get", "shell": "rm -rf /"})


def test_console_actions_are_limited():
    with pytest.raises(ActionNotAllowed, match="read_console"):
        check_allowed("read_console", {"action": "export"})


def test_the_allowlist_is_small():
    assert set(ALLOWED_TOOLS) == {
        "execute_menu_item",
        "read_console",
        "refresh_unity",
        "manage_scene",
        "find_gameobjects",
    }


# ---- the client, against an in-process fake ------------------------------------------------------


async def test_a_call_returns_the_parsed_reply():
    fake = FakeUnity()
    fake.console = ["[RigAgent] hello"]
    async with UnityMcpClient(fake.server) as unity:
        reply = await unity.call_tool("read_console", {"action": "get", "types": ["log"]})
    assert reply == {"success": True, "data": ["[RigAgent] hello"]}
    assert fake.calls == [("read_console", {"action": "get", "types": ["log"], "count": 10})]


async def test_a_forbidden_call_never_reaches_unity():
    fake = FakeUnity()
    async with UnityMcpClient(fake.server) as unity:
        with pytest.raises(ActionNotAllowed):
            await unity.call_tool("delete_script", {"path": "Assets/Important.cs"})
        with pytest.raises(ActionNotAllowed):
            await unity.call_tool("execute_menu_item", {"menu_path": "Assets/Delete"})
        with pytest.raises(ActionNotAllowed):
            await unity.call_tool("manage_scene", {"action": "create"})
    assert fake.calls == []


async def test_the_import_menu_item_can_be_run():
    fake = FakeUnity()
    async with UnityMcpClient(fake.server) as unity:
        await unity.call_tool("execute_menu_item", {"menu_path": IMPORT_MENU})
    assert fake.calls == [("execute_menu_item", {"menu_path": IMPORT_MENU})]


async def test_a_failure_reply_becomes_an_error():
    fake = FakeUnity()
    fake.reply = {"success": False, "error": "Menu item not found"}
    async with UnityMcpClient(fake.server) as unity:
        with pytest.raises(UnityMcpError, match="execute_menu_item failed: Menu item not found"):
            await unity.call_tool("execute_menu_item", {"menu_path": IMPORT_MENU})


async def test_tools_can_be_listed():
    async with UnityMcpClient(FakeUnity().server) as unity:
        names = await unity.list_tools()
    assert {"read_console", "execute_menu_item", "delete_script"} <= set(names)


async def test_editor_state_is_read_through_the_resource():
    async with UnityMcpClient(FakeUnity().server) as unity:
        state = await unity.editor_state()
    assert state["unity"]["unity_version"] == "6000.4.0f1" and state["advice"]["ready_for_tools"]


async def test_only_unity_resources_can_be_read():
    async with UnityMcpClient(FakeUnity().server) as unity:
        with pytest.raises(ActionNotAllowed, match="mcpforunity://"):
            await unity.read_resource("file:///etc/passwd")


async def test_wait_until_ready_waits_out_a_compile():
    fake = FakeUnity()
    fake.not_ready_reads = 3
    async with UnityMcpClient(fake.server) as unity:
        state = await unity.wait_until_ready(timeout=5, poll=0.01)
    assert state["advice"]["ready_for_tools"] and fake.not_ready_reads == 0


async def test_wait_until_ready_gives_up_and_says_why():
    fake = FakeUnity()
    fake.not_ready_reads = 10_000
    async with UnityMcpClient(fake.server) as unity:
        with pytest.raises(UnityMcpError, match="not ready.*compiling"):
            await unity.wait_until_ready(timeout=0.2, poll=0.05)


async def test_console_helpers():
    fake = FakeUnity()
    fake.console = ["[RigAgent] one", "[RigAgent] two"]
    async with UnityMcpClient(fake.server) as unity:
        assert await unity.console_messages(["log"]) == ["[RigAgent] one", "[RigAgent] two"]
        await unity.clear_console()
        assert await unity.console_messages(["log"]) == []
    assert fake.calls[1][1]["action"] == "clear"


async def test_the_server_name_is_available():
    async with UnityMcpClient(FakeUnity().server) as unity:
        assert "fake-unity" in unity.server_name


async def test_using_the_client_without_connecting_is_an_error():
    with pytest.raises(UnityMcpError, match="not connected"):
        await UnityMcpClient(FakeUnity().server).list_tools()


async def test_an_unreachable_server_is_reported_as_unavailable():
    with pytest.raises(
        UnityUnavailable, match="cannot reach the Unity MCP server at http://127.0.0.1:9/mcp"
    ):
        async with UnityMcpClient("http://127.0.0.1:9/mcp", timeout=2):
            pass


# ---- the setup check -----------------------------------------------------------------------------


def test_check_unity_reports_a_healthy_server():
    status = check_unity(FakeUnity().server)
    assert status.ok and status.ready and status.unity_version == "6000.4.0f1"
    assert status.scene == "SampleScene" and status.instance == "fake@1"
    assert status.missing_tools == [] and status.tool_count >= 5


def test_check_unity_names_missing_tools():
    fake = FakeUnity(tools=("read_console", "execute_menu_item"))
    status = check_unity(fake.server)
    assert not status.ok
    assert set(status.missing_tools) == {"refresh_unity", "manage_scene", "find_gameobjects"}


def test_check_unity_reports_a_busy_editor():
    fake = FakeUnity()
    fake.not_ready_reads = 5
    status = check_unity(fake.server)
    assert not status.ok and status.blocking == ["compiling"]


def test_check_unity_raises_when_nothing_answers():
    with pytest.raises(UnityUnavailable):
        check_unity("http://127.0.0.1:9/mcp")


async def test_an_empty_state_during_a_domain_reload_is_waited_out_not_a_crash():
    fake = FakeUnity()
    fake.empty_state_reads = 3
    async with UnityMcpClient(fake.server) as unity:
        state = await unity.wait_until_ready(timeout=5, poll=0.01)
    assert state["advice"]["ready_for_tools"] and fake.empty_state_reads == 0
