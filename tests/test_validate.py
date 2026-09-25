import itertools

import pytest

from layout_helpers import bone, make_spec, validated
from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.schemas.validation import IssueCode
from rig_agent.validator.report import validate
from rig_agent.vocabulary.bones import OPTIONAL_TOKENS, token_views
from rig_agent.vocabulary.presets import PRESETS

FRONT = {"view": "front", "rest_pose": "A_pose"}
SIDE = {"view": "side", "rest_pose": "side_neutral"}
ALL_FRONT = {**FRONT, "optional_bones": ["chest", "neck", "hands", "shoulders", "jaw"]}
ALL_SIDE = {**SIDE, "optional_bones": ["chest", "neck", "hands", "toes", "jaw"]}


def extra(**kw):
    data = {"name": "extra_cape", "parent": "chest", "direction_deg": -90, "length_ratio": 0.3}
    data.update(kw)
    return data


def codes(report):
    return {i.code for i in report.issues}


def move_head(name, dx=0.0, dy=0.0):
    def mutate(sk):
        b = bone(sk, name)
        b.world_head = (b.world_head[0] + dx, b.world_head[1] + dy)

    return mutate


# ---- everything the builder makes is valid -------------------------------------------------------


@pytest.mark.parametrize("preset", list(PRESETS))
@pytest.mark.parametrize(
    ("view", "pose"), [("front", "A_pose"), ("front", "T_pose"), ("side", "side_neutral")]
)
def test_every_builder_output_validates(preset, view, pose):
    tokens = [t for t in OPTIONAL_TOKENS if view in token_views(t)]
    for size in range(len(tokens) + 1):
        for subset in itertools.combinations(tokens, size):
            report = validated(
                preset=preset, view=view, rest_pose=pose, optional_bones=list(subset)
            )
            assert report.passed and report.issues == [], (
                preset,
                view,
                pose,
                subset,
                report.issues,
            )


def test_builder_output_with_extras_validates():
    extras = [
        extra(segments=3, layer="behind"),
        extra(name="extra_hair", parent="head", direction_deg=-45, segments=2, mirror=True),
        extra(name="extra_glove", parent="hand_L", direction_deg=-90, mirror=True),
        extra(name="extra_sword", parent="hand_R", direction_deg=-20, length_ratio=0.35),
    ]
    for kw in (ALL_FRONT, ALL_SIDE):
        report = validated(extra_bones=extras, **kw)
        assert report.issues == [], report.issues


def test_moderate_overrides_validate():
    overrides = {"leg_scale": 1.15, "arm_scale": 1.15, "torso_scale": 0.95, "head_scale": 1.1,
                 "thigh_shin_bias": 0.85, "hand_size": 1.3, "foot_size": 1.2}  # fmt: skip
    for kw in (ALL_FRONT, ALL_SIDE):
        assert validated(overrides=overrides, **kw).issues == []


def test_metrics_of_a_good_rig():
    front = validated(**ALL_FRONT).metrics
    assert front["required_bone_coverage"] == 1.0
    assert front["joint_connectivity"] == 1.0
    assert front["symmetry_error"] < 1e-4 and front["proportion_error"] < 1e-4
    assert "depth_order_correct" not in front
    side = validated(**ALL_SIDE).metrics
    assert side["depth_order_correct"] == 1.0 and side["symmetry_error"] < 1e-4


# ---- lengths -------------------------------------------------------------------------------------


def test_non_positive_length():
    def zero(sk):
        bone(sk, "forearm_L").length = 0

    report = validated(zero, **FRONT)
    assert IssueCode.NON_POSITIVE_LENGTH in codes(report)


def test_extra_segments_below_half_a_percent_of_height_are_too_short():
    report = validated(extra_bones=[extra(segments=4, length_ratio=0.01)], **ALL_FRONT)
    short = [i for i in report.issues if i.code == IssueCode.SEGMENT_TOO_SHORT]
    assert len(short) == 4 and not report.passed


def test_extra_segments_at_the_minimum_are_fine():
    report = validated(extra_bones=[extra(segments=2, length_ratio=0.01)], **ALL_FRONT)
    assert IssueCode.SEGMENT_TOO_SHORT not in codes(report)


# ---- connectivity --------------------------------------------------------------------------------


