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


# ---- the placeholder sprite and the SpriteSkin ---------------------------------------------------


def test_a_report_without_sprite_data_is_rejected_as_an_outdated_importer(skeleton):
    report = unity_report(skeleton)
    del report["skin"]
    assert "has no sprite data" in compare_import(skeleton, report)[0]


@pytest.mark.parametrize("state", ["SpriteHasNoSkinningInformation", "RootTransformNotFound", ""])
def test_a_skin_that_is_not_ready_is_reported(skeleton, state):
    report = unity_report(skeleton)
    report["skin"]["state"] = state
    assert f"Unity's SpriteSkin is not ready (state '{state}')" in compare_import(skeleton, report)


def test_a_sprite_with_the_wrong_number_of_bones_or_bind_poses_is_reported(skeleton):
    report = unity_report(skeleton)
    report["skin"]["sprite_bones"] -= 1
    report["skin"]["bind_poses"] = 0
    problems = " ".join(compare_import(skeleton, report))
    assert "sprite holds" in problems and "0 bind poses" in problems


def test_a_sprite_without_weights_is_reported(skeleton):
    report = unity_report(skeleton)
    report["skin"]["has_weights"] = False
    assert "the sprite has no bone weights" in compare_import(skeleton, report)


def test_a_missing_skeleton_asset_is_reported(skeleton):
    report = unity_report(skeleton)
    report["skin"]["skeleton_path"] = ""
    assert "no skeleton asset was written" in compare_import(skeleton, report)


# ---- the IK solvers ------------------------------------------------------------------------------


@pytest.fixture
def hands_skeleton():
    return good_skeleton(view="front", rest_pose="A_pose", optional_bones=["hands"])


def test_a_faithful_report_with_ik_has_no_problems(hands_skeleton):
    report = unity_report(hands_skeleton)
    assert len(report["ik"]["solvers"]) == 4
    assert compare_import(hands_skeleton, report) == []


def test_an_arm_without_a_hand_needs_no_solver(skeleton):
    # side view with hands: 4 chains. Without hands, only the legs have an effector.
    bare = good_skeleton(view="side", rest_pose="side_neutral")
    report = unity_report(bare)
    assert [s["chain"] for s in report["ik"]["solvers"]] == ["leg_L", "leg_R"]
    assert compare_import(bare, report) == []


def test_ik_that_was_expected_but_reported_off_is_a_problem(hands_skeleton):
    report = unity_report(hands_skeleton)
    report["ik"] = {"enabled": False, "solvers": []}
    assert "the importer reports it off" in compare_import(hands_skeleton, report)[0]
    del report["ik"]
    assert "the importer reports it off" in compare_import(hands_skeleton, report)[0]


def test_ik_that_was_switched_off_is_not_checked(hands_skeleton):
    report = unity_report(hands_skeleton)
    report["ik"] = {"enabled": False, "solvers": []}
    assert compare_import(hands_skeleton, report, expect_ik=False) == []


def test_a_missing_or_invalid_solver_is_reported(hands_skeleton):
    report = unity_report(hands_skeleton)
    report["ik"]["solvers"] = [s for s in report["ik"]["solvers"] if s["chain"] != "leg_L"]
    report["ik"]["solvers"][0]["valid"] = False
    problems = " ".join(compare_import(hands_skeleton, report))
    assert "'leg_L' has no solver" in problems and "'arm_L' is not valid" in problems


def test_a_solver_that_bends_the_wrong_way_is_reported(hands_skeleton):
    report = unity_report(hands_skeleton)
    report["ik"]["solvers"][1]["flip"] = not report["ik"]["solvers"][1]["flip"]  # arm_R
    problems = compare_import(hands_skeleton, report)
    assert len(problems) == 1 and "IK chain 'arm_R' bends to the wrong side" in problems[0]


def test_a_solver_with_the_wrong_effector_or_an_unknown_one_is_reported(hands_skeleton):
    report = unity_report(hands_skeleton)
    report["ik"]["solvers"][0]["effector"] = "forearm_L"
    report["ik"]["solvers"].append({"chain": "tail", "effector": "x", "valid": True, "flip": False})
    problems = " ".join(compare_import(hands_skeleton, report))
    assert (
        "reaches with 'forearm_L'" in problems
        and "IK solver 'tail' that is not in the JSON" in problems
    )
