import copy

import pytest

from layout_helpers import good_skeleton
from rig_agent.unity.verify import compare_import
from unity_helpers import unity_report


@pytest.fixture
def skeleton():
    return good_skeleton(
        view="side", rest_pose="side_neutral", optional_bones=["hands", "toes"],
        extra_bones=[{"name": "extra_cape", "parent": "spine", "direction_deg": 170, "length_ratio": 0.3, "layer": "behind"}],
    )  # fmt: skip


def test_a_faithful_import_has_no_problems(skeleton):
    assert compare_import(skeleton, unity_report(skeleton)) == []


def test_small_position_noise_is_within_tolerance(skeleton):
    report = unity_report(skeleton)
    report["bones"][3]["world_head"][0] += 5e-4
    assert compare_import(skeleton, report) == []


def test_a_position_error_over_the_tolerance_is_reported(skeleton):
    report = unity_report(skeleton)
    report["bones"][3]["world_tail"][1] += 0.01
    problems = compare_import(skeleton, report)
    assert len(problems) == 1 and "tail is 0.0100 units off" in problems[0]


def test_the_importers_own_failure_is_reported(skeleton):
    report = unity_report(skeleton)
    report["ok"] = False
    report["errors"] = ["positions differ from the JSON by up to 3.00E-002"]
    problems = compare_import(skeleton, report)
    assert "Unity's importer reported failure" in problems
    assert "importer: positions differ from the JSON by up to 3.00E-002" in problems


def test_a_wrong_bone_count_is_reported(skeleton):
    report = unity_report(skeleton)
    report["bone_count"] -= 1
    assert any("created" in p and "expected" in p for p in compare_import(skeleton, report))


def test_a_missing_bone_is_reported(skeleton):
    report = unity_report(skeleton)
    del report["bones"][-1]
    report["bone_count"] -= 1
    problems = compare_import(skeleton, report)
    assert f"bone '{skeleton.bones[-1].name}' is missing in Unity" in problems


def test_an_unexpected_bone_is_reported(skeleton):
    report = unity_report(skeleton)
    report["bones"].append({**copy.deepcopy(report["bones"][2]), "name": "intruder"})
    assert any("not in the JSON" in p and "intruder" in p for p in compare_import(skeleton, report))


def test_a_wrong_parent_is_reported(skeleton):
    report = unity_report(skeleton)
    thigh = next(b for b in report["bones"] if b["name"] == "thigh_R")
    thigh["parent"] = "spine"
    assert any(
        "'thigh_R' hangs from 'spine', expected 'hip'" in p
        for p in compare_import(skeleton, report)
    )


def test_a_wrong_depth_or_layer_is_reported(skeleton):
    report = unity_report(skeleton)
    next(b for b in report["bones"] if b["name"] == "thigh_L")["depth"] = 1
    next(b for b in report["bones"] if b["name"] == "extra_cape")["layer"] = "front"
    problems = compare_import(skeleton, report)
    assert any("'thigh_L' has depth 1, expected -1" in p for p in problems)
    assert any("'extra_cape' has layer 'front', expected 'behind'" in p for p in problems)


def test_objects_outside_the_output_root_are_reported(skeleton):
    problems = compare_import(skeleton, unity_report(skeleton, root="Somewhere"))
    assert problems and all("outside RigAgent_Output" in p for p in problems)


def test_a_wrong_rig_name_is_reported(skeleton):
    report = unity_report(skeleton)
    report["rig_name"] = "other"
    assert any("rig name is 'other'" in p for p in compare_import(skeleton, report))


def test_a_report_without_positions_is_reported(skeleton):
    report = unity_report(skeleton)
    report["bones"][1]["world_head"] = None
    assert any("no head position" in p for p in compare_import(skeleton, report))


def test_an_empty_report_lists_everything(skeleton):
    problems = compare_import(skeleton, {})
    assert "Unity's importer reported failure" in problems
    assert sum("is missing in Unity" in p for p in problems) == len(skeleton.bones)


def test_the_tolerance_can_be_changed(skeleton):
    report = unity_report(skeleton)
    report["bones"][2]["world_head"][0] += 0.01
    assert compare_import(skeleton, report)
    assert compare_import(skeleton, report, tolerance=0.05) == []
