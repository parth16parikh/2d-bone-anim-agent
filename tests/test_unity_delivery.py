import json
import os
import time

import pytest

from fake_unity import FakeUnity
from layout_helpers import good_skeleton
from rig_agent.unity.contract import IMPORT_MENU, REPORT_FILE, RIGS_DIR, SCRIPTS_DIR, SKELETON_FILE
from rig_agent.unity.delivery import UnityDelivery
from rig_agent.unity.install import install_scripts
from rig_agent.unity.mcp_client import ALLOWED_TOOLS
from unity_helpers import make_project, simulate_import


@pytest.fixture
def skeleton():
    return good_skeleton(view="side", rest_pose="side_neutral", optional_bones=["hands", "toes"])


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "unity")


def delivery(fake, project, **kw):
    lines = kw.pop("lines", None)
    return UnityDelivery(
        fake.server,
        project,
        report_wait=kw.pop("report_wait", 2.0),
        compile_wait=5.0,
        say=(lines.append if lines is not None else (lambda m: None)),
        **kw,
    )


def unity_with_importer(project, mutate=None, installed=True):
    """A fake Unity whose import menu item behaves like the C# importer."""
    fake = FakeUnity()
    fake.on_menu = simulate_import(project, mutate)
    if installed:
        install_scripts(project)
    return fake


# ---- the happy path ------------------------------------------------------------------------------


def test_delivering_a_rig_is_applied_and_verified(project, skeleton):
    fake = unity_with_importer(project)
    lines = []
    result = delivery(fake, project, lines=lines).deliver(skeleton)
    assert result.status == "applied"
    assert f"{len(skeleton.bones)} bones under RigAgent_Output/{skeleton.rig_name}" in result.detail
    assert ("execute_menu_item", {"menu_path": IMPORT_MENU}) in fake.calls
    text = "\n".join(lines)
    assert (
        "[unity] connected" in text
        and "[unity] import triggered" in text
        and "[unity] verified" in text
    )


def test_the_skeleton_is_written_where_the_importer_reads_it(project, skeleton):
    delivery(unity_with_importer(project), project).deliver(skeleton)
    written = project / RIGS_DIR / SKELETON_FILE
    assert json.loads(written.read_text())["rig_name"] == skeleton.rig_name
    assert len(json.loads(written.read_text())["bones"]) == len(skeleton.bones)


def test_a_new_delivery_replaces_the_previous_skeleton_file(project, skeleton):
    fake = unity_with_importer(project)
    (project / RIGS_DIR).mkdir(parents=True, exist_ok=True)
    (project / RIGS_DIR / SKELETON_FILE).write_text('{"old": true}')
    delivery(fake, project).deliver(skeleton)
    assert "old" not in json.loads((project / RIGS_DIR / SKELETON_FILE).read_text())


def test_apply_and_verify_can_run_as_separate_steps(project, skeleton):
    fake = unity_with_importer(project)
    unity = delivery(fake, project)
    assert unity.apply(skeleton).status == "applied"
    assert unity.verify(skeleton).status == "applied"


def test_the_console_is_cleared_before_the_import(project, skeleton):
    fake = unity_with_importer(project)
    delivery(fake, project).deliver(skeleton)
    names = [c[0] for c in fake.calls]
    menu = names.index("execute_menu_item")
    assert any(
        c == ("read_console", {"action": "clear", "types": None, "count": 10})
        for c in fake.calls[:menu]
    )


# ---- safety --------------------------------------------------------------------------------------


def test_only_allowlisted_tools_are_ever_called(project, skeleton):
    fake = unity_with_importer(project, installed=False)
    delivery(fake, project).deliver(skeleton)
    assert {name for name, _ in fake.calls} <= set(ALLOWED_TOOLS)
    assert "delete_script" not in {name for name, _ in fake.calls}


def test_nothing_outside_the_two_folders_is_written(project, skeleton):
    fake = unity_with_importer(project, installed=False)
    delivery(fake, project).deliver(skeleton)
    written = {p.relative_to(project).parts[:2] for p in project.rglob("*") if p.is_file()}
    written -= {("Packages", "manifest.json")}  # the fake project's own package list
    assert written <= {("Assets", "RigAgent"), ("Assets", "Rigs")}


# ---- installing the scripts ----------------------------------------------------------------------


def test_missing_scripts_are_installed_and_compiled_first(project, skeleton):
    fake = unity_with_importer(project, installed=False)
    lines = []
    result = delivery(fake, project, lines=lines).deliver(skeleton)
    assert result.status == "applied"
    assert (project / SCRIPTS_DIR / "Editor" / "RigImporter.cs").is_file()
    refresh = next(args for name, args in fake.calls if name == "refresh_unity")
    assert refresh == {"mode": "force", "compile": "request"}
    assert any("installed 8 C# script(s)" in line for line in lines)


def test_installed_scripts_are_not_compiled_again(project, skeleton):
    fake = unity_with_importer(project, installed=True)
    delivery(fake, project).deliver(skeleton)
    assert "refresh_unity" not in {name for name, _ in fake.calls}


def test_compile_errors_after_installing_fail_the_delivery(project, skeleton):
    fake = unity_with_importer(project, installed=False)
    fake.on_refresh = lambda: fake.console.append(
        "Assets/RigAgent/Editor/RigImporter.cs(9,1): error CS1002: ; expected"
    )
    result = delivery(fake, project).deliver(skeleton)
    assert result.status == "failed" and "errors after installing the scripts" in result.detail
    assert "execute_menu_item" not in {name for name, _ in fake.calls}


