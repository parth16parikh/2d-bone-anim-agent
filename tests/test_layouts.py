import itertools

import pytest

from layout_helpers import (
    EXEMPT_FROM_PARENT_TAIL,
    is_limb_root,
    layout,
    make_spec,
    parent_tail_gap,
)
from rig_agent.builder.geometry import distance
from rig_agent.vocabulary.bones import OPTIONAL_TOKENS, expand_optional, present_bones, token_views
from rig_agent.vocabulary.poses import FAR_LIMB_OFFSET_RATIO, rest_angle

FRONT = {"view": "front", "rest_pose": "A_pose"}
SIDE = {"view": "side", "rest_pose": "side_neutral"}
EVERYTHING_FRONT = ["chest", "neck", "spine_2", "hands", "shoulders", "jaw"]
EVERYTHING_SIDE = ["chest", "neck", "spine_2", "hands", "toes", "jaw"]


def subsets(view):
    tokens = [t for t in OPTIONAL_TOKENS if view in token_views(t)]
    for size in range(len(tokens) + 1):
        yield from itertools.combinations(tokens, size)


@pytest.mark.parametrize("kw", [FRONT, {"view": "front", "rest_pose": "T_pose"}, SIDE])
def test_placed_bones_are_exactly_the_present_ones(kw):
    for tokens in subsets(kw["view"]):
        placed, _ = layout(make_spec(optional_bones=list(tokens), **kw))
        assert set(placed) == present_bones(tokens)


@pytest.mark.parametrize("kw", [FRONT, {"view": "front", "rest_pose": "T_pose"}, SIDE])
def test_every_child_starts_on_its_parents_tail_except_the_known_exceptions(kw):
    for tokens in subsets(kw["view"]):
        placed, _ = layout(make_spec(optional_bones=list(tokens), **kw))
        for name, bone in placed.items():
            if bone.parent is None or name in EXEMPT_FROM_PARENT_TAIL or is_limb_root(name, placed):
                continue
            assert parent_tail_gap(name, placed) < 1e-9, (tokens, name)


@pytest.mark.parametrize("kw", [FRONT, SIDE])
def test_the_head_top_is_at_the_full_height(kw):
    placed, props = layout(
        make_spec(optional_bones=EVERYTHING_SIDE if kw is SIDE else EVERYTHING_FRONT, **kw)
    )
    assert placed["head"].tail[1] == pytest.approx(props.height)
    assert placed["head"].tail[0] == pytest.approx(0)


def test_no_neck_still_reaches_the_full_height():
    for kw in (FRONT, SIDE):
        placed, props = layout(make_spec(**kw))
        assert "neck" not in placed
        assert placed["head"].tail[1] == pytest.approx(props.height)


def test_root_hip_and_legs_are_placed_at_the_ground_and_hip_joint():
    placed, props = layout(make_spec(**FRONT))
    assert placed["root"].head == (0.0, 0.0) and placed["root"].angle == 90
    assert placed["hip"].head == pytest.approx((0.0, props.leg_length))
    assert placed["shin_L"].tail[1] == pytest.approx(props.ankle_height)
    assert placed["foot_L"].head[1] == pytest.approx(props.ankle_height)


def test_bone_lengths_come_from_the_resolved_proportions():
    placed, props = layout(make_spec(optional_bones=EVERYTHING_FRONT, **FRONT))
    for name, expected in {
        "hip": props.hip, "spine": props.spine, "spine_2": props.spine_2, "chest": props.chest,
        "neck": props.neck, "head": props.head, "upper_arm_L": props.upper_arm,
        "forearm_R": props.forearm, "hand_L": props.hand, "thigh_R": props.thigh,
        "shin_L": props.shin, "foot_R": props.foot, "jaw": props.jaw,
    }.items():  # fmt: skip
        assert placed[name].length == pytest.approx(expected), name


