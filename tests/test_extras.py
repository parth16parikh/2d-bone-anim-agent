import math
from itertools import pairwise

import pytest

from layout_helpers import layout, make_spec
from rig_agent.builder.errors import BuildError
from rig_agent.builder.extras import chain_names, place_extras
from rig_agent.builder.geometry import distance, mirror_angle, mirror_x
from rig_agent.vocabulary.poses import FAR_LIMB_OFFSET_RATIO

FRONT = {"view": "front", "rest_pose": "A_pose", "optional_bones": ["chest", "neck", "hands"]}
SIDE = {"view": "side", "rest_pose": "side_neutral", "optional_bones": ["chest", "neck", "hands"]}


def extra(**kw):
    data = {"name": "extra_cape", "parent": "chest", "direction_deg": -90, "length_ratio": 0.3}
    data.update(kw)
    return data


def build(extras, **base):
    spec = make_spec(extra_bones=extras, **(base or FRONT))
    canonical, _ = layout(spec)
    return place_extras(spec, canonical), canonical, spec


def test_chain_names():
    assert chain_names("extra_cape", 1) == ["extra_cape"]
    assert chain_names("extra_cape", 3) == ["extra_cape_1", "extra_cape_2", "extra_cape_3"]
    assert chain_names("extra_ponytail", 1, "L") == ["extra_ponytail_L"]
    assert chain_names("extra_ponytail", 2, "R") == ["extra_ponytail_1_R", "extra_ponytail_2_R"]


def test_no_extras_gives_nothing():
    assert build([])[0] == {}


def test_single_bone_hangs_from_the_parent_tail():
    extras, canonical, spec = build([extra(direction_deg=-90, length_ratio=0.3)])
    cape = extras["extra_cape"]
    assert cape.parent == "chest"
    assert cape.head == pytest.approx(canonical["chest"].tail)
    assert cape.angle == -90
    assert cape.length == pytest.approx(0.3 * spec.height_units)
    assert cape.tail == pytest.approx((cape.head[0], cape.head[1] - cape.length))


def test_attach_at_head_starts_on_the_parent_head():
    extras, canonical, _ = build([extra(attach_at="head")])
    assert extras["extra_cape"].head == pytest.approx(canonical["chest"].head)


def test_chain_splits_the_total_length_equally_and_connects():
    extras, canonical, spec = build([extra(segments=3, length_ratio=0.3, direction_deg=-60)])
    names = ["extra_cape_1", "extra_cape_2", "extra_cape_3"]
    assert list(extras) == names
    assert [extras[n].parent for n in names] == ["chest", "extra_cape_1", "extra_cape_2"]
    assert extras[names[0]].head == pytest.approx(canonical["chest"].tail)
    for a, b in pairwise(names):
        assert extras[b].head == pytest.approx(extras[a].tail)
    for n in names:
        assert extras[n].length == pytest.approx(0.3 * spec.height_units / 3)
        assert extras[n].angle == -60
    assert distance(extras[names[0]].head, extras[names[2]].tail) == pytest.approx(0.6)


def test_extras_inherit_the_parents_depth_and_carry_the_layer():
    extras, canonical, _ = build([extra(layer="behind", segments=2)])
    assert canonical["chest"].depth == 0
    assert {b.depth for b in extras.values()} == {0}
    assert {b.layer for b in extras.values()} == {"behind"}
    on_arm, canonical, _ = build([extra(name="extra_ring", parent="hand_L")])
    assert on_arm["extra_ring"].depth == canonical["hand_L"].depth == 1
    assert on_arm["extra_ring"].layer == "front"


def test_an_extra_can_hang_from_an_earlier_extra():
    extras, _, _ = build([extra(), extra(name="extra_tassel", parent="extra_cape")])
    assert extras["extra_tassel"].parent == "extra_cape"
    assert extras["extra_tassel"].head == pytest.approx(extras["extra_cape"].tail)


def test_an_unknown_parent_is_a_build_error():
    with pytest.raises(BuildError, match="unknown parent.*'wing'"):
        build([extra(parent="wing")])


def test_a_parent_that_is_not_in_the_rig_is_a_build_error():
    with pytest.raises(BuildError, match="'hand_L'"):
        build([extra(parent="hand_L")], view="front", rest_pose="A_pose")


def test_a_later_extra_cannot_be_used_as_an_earlier_parent():
    with pytest.raises(BuildError):
        build([extra(name="extra_a", parent="extra_b"), extra(name="extra_b")])


# ---- mirroring, front view -----------------------------------------------------------------


