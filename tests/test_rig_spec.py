from typing import get_args

import pytest
from pydantic import ValidationError

from rig_agent.schemas.rig_spec import (
    ExtraBoneSpec,
    OptionalBone,
    RigSpec,
    extra_bone_count,
)
from rig_agent.vocabulary.bones import OPTIONAL_TOKENS


def spec(**overrides):
    data = {
        "character_summary": "a knight",
        "style": "heroic knight",
        "view": "front",
        "rest_pose": "A_pose",
    }
    data.update(overrides)
    return RigSpec.model_validate(data)


def extra(**overrides):
    data = {"name": "extra_cape", "parent": "chest", "direction_deg": -90, "length_ratio": 0.3}
    data.update(overrides)
    return data


def test_minimal_spec_uses_the_defaults():
    s = spec()
    assert s.preset == "realistic"
    assert s.height_units == 2.0
    assert s.optional_bones == [] and s.extra_bones == []
    assert s.base.heads_tall is None
    assert s.overrides.leg_scale == 1.0


def test_optional_bone_literal_matches_the_vocabulary():
    assert set(get_args(OptionalBone)) == set(OPTIONAL_TOKENS)


def test_defaults_are_not_shared_between_instances():
    a, b = spec(), spec()
    a.overrides.leg_scale = 1.2
    assert b.overrides.leg_scale == 1.0


@pytest.mark.parametrize(
    ("view", "pose"),
    [("front", "side_neutral"), ("side", "A_pose"), ("side", "T_pose")],
)
def test_pose_must_match_view(view, pose):
    with pytest.raises(ValidationError, match="side_neutral"):
        spec(view=view, rest_pose=pose)


@pytest.mark.parametrize(
    ("view", "pose"), [("front", "A_pose"), ("front", "T_pose"), ("side", "side_neutral")]
)
def test_valid_view_and_pose_pairs(view, pose):
    assert spec(view=view, rest_pose=pose).rest_pose == pose


def test_shoulders_are_front_only():
    assert spec(optional_bones=["shoulders"]).optional_bones == ["shoulders"]
    with pytest.raises(ValidationError, match="shoulders"):
        spec(view="side", rest_pose="side_neutral", optional_bones=["shoulders"])


def test_toes_are_side_only():
    assert spec(view="side", rest_pose="side_neutral", optional_bones=["toes"])
    with pytest.raises(ValidationError, match="toes"):
        spec(optional_bones=["toes"])


def test_shoulder_width_is_front_only():
    side = {"view": "side", "rest_pose": "side_neutral"}
    with pytest.raises(ValidationError, match="shoulder width"):
        spec(**side, overrides={"shoulder_width_scale": 1.2})
    with pytest.raises(ValidationError, match="shoulder width"):
        spec(**side, base={"shoulder_width_hu": 2.0})
    assert spec(overrides={"shoulder_width_scale": 1.2}, base={"shoulder_width_hu": 2.0})


@pytest.mark.parametrize(
    ("field", "value"),
    [("head_scale", 1.6), ("leg_scale", 0.4), ("thigh_shin_bias", 1.4), ("chest_bias", 0.6)],
)
def test_override_ranges(field, value):
    with pytest.raises(ValidationError):
        spec(overrides={field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("heads_tall", 1.5), ("heads_tall", 11), ("leg_ratio", 0.7), ("arm_ratio", 0.2)],
)
def test_base_bounds_follow_the_plausibility_bands(field, value):
    with pytest.raises(ValidationError):
        spec(base={field: value})


def test_base_values_at_the_bounds_are_accepted():
    s = spec(base={"heads_tall": 2.0, "leg_ratio": 0.6})
    assert s.base.heads_tall == 2.0


def test_style_is_a_free_label_with_a_length_limit():
    assert spec(style="gaunt").style == "gaunt"
    with pytest.raises(ValidationError):
        spec(style="x" * 41)
    with pytest.raises(ValidationError):
        spec(style="")


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        spec(unexpected=1)


def test_unknown_optional_token_is_rejected():
    with pytest.raises(ValidationError):
        spec(optional_bones=["shoulder_L"])


@pytest.mark.parametrize("name", ["cape", "extra_", "extra_Cape", "extra_a-b"])
def test_extra_bone_name_pattern(name):
    with pytest.raises(ValidationError):
        spec(extra_bones=[extra(name=name)])


def test_extra_bone_ranges():
    for bad in (
        {"length_ratio": 0.005},
        {"length_ratio": 0.7},
        {"segments": 5},
        {"direction_deg": 200},
    ):
        with pytest.raises(ValidationError):
            spec(extra_bones=[extra(**bad)])


def test_extra_bone_defaults():
    e = ExtraBoneSpec.model_validate(extra())
    assert (e.attach_at, e.segments, e.layer, e.mirror) == ("tail", 1, "front", False)


def test_extra_bone_count_includes_segments_and_mirrors():
    extras = [
        ExtraBoneSpec.model_validate(extra(segments=3, mirror=True)),
        ExtraBoneSpec.model_validate(extra(name="extra_sword")),
    ]
    assert extra_bone_count(extras) == 7
    assert extra_bone_count([]) == 0


def test_budget_of_sixteen_bones_is_accepted():
    four_chains = [extra(name=f"extra_hair_{i}", segments=4) for i in range(4)]
    assert extra_bone_count(spec(extra_bones=four_chains).extra_bones) == 16


def test_budget_over_sixteen_bones_is_rejected():
    chains = [extra(name=f"extra_hair_{i}", segments=4) for i in range(4)]
    with pytest.raises(ValidationError, match="total 17"):
        spec(extra_bones=chains + [extra(name="extra_sword")])


def test_mirrors_count_double_toward_the_budget():
    with pytest.raises(ValidationError, match="total 18"):
        spec(extra_bones=[extra(name=f"extra_hair_{i}", segments=3, mirror=True) for i in range(3)])


def test_more_than_sixteen_entries_is_rejected():
    with pytest.raises(ValidationError):
        spec(extra_bones=[extra(name=f"extra_b{i}") for i in range(17)])


def test_assumptions_are_limited_to_five():
    assert spec(assumptions=["a"] * 5)
    with pytest.raises(ValidationError):
        spec(assumptions=["a"] * 6)


def test_json_round_trip_and_json_schema():
    s = spec(
        optional_bones=["chest", "neck", "hands"],
        extra_bones=[extra(mirror=True, layer="behind")],
        base={"heads_tall": 9},
        overrides={"leg_scale": 1.15},
    )
    assert RigSpec.model_validate_json(s.model_dump_json()) == s
    schema = RigSpec.model_json_schema()
    assert schema["properties"]["preset"]["default"] == "realistic"