def test_bones_point_along_their_rest_angles():
    for kw in (FRONT, {"view": "front", "rest_pose": "T_pose"}, SIDE):
        tokens = EVERYTHING_SIDE if kw["view"] == "side" else EVERYTHING_FRONT
        spec = make_spec(optional_bones=tokens, **kw)
        placed, _ = layout(spec)
        for name, bone in placed.items():
            assert bone.angle == pytest.approx(rest_angle(name, spec.rest_pose)), name


# ---- front view ----------------------------------------------------------------------------


def test_front_pairs_mirror_across_the_y_axis():
    for pose in ("A_pose", "T_pose"):
        spec = make_spec(optional_bones=EVERYTHING_FRONT, view="front", rest_pose=pose)
        placed, _ = layout(spec)
        for name in placed:
            if name.endswith("_L"):
                left, right = placed[name], placed[name[:-2] + "_R"]
                assert right.head == pytest.approx((-left.head[0], left.head[1])), name
                assert right.tail == pytest.approx((-left.tail[0], left.tail[1])), name
                assert right.length == pytest.approx(left.length)


def test_front_left_is_on_the_positive_x_side():
    placed, _ = layout(make_spec(**FRONT))
    assert placed["upper_arm_L"].head[0] > 0 > placed["upper_arm_R"].head[0]
    assert placed["thigh_L"].head[0] > 0 > placed["thigh_R"].head[0]


def test_limb_roots_sit_at_their_offsets():
    placed, props = layout(make_spec(**FRONT))
    top_y = placed["spine"].tail[1]
    assert placed["upper_arm_L"].head[0] == pytest.approx(props.shoulder_width / 2)
    assert placed["upper_arm_L"].head[1] < top_y
    assert placed["thigh_L"].head == pytest.approx((props.hip_spacing / 2, props.leg_length))


def test_shoulder_bone_geometry():
    placed, props = layout(make_spec(optional_bones=["shoulders"], **FRONT))
    shoulder, arm = placed["shoulder_L"], placed["upper_arm_L"]
    assert shoulder.head == pytest.approx(placed["spine"].tail)
    assert shoulder.angle == pytest.approx(-10)
    assert shoulder.length == pytest.approx((props.shoulder_width / 2) / 0.984807753)
    assert arm.head == pytest.approx(shoulder.tail)
    assert parent_tail_gap("upper_arm_L", placed) < 1e-9
    assert placed["shoulder_R"].angle == pytest.approx(-170)


def test_shoulder_joint_is_the_same_with_or_without_shoulder_bones():
    without, _ = layout(make_spec(**FRONT))
    with_bones, _ = layout(make_spec(optional_bones=["shoulders"], **FRONT))
    assert without["upper_arm_L"].head == pytest.approx(with_bones["upper_arm_L"].head)


def test_a_pose_and_t_pose_arms():
    a, _ = layout(make_spec(view="front", rest_pose="A_pose"))
    t, _ = layout(make_spec(view="front", rest_pose="T_pose"))
    assert a["upper_arm_L"].tail[1] < a["upper_arm_L"].head[1]
    assert t["upper_arm_L"].tail[1] == pytest.approx(t["upper_arm_L"].head[1])
    assert t["upper_arm_L"].tail[0] > a["upper_arm_L"].tail[0]


def test_front_limbs_are_slightly_in_front_and_the_torso_is_on_the_plane():
    placed, _ = layout(make_spec(optional_bones=EVERYTHING_FRONT, **FRONT))
    for name, bone in placed.items():
        limb = name.split("_")[0] in {"upper", "forearm", "hand", "thigh", "shin", "foot"}
        assert bone.depth == (1 if limb else 0), name


def test_without_hands_the_arm_ends_at_the_forearm():
    placed, props = layout(make_spec(**FRONT))
    assert "hand_L" not in placed
    total = distance(placed["upper_arm_L"].head, placed["forearm_L"].tail)
    assert total == pytest.approx(props.arm_length)


def test_with_hands_the_arm_spans_the_full_arm_length():
    placed, props = layout(make_spec(optional_bones=["hands"], **FRONT))
    assert distance(placed["upper_arm_L"].head, placed["hand_L"].tail) == pytest.approx(
        props.arm_length
    )


