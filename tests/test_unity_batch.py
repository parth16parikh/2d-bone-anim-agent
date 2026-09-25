import json

import pytest

from fake_unity import FakeUnity
from layout_helpers import good_skeleton
from rig_agent.unity.batch import collect_rigs, safe_name
from rig_agent.unity.contract import (
    BATCH_DIR,
    IMPORT_ALL_MENU,
    IMPORT_MENU,
    RIGS_DIR,
    SAVE_PREFABS_MENU,
)
from rig_agent.unity.delivery import UnityDelivery
from rig_agent.unity.install import install_scripts
from rig_agent.unity.mcp_client import ALLOWED_TOOLS
from rig_agent.unity.prefab import PrefabFolderError, PrefabOptions, check_prefab_folder
from rig_agent.unity.verify import compare_import
from unity_helpers import (
    FakePrefabs,
    make_project,
    simulate_batch_import,
    simulate_import,
    unity_report,
)


def write_rig(out, folder, *, passed=True, **kw):
    kw.setdefault("view", "front")
    kw.setdefault("rest_pose", "A_pose")
    skeleton = good_skeleton(**kw)
    target = out / folder
    target.mkdir(parents=True)
    (target / "skeleton.json").write_text(skeleton.model_dump_json())
    if passed is not None:
        issues = [] if passed else [{"code": "depth_order", "message": "x", "bones": []}]
        (target / "validation_report.json").write_text(json.dumps({"issues": issues}))
    return skeleton


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    write_rig(folder, "knight")
    write_rig(folder, "runner", view="side", rest_pose="side_neutral")
    return folder


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "unity")


def unity_for(project, mutate=None):
    fake = FakeUnity()
    fake.menus[IMPORT_ALL_MENU] = simulate_batch_import(project, mutate)
    install_scripts(project)
    return fake


def delivery(fake, project, prefab=None, **kw):
    return UnityDelivery(
        fake.server, project, report_wait=2.0, compile_wait=5.0, prefab=prefab, **kw
    )


# ---- finding the rigs -----------------------------------------------------------------------------


def test_every_rig_in_out_is_found_by_folder_name(out):
    rigs, skipped = collect_rigs(out)
    assert [r.name for r in rigs] == ["knight", "runner"] and not skipped
    assert all(r.skeleton.rig_name == r.name for r in rigs)


def test_the_rig_name_comes_from_the_folder_so_same_prompt_runs_do_not_collide(out):
    write_rig(out, "knight2")  # good_skeleton gives every rig the same rig_name
    rigs, _ = collect_rigs(out)
    assert len({r.skeleton.rig_name for r in rigs}) == len(rigs) == 3


def test_the_validation_result_is_read_from_the_report(out):
    write_rig(out, "bad", passed=False)
    write_rig(out, "unchecked", passed=None)
    passed = {r.name: r.passed for r in collect_rigs(out)[0]}
    assert passed == {"bad": False, "knight": True, "runner": True, "unchecked": None}


def test_unreadable_skeletons_are_skipped_not_fatal(out):
    (out / "broken").mkdir()
    (out / "broken" / "skeleton.json").write_text("{nope")
    (out / "empty").mkdir()
    rigs, skipped = collect_rigs(out)
    assert len(rigs) == 2
    assert [s.source.parent.name for s in skipped] == ["broken"]
    assert "not a valid skeleton.json" in skipped[0].reason


def test_a_missing_out_folder_has_no_rigs(tmp_path):
    assert collect_rigs(tmp_path / "nope") == ([], [])


@pytest.mark.parametrize(
    ("text", "expected"),
    [("knight 2", "knight_2"), ("../x", "x"), ("a/b\\c", "a_b_c"), ("", "rig")],
)
def test_names_are_made_safe(text, expected):
    assert safe_name(text) == expected


# ---- prefab folder -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "folder", ["Assets/Prefabs/Rigs", "Assets", "/Assets/Rigs/", "Assets\\Rigs"]
)
def test_folders_inside_assets_are_accepted(folder):
    assert check_prefab_folder(folder).startswith("Assets")


@pytest.mark.parametrize(
    "folder",
    [
        "",
        "Prefabs",
        "/etc",
        "Assets/../ProjectSettings",
        "Assets/.hidden",
        "Assets//x",
        "Packages/x",
        "Assets/a:b",
    ],
)
def test_folders_outside_assets_or_odd_ones_are_refused(folder):
    with pytest.raises(PrefabFolderError):
        PrefabOptions(folder)


# ---- delivering everything -----------------------------------------------------------------------


def test_all_rigs_are_delivered_and_verified(project, out):
    fake = unity_for(project)
    rigs, _ = collect_rigs(out)
    result = delivery(fake, project).deliver_all(rigs)
    assert result.status == "applied", result
    assert [(o.name, o.status) for o in result.rigs] == [
        ("knight", "applied"),
        ("runner", "applied"),
    ]
    assert ("execute_menu_item", {"menu_path": IMPORT_ALL_MENU}) in fake.calls