def test_a_disconnected_canonical_joint():
    report = validated(move_head("forearm_L", dx=0.1), **FRONT)
    issue = next(i for i in report.issues if i.code == IssueCode.DISCONNECTED_JOINT)
    assert issue.bones == ["forearm_L"]
    assert report.metrics["joint_connectivity"] < 1.0


def test_small_gaps_within_the_tolerance_are_accepted():
    assert validated(move_head("forearm_L", dx=0.005), **FRONT).issues == []  # 0.25% of H = 0.005


@pytest.mark.parametrize("name", ["upper_arm_L", "upper_arm_R", "thigh_L", "thigh_R"])
def test_misplaced_limb_roots_in_front_view(name):
    report = validated(move_head(name, dx=0.05), **FRONT)
    assert next(i.code for i in report.issues if name in i.bones) == IssueCode.LIMB_ROOT_MISPLACED


@pytest.mark.parametrize("name", ["upper_arm_R", "thigh_R", "thigh_L"])
def test_misplaced_limb_roots_in_side_view(name):
    report = validated(move_head(name, dx=0.05), **SIDE)
    assert IssueCode.LIMB_ROOT_MISPLACED in codes(report)


def test_a_far_limb_at_the_wrong_offset_is_caught_in_side_view():
    def no_offset(sk):
        for name in ("thigh_L", "shin_L", "foot_L"):  # _L is the far side
            b = bone(sk, name)
            b.world_head = (0.0, b.world_head[1])

    assert IssueCode.LIMB_ROOT_MISPLACED in codes(validated(no_offset, **SIDE))


def test_the_upper_arm_on_a_shoulder_must_start_on_the_shoulder_tail():
    report = validated(move_head("upper_arm_L", dy=0.05), optional_bones=["shoulders"], **FRONT)
    assert IssueCode.DISCONNECTED_JOINT in codes(report)
    assert IssueCode.LIMB_ROOT_MISPLACED not in codes(report)


def test_misplaced_hip():
    report = validated(move_head("hip", dy=0.1), **FRONT)
    assert IssueCode.HIP_MISPLACED in codes(report)


def test_misplaced_jaw():
    report = validated(move_head("jaw", dy=0.05), optional_bones=["jaw"], **FRONT)
    assert IssueCode.JAW_MISPLACED in codes(report)


def test_an_extra_bone_that_floats_away_from_its_parent():
    report = validated(move_head("extra_cape", dx=0.2), extra_bones=[extra()], **ALL_FRONT)
    issue = next(i for i in report.issues if i.code == IssueCode.DISCONNECTED_JOINT)
    assert issue.bones == ["extra_cape"]


def test_an_extra_may_attach_at_either_end_of_its_parent():
    report = validated(extra_bones=[extra(attach_at="head")], **ALL_FRONT)
    assert report.issues == []


def test_a_mirrored_chain_on_an_off_center_parent_without_a_twin_is_disconnected():
    extras = [
        extra(name="extra_arm", parent="chest", direction_deg=-20, length_ratio=0.3),
        extra(
            name="extra_tip", parent="extra_arm", direction_deg=-30, length_ratio=0.1, mirror=True
        ),
    ]
    report = validated(extra_bones=extras, **ALL_FRONT)
    assert IssueCode.DISCONNECTED_JOINT in codes(report)


# ---- symmetry and depth --------------------------------------------------------------------------


def test_front_asymmetry():
    def wonky(sk):
        b = bone(sk, "hand_R")
        b.world_tail = (b.world_tail[0] - 0.1, b.world_tail[1])

    report = validated(wonky, **ALL_FRONT)
    issue = next(i for i in report.issues if i.code == IssueCode.ASYMMETRIC_PAIR)
    assert issue.bones == ["hand_L", "hand_R"]
    assert report.metrics["symmetry_error"] > 0


def test_side_pairs_need_equal_lengths():
    def uneven(sk):
        bone(sk, "shin_R").length *= 1.2

    assert IssueCode.ASYMMETRIC_PAIR in codes(validated(uneven, **SIDE))


def test_side_pairs_must_keep_the_far_offset():
    def stacked(sk):
        for name in ("upper_arm_R", "forearm_R"):
            b = bone(sk, name)
            b.world_head = (b.world_head[0] + 0.05, b.world_head[1])

    assert IssueCode.ASYMMETRIC_PAIR in codes(validated(stacked, **SIDE))