def test_front_feet_point_away_from_the_center_line():
    placed, _ = layout(make_spec(**FRONT))
    assert placed["foot_L"].tail[0] > placed["foot_L"].head[0]
    assert placed["foot_R"].tail[0] < placed["foot_R"].head[0]


def test_jaw_pivots_on_the_head_bone():
    placed, props = layout(make_spec(optional_bones=["jaw"], **FRONT))
    head, jaw = placed["head"], placed["jaw"]
    assert jaw.parent == "head"
    assert jaw.head[1] == pytest.approx(head.head[1] + 0.35 * head.length)
    assert jaw.head[0] == pytest.approx(0)
    assert jaw.tail[1] < jaw.head[1]
    assert jaw.length == pytest.approx(props.jaw)


# ---- side view -----------------------------------------------------------------------------


def test_side_view_is_a_single_column_with_far_limbs_offset_behind():
    placed, props = layout(make_spec(optional_bones=EVERYTHING_SIDE, **SIDE))
    offset = FAR_LIMB_OFFSET_RATIO * props.height
    for name in [n for n in placed if n.endswith("_R")]:
        near, far = placed[name], placed[name[:-2] + "_L"]  # _R is the near side, _L the far side
        assert near.head[0] - far.head[0] == pytest.approx(offset), name
        assert near.head[1] == pytest.approx(far.head[1]), name
        assert near.length == pytest.approx(far.length)
        assert near.angle == pytest.approx(far.angle)


def test_side_near_arm_is_a_normal_connected_bone_and_far_arm_is_offset():
    placed, props = layout(make_spec(**SIDE))
    assert parent_tail_gap("upper_arm_R", placed) < 1e-9
    far_gap = parent_tail_gap("upper_arm_L", placed)
    assert far_gap == pytest.approx(FAR_LIMB_OFFSET_RATIO * props.height)


def test_side_depth_order():
    placed, _ = layout(make_spec(optional_bones=EVERYTHING_SIDE, **SIDE))
    limbs = ("upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe")
    for name, bone in placed.items():
        base = name.rsplit("_", 1)[0]
        if base in limbs:
            assert bone.depth == (1 if name.endswith("_R") else -1), name
        else:
            assert bone.depth == 0, name


def test_side_arms_hang_slightly_forward_and_feet_point_forward():
    placed, _ = layout(make_spec(optional_bones=EVERYTHING_SIDE, **SIDE))
    assert placed["upper_arm_L"].tail[0] > placed["upper_arm_L"].head[0]
    assert placed["foot_L"].tail[0] > placed["foot_L"].head[0]
    assert placed["foot_R"].tail[0] > placed["foot_R"].head[0]
    assert placed["toe_L"].head == pytest.approx(placed["foot_L"].tail)


def test_side_jaw_points_forward_and_down():
    placed, _ = layout(make_spec(optional_bones=["jaw"], **SIDE))
    jaw = placed["jaw"]
    assert jaw.tail[0] > jaw.head[0] and jaw.tail[1] < jaw.head[1]


def test_expand_optional_matches_what_gets_placed():
    placed, _ = layout(make_spec(optional_bones=["hands", "toes"], **SIDE))
    assert set(expand_optional(["hands", "toes"])) <= set(placed)


def test_facing_right_the_right_limbs_are_near_the_camera():
    """A character facing right shows its right side to the viewer (LLD 2.2)."""
    placed, _ = layout(make_spec(optional_bones=["hands"], **SIDE))
    for base in ("upper_arm", "forearm", "hand", "thigh", "shin", "foot"):
        assert placed[f"{base}_R"].depth > placed["spine"].depth > placed[f"{base}_L"].depth, base
    assert placed["thigh_L"].head[0] < placed["thigh_R"].head[0]  # the far leg is pushed back (-X)
    assert placed["thigh_R"].head[0] == 0