def test_each_rig_gets_its_own_file_and_the_manifest_lists_them(project, out):
    delivery(unity_for(project), project).deliver_all(collect_rigs(out)[0])
    files = sorted(p.name for p in (project / BATCH_DIR).glob("*.json"))
    assert files == ["knight.json", "runner.json"]
    manifest = json.loads((project / RIGS_DIR / "batch.json").read_text())
    assert manifest["files"] == [f"{BATCH_DIR}/knight.json", f"{BATCH_DIR}/runner.json"]
    assert json.loads((project / BATCH_DIR / "runner.json").read_text())["rig_name"] == "runner"


def test_a_rig_that_did_not_import_cleanly_is_reported_by_name(project, out):
    def drift(report):
        if report["rig_name"] == "runner":
            report["bones"][3]["world_head"][0] += 0.2

    result = delivery(unity_for(project, drift), project).deliver_all(collect_rigs(out)[0])
    outcomes = {o.name: o for o in result.rigs}
    assert result.status == "failed"
    assert outcomes["knight"].status == "applied"
    assert outcomes["runner"].status == "failed" and "units off" in outcomes["runner"].detail


def test_a_rig_unity_never_reported_fails(project, out):
    def lose(report):
        report["rig_name"] = (
            "someone_else" if report["rig_name"] == "runner" else report["rig_name"]
        )

    result = delivery(unity_for(project, lose), project).deliver_all(collect_rigs(out)[0])
    assert {o.name: o.status for o in result.rigs} == {"knight": "applied", "runner": "failed"}
    assert "did not report" in result.rigs[1].detail


def test_nothing_to_import_is_a_failure(project):
    result = delivery(unity_for(project), project).deliver_all([])
    assert result.status == "failed" and "no rigs" in result.detail


def test_batch_import_without_a_report_says_so(project, out):
    fake = FakeUnity()  # the menu does nothing
    install_scripts(project)
    result = UnityDelivery(fake.server, project, report_wait=0.5).deliver_all(collect_rigs(out)[0])
    assert result.status == "failed" and "batch import report" in result.detail


def test_console_errors_fail_the_batch(project, out):
    fake = unity_for(project)
    real = fake.menus[IMPORT_ALL_MENU]

    def import_then_error():
        real()
        fake.console.append("NullReferenceException")

    fake.menus[IMPORT_ALL_MENU] = import_then_error
    result = delivery(fake, project).deliver_all(collect_rigs(out)[0])
    assert result.status == "failed" and "console errors" in result.detail


def test_an_unreachable_unity_is_unavailable(project, out):
    result = UnityDelivery("http://127.0.0.1:9/mcp", project, timeout=2).deliver_all(
        collect_rigs(out)[0]
    )
    assert result.status == "unavailable"


def test_the_batch_only_uses_allowlisted_calls(project, out):
    fake = unity_for(project)
    delivery(fake, project, prefab=PrefabOptions("Assets/Prefabs")).deliver_all(
        collect_rigs(out)[0]
    )
    assert {name for name, _ in fake.calls} <= set(ALLOWED_TOOLS)


# ---- prefabs in a batch --------------------------------------------------------------------------


def with_prefabs(project, **kw):
    fake = unity_for(project)
    prefabs = FakePrefabs(project, **kw)
    fake.menus[SAVE_PREFABS_MENU] = prefabs
    return fake, prefabs


def test_verified_rigs_are_saved_as_prefabs_in_the_chosen_folder(project, out):
    fake, prefabs = with_prefabs(project)
    result = delivery(fake, project, PrefabOptions("Assets/Prefabs/Rigs")).deliver_all(
        collect_rigs(out)[0]
    )
    assert result.status == "applied"
    assert prefabs.requests == [
        {"folder": "Assets/Prefabs/Rigs", "overwrite": False, "rigs": ["knight", "runner"]}
    ]
    assert [o.prefab for o in result.rigs] == [
        "Assets/Prefabs/Rigs/knight.prefab",
        "Assets/Prefabs/Rigs/runner.prefab",
    ]


def test_no_prefab_step_without_prefab_options(project, out):
    fake, prefabs = with_prefabs(project)
    delivery(fake, project).deliver_all(collect_rigs(out)[0])
    assert prefabs.requests == []
    assert SAVE_PREFABS_MENU not in [
        a["menu_path"] for n, a in fake.calls if n == "execute_menu_item"
    ]


def test_rigs_that_failed_validation_or_have_no_report_get_no_prefab(project, out):
    write_rig(out, "bad", passed=False)
    write_rig(out, "unchecked", passed=None)
    fake, prefabs = with_prefabs(project)
    result = delivery(fake, project, PrefabOptions("Assets/P")).deliver_all(collect_rigs(out)[0])
    assert prefabs.requests[0]["rigs"] == ["knight", "runner"]
    outcomes = {o.name: o for o in result.rigs}
    assert outcomes["bad"].status == "applied" and outcomes["bad"].prefab == ""
    assert "failed validation" in outcomes["bad"].detail
    assert "no validation report" in outcomes["unchecked"].detail
    assert result.status == "applied"