@pytest.mark.parametrize(
    ("name", "depth"), [("thigh_L", 1), ("upper_arm_R", 0), ("hand_L", 0), ("foot_R", -1)]
)
def test_side_depth_order(name, depth):
    def wrong(sk):
        bone(sk, name).depth = depth

    report = validated(wrong, **ALL_SIDE)
    assert IssueCode.DEPTH_ORDER in codes(report)
    assert report.metrics["depth_order_correct"] == 0.0


def test_depth_order_is_not_checked_in_front_view():
    def flat(sk):
        for b in sk.bones:
            b.depth = 0

    assert validated(flat, **FRONT).issues == []


# ---- bounds and bands ----------------------------------------------------------------------------


def test_joints_outside_the_bounding_box():
    def out(sk):
        b = bone(sk, "extra_cape")
        b.world_tail = (b.world_tail[0], 3.0)

    report = validated(out, extra_bones=[extra()], **ALL_FRONT)
    assert IssueCode.OUT_OF_BOUNDS in codes(report)


def test_an_extra_pointing_up_above_the_box_is_out_of_bounds():
    report = validated(
        extra_bones=[extra(parent="head", direction_deg=90, length_ratio=0.5)], **ALL_FRONT
    )
    assert IssueCode.OUT_OF_BOUNDS in codes(report)


def test_a_value_pushed_out_of_its_band_by_multipliers():
    report = validated(overrides={"head_scale": 0.5, "foot_size": 1.5}, **FRONT)
    band_issues = [i for i in report.issues if i.code == IssueCode.PROPORTION_OUT_OF_BAND]
    assert any("foot_length_hu" in i.message for i in band_issues)
    assert not report.passed


def test_extreme_biases_alone_stay_in_band():
    overrides = {"thigh_shin_bias": 0.7, "upper_forearm_bias": 1.3, "chest_bias": 0.7}
    assert validated(overrides=overrides, **ALL_FRONT).issues == []


def test_an_unbuildable_spec_is_reported_not_raised():
    good = build_skeleton(make_spec(**FRONT))
    impossible = make_spec(base={"heads_tall": 2.0, "leg_ratio": 0.6}, **FRONT)
    report = validate(good, impossible)
    assert not report.passed
    assert (
        "no room for a torso"
        in next(i for i in report.issues if i.code == IssueCode.UNBUILDABLE).message
    )


# ---- mirrored twins that coincide ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "coincident"),
    [(90, True), (-90, True), (-85, True), (85, True), (-84, False), (-45, False), (0, False)],
)
def test_mirror_coincident_within_five_degrees_of_vertical(direction, coincident):
    report = validated(
        extra_bones=[extra(parent="head", direction_deg=direction, mirror=True)], **ALL_FRONT
    )
    assert (IssueCode.MIRROR_COINCIDENT in codes(report)) is coincident


def test_mirror_coincident_needs_a_center_parent_and_the_front_view():
    on_arm = validated(
        extra_bones=[extra(parent="hand_L", direction_deg=-90, mirror=True)], **ALL_FRONT
    )
    assert IssueCode.MIRROR_COINCIDENT not in codes(on_arm)
    side = validated(extra_bones=[extra(parent="head", direction_deg=90, mirror=True)], **ALL_SIDE)
    assert IssueCode.MIRROR_COINCIDENT not in codes(side)


# ---- report assembly -----------------------------------------------------------------------------


def test_structural_failures_skip_the_geometry_checks_without_crashing():
    def remove_hip(sk):
        sk.bones = [b for b in sk.bones if b.name != "hip"]

    report = validated(remove_hip, **FRONT)
    assert IssueCode.MISSING_REQUIRED_BONE in codes(report)
    assert "joint_connectivity" not in report.metrics
    assert report.metrics["required_bone_coverage"] == pytest.approx(13 / 14)


def test_a_cycle_skips_the_geometry_checks():
    def loop(sk):
        bone(sk, "hip").parent_id = bone(sk, "spine").id

    report = validated(loop, **FRONT)
    assert IssueCode.CYCLE in codes(report) and "symmetry_error" not in report.metrics


def test_issues_carry_bone_names_for_the_repair_loop():
    report = validated(move_head("forearm_L", dx=0.1), **FRONT)
    assert all(i.bones for i in report.errors)
    assert report.model_dump(mode="json")["passed"] is False