def test_a_busy_editor_is_waited_for(project, skeleton):
    fake = unity_with_importer(project)
    fake.not_ready_reads = 2
    assert delivery(fake, project).deliver(skeleton).status == "applied"


# ---- failures ------------------------------------------------------------------------------------


def test_an_unreachable_unity_is_unavailable_not_a_crash(project, skeleton):
    result = UnityDelivery("http://127.0.0.1:9/mcp", project, timeout=2).deliver(skeleton)
    assert result.status == "unavailable" and "cannot reach the Unity MCP server" in result.detail


def test_a_missing_project_path_is_unavailable(skeleton, monkeypatch):
    monkeypatch.setattr("rig_agent.unity.delivery.settings.unity_project_path", None)
    result = UnityDelivery(FakeUnity().server, None).deliver(skeleton)
    assert result.status == "unavailable" and "UNITY_PROJECT_PATH is not set" in result.detail


def test_a_folder_that_is_not_a_unity_project_fails_clearly(tmp_path, skeleton):
    result = UnityDelivery(FakeUnity().server, tmp_path).deliver(skeleton)
    assert result.status == "failed" and "not a Unity project" in result.detail


def test_the_importers_own_errors_are_reported(project, skeleton):
    def broken(report):
        report["ok"] = False
        report["errors"] = ["expected exactly one root bone, found 2"]

    result = delivery(unity_with_importer(project, broken), project).deliver(skeleton)
    assert result.status == "failed"
    assert "expected exactly one root bone, found 2" in result.detail


def test_positions_that_do_not_match_the_json_fail_verification(project, skeleton):
    def drift(report):
        report["bones"][4]["world_head"][0] += 0.05

    result = delivery(unity_with_importer(project, drift), project).deliver(skeleton)
    assert result.status == "failed" and "units off" in result.detail


def test_many_problems_are_summarised(project, skeleton):
    def wreck(report):
        for bone in report["bones"]:
            bone["world_head"][0] += 1

    result = delivery(unity_with_importer(project, wreck), project).deliver(skeleton)
    assert result.status == "failed" and "more)" in result.detail


def test_no_report_means_the_import_did_not_run(project, skeleton):
    fake = FakeUnity()  # the menu item does nothing
    install_scripts(project)
    result = delivery(fake, project, report_wait=0.6).deliver(skeleton)
    assert result.status == "failed" and "wrote no import report within" in result.detail


def test_a_stale_report_from_an_earlier_import_is_not_accepted(project, skeleton):
    install_scripts(project)
    old = project / RIGS_DIR / REPORT_FILE
    old.write_text(json.dumps({"ok": True}))
    long_ago = time.time() - 3600
    os.utime(old, (long_ago, long_ago))
    result = delivery(FakeUnity(), project, report_wait=0.6).deliver(skeleton)
    assert result.status == "failed" and "no import report" in result.detail


def test_console_errors_during_the_import_fail_the_delivery(project, skeleton):
    fake = unity_with_importer(project)
    real = fake.on_menu

    def import_then_error():
        real()
        fake.console.append("NullReferenceException: Object reference not set")

    fake.on_menu = import_then_error
    result = delivery(fake, project).deliver(skeleton)
    assert result.status == "failed" and "Unity console errors" in result.detail


def test_a_menu_item_failure_is_reported(project, skeleton):
    fake = unity_with_importer(project)
    fake.reply = {"success": False, "error": "menu item not found"}
    result = delivery(fake, project).deliver(skeleton)
    assert result.status == "failed" and "menu item not found" in result.detail


def test_verify_alone_fails_without_a_prior_import(project, skeleton):
    install_scripts(project)
    result = delivery(FakeUnity(), project, report_wait=0.4).verify(skeleton)
    assert result.status == "failed"


# ---- where the rig's sprite and skeleton asset go -------------------------------------------------


def test_a_single_import_defaults_to_the_generated_folder(project, skeleton):
    delivery(unity_with_importer(project), project).deliver(skeleton)
    options = json.loads((project / RIGS_DIR / "import_options.json").read_text())
    assert options == {"asset_folder": f"Assets/Rigs/Generated/{skeleton.rig_name}", "ik": True}


def test_with_a_prefab_folder_the_assets_go_beside_the_prefab(project, skeleton):
    from rig_agent.unity.prefab import PrefabOptions

    fake = unity_with_importer(project)
    delivery(fake, project, prefab=PrefabOptions("Assets/Prefabs/Rigs")).apply(skeleton)
    options = json.loads((project / RIGS_DIR / "import_options.json").read_text())
    assert options["asset_folder"] == f"Assets/Prefabs/Rigs/{skeleton.rig_name}"


# ---- turning IK off -------------------------------------------------------------------------------


def test_ik_is_on_by_default_and_can_be_switched_off(project, skeleton):
    delivery(unity_with_importer(project), project, ik=False).apply(skeleton)
    assert json.loads((project / RIGS_DIR / "import_options.json").read_text())["ik"] is False


def test_a_delivery_without_ik_does_not_expect_solvers(project, skeleton):
    def no_ik(report):
        report["ik"] = {"enabled": False, "solvers": []}

    fake = unity_with_importer(project, no_ik)
    assert delivery(fake, project, ik=False).deliver(skeleton).status == "applied"
    fake = unity_with_importer(project, no_ik)
    result = delivery(fake, project).deliver(skeleton)
    assert result.status == "failed" and "IK was expected" in result.detail