def test_front_mirror_on_a_center_bone_reflects_the_chain():
    extras, _, _ = build(
        [extra(name="extra_hair", parent="head", direction_deg=-45, segments=2, mirror=True)]
    )
    assert list(extras) == ["extra_hair_1_L", "extra_hair_2_L", "extra_hair_1_R", "extra_hair_2_R"]
    for i in (1, 2):
        left, right = extras[f"extra_hair_{i}_L"], extras[f"extra_hair_{i}_R"]
        assert left.angle == pytest.approx(-45)
        assert right.angle == pytest.approx(mirror_angle(-45))
        assert right.head == pytest.approx(mirror_x(left.head))
        assert right.tail == pytest.approx(mirror_x(left.tail))
        assert right.length == pytest.approx(left.length)
        assert right.depth == left.depth and right.layer == left.layer
    assert extras["extra_hair_1_L"].parent == extras["extra_hair_1_R"].parent == "head"
    assert extras["extra_hair_2_R"].parent == "extra_hair_1_R"


def test_front_mirror_names_the_bone_pointing_to_plus_x_as_left():
    toward_plus_x, _, _ = build([extra(parent="head", direction_deg=-30, mirror=True)])
    toward_minus_x, _, _ = build([extra(parent="head", direction_deg=-150, mirror=True)])
    assert toward_plus_x["extra_cape_L"].tail[0] > 0 > toward_plus_x["extra_cape_R"].tail[0]
    assert toward_minus_x["extra_cape_R"].tail[0] < 0 < toward_minus_x["extra_cape_L"].tail[0]
    assert toward_minus_x["extra_cape_R"].angle == -150


def test_front_mirror_on_a_sided_parent_attaches_to_the_opposite_bone():
    extras, canonical, _ = build(
        [extra(name="extra_glove", parent="hand_L", direction_deg=-90, mirror=True)]
    )
    left, right = extras["extra_glove_L"], extras["extra_glove_R"]
    assert (left.parent, right.parent) == ("hand_L", "hand_R")
    assert left.head == pytest.approx(canonical["hand_L"].tail)
    assert right.head == pytest.approx(canonical["hand_R"].tail)
    assert right.head == pytest.approx(mirror_x(left.head))
    assert right.depth == left.depth == 1


def test_front_mirror_on_the_right_parent_names_the_original_right():
    extras, _, _ = build([extra(name="extra_glove", parent="hand_R", mirror=True)])
    assert extras["extra_glove_R"].parent == "hand_R"
    assert extras["extra_glove_L"].parent == "hand_L"


def test_a_vertical_mirrored_chain_on_a_center_bone_coincides():
    extras, _, _ = build([extra(parent="head", direction_deg=90, mirror=True)])
    left, right = extras["extra_cape_L"], extras["extra_cape_R"]
    assert left.head == pytest.approx(right.head) and left.tail == pytest.approx(right.tail)


def test_mirroring_a_parent_that_has_no_twin_is_a_build_error():
    spec = make_spec(extra_bones=[extra(parent="hand_L", mirror=True)], **FRONT)
    canonical, _ = layout(spec)
    del canonical["hand_R"]
    with pytest.raises(BuildError, match="no twin.*'hand_R'"):
        place_extras(spec, canonical)


# ---- mirroring, side view ------------------------------------------------------------------


def test_side_mirror_on_a_center_bone_is_a_near_far_pair():
    extras, canonical, spec = build(
        [extra(name="extra_ear", parent="head", direction_deg=60, mirror=True)], **SIDE
    )
    near, far = extras["extra_ear_R"], extras["extra_ear_L"]  # the right side faces the camera
    offset = FAR_LIMB_OFFSET_RATIO * spec.height_units
    assert near.angle == far.angle == 60
    assert near.head[0] - far.head[0] == pytest.approx(offset)
    assert near.head[1] == pytest.approx(far.head[1])
    assert near.depth == canonical["head"].depth == 0
    assert far.depth == -1
    assert near.parent == far.parent == "head"


def test_side_mirror_on_a_sided_parent_uses_the_far_limb():
    extras, canonical, _ = build([extra(name="extra_glove", parent="hand_R", mirror=True)], **SIDE)
    near, far = extras["extra_glove_R"], extras["extra_glove_L"]
    assert (near.parent, far.parent) == ("hand_R", "hand_L")
    assert near.head == pytest.approx(canonical["hand_R"].tail)
    assert far.head == pytest.approx(canonical["hand_L"].tail)
    assert (near.depth, far.depth) == (1, -1)


def test_side_non_mirrored_extra_on_the_far_arm_is_behind():
    extras, _, _ = build([extra(name="extra_ring", parent="hand_L")], **SIDE)  # _L is the far side
    assert extras["extra_ring"].depth == -1


def test_side_non_mirrored_extra_on_the_near_arm_is_in_front():
    extras, _, _ = build([extra(name="extra_ring", parent="hand_R")], **SIDE)
    assert extras["extra_ring"].depth == 1


def test_mirrored_chains_count_all_their_bones():
    extras, _, spec = build([extra(segments=4, mirror=True, parent="head", direction_deg=-30)])
    assert len(extras) == 8
    assert all(math.isclose(b.length, 0.3 * spec.height_units / 4) for b in extras.values())