def test_a_rig_that_did_not_import_gets_no_prefab(project, out):
    def drift(report):
        if report["rig_name"] == "knight":
            report["bones"][3]["world_head"][0] += 0.2

    fake = unity_for(project, drift)
    prefabs = FakePrefabs(project)
    fake.menus[SAVE_PREFABS_MENU] = prefabs
    delivery(fake, project, PrefabOptions("Assets/P")).deliver_all(collect_rigs(out)[0])
    assert prefabs.requests[0]["rigs"] == ["runner"]


def test_an_existing_prefab_is_kept_unless_overwrite_is_set(project, out):
    fake, prefabs = with_prefabs(project, existing={"knight"})
    result = delivery(fake, project, PrefabOptions("Assets/P")).deliver_all(collect_rigs(out)[0])
    assert "prefab kept" in result.rigs[0].detail and "prefab created" in result.rigs[1].detail
    assert result.status == "applied"

    fake, prefabs = with_prefabs(project, existing={"knight"})
    result = delivery(fake, project, PrefabOptions("Assets/P", overwrite=True)).deliver_all(
        collect_rigs(out)[0]
    )
    assert prefabs.requests[0]["overwrite"] is True
    assert "prefab updated" in result.rigs[0].detail


def test_a_prefab_failure_fails_that_rig_only(project, out):
    fake, _ = with_prefabs(project, failing={"runner"})
    result = delivery(fake, project, PrefabOptions("Assets/P")).deliver_all(collect_rigs(out)[0])
    outcomes = {o.name: o for o in result.rigs}
    assert result.status == "failed"
    assert outcomes["knight"].status == "applied" and outcomes["knight"].prefab
    assert (
        outcomes["runner"].status == "failed"
        and "prefab not saved: boom" in outcomes["runner"].detail
    )


def test_a_missing_prefab_report_is_an_error_not_a_hang(project, out):
    fake = unity_for(project)  # the prefab menu does nothing
    result = UnityDelivery(
        fake.server, project, report_wait=0.5, prefab=PrefabOptions("Assets/P")
    ).deliver_all(collect_rigs(out)[0])
    assert result.status == "failed"
    assert "prefab report" in result.detail


# ---- prefab for a single rig ---------------------------------------------------------------------


def single_unity(project, **kw):
    fake = FakeUnity()
    fake.menus[IMPORT_MENU] = simulate_import(project)
    prefabs = FakePrefabs(project, **kw)
    fake.menus[SAVE_PREFABS_MENU] = prefabs
    install_scripts(project)
    return fake, prefabs


def test_a_single_verified_rig_can_be_saved_as_a_prefab(project):
    skeleton = good_skeleton(view="side", rest_pose="side_neutral")
    fake, prefabs = single_unity(project)
    result = delivery(fake, project, PrefabOptions("Assets/Prefabs/Rigs")).deliver(skeleton)
    assert result.status == "applied"
    assert f"prefab Assets/Prefabs/Rigs/{skeleton.rig_name}.prefab (created)" in result.detail
    assert prefabs.requests[0]["rigs"] == [skeleton.rig_name]


def test_no_prefab_when_the_import_did_not_verify(project):
    skeleton = good_skeleton(view="side", rest_pose="side_neutral")
    fake = FakeUnity()

    def drift():
        report = unity_report(skeleton)
        report["bones"][2]["world_head"][0] += 0.3
        (project / RIGS_DIR / "last_import.json").write_text(json.dumps(report))

    fake.menus[IMPORT_MENU] = drift
    prefabs = FakePrefabs(project)
    fake.menus[SAVE_PREFABS_MENU] = prefabs
    install_scripts(project)
    result = delivery(fake, project, PrefabOptions("Assets/P")).deliver(skeleton)
    assert result.status == "failed" and prefabs.requests == []


def test_a_single_prefab_failure_is_reported_but_the_rig_stays_verified(project):
    skeleton = good_skeleton(view="side", rest_pose="side_neutral")
    fake, _ = single_unity(project, failing={skeleton.rig_name})
    result = delivery(fake, project, PrefabOptions("Assets/P")).deliver(skeleton)
    assert result.status == "failed"
    assert "the rig is verified, but its prefab was not saved: boom" in result.detail


def test_an_existing_single_prefab_is_kept(project):
    skeleton = good_skeleton(view="side", rest_pose="side_neutral")
    fake, _ = single_unity(project, existing={skeleton.rig_name})
    result = delivery(fake, project, PrefabOptions("Assets/P")).deliver(skeleton)
    assert result.status == "applied" and "(kept)" in result.detail


def test_batch_positions_are_compared_in_each_rigs_own_space(project, out):
    """The importer reports positions without the side-by-side offset, so compare_import holds."""
    rigs, _ = collect_rigs(out)
    for rig in rigs:
        assert compare_import(rig.skeleton, unity_report(rig.skeleton)) == []
