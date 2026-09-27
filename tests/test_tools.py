import json

import pytest
from pydantic_ai import Tool

from layout_helpers import make_spec
from rig_agent.agent.tools import (
    PLANNER_TOOLS,
    describe_proportions,
    dry_run_validate,
    get_preset,
    get_view_rules,
    list_existing_bones,
    list_vocabulary,
)
from rig_agent.schemas.validation import IssueCode
from rig_agent.vocabulary.presets import PRESETS

FRONT = {"view": "front", "rest_pose": "A_pose"}
SIDE = {"view": "side", "rest_pose": "side_neutral"}


def extra(**kw):
    data = {"name": "extra_cape", "parent": "chest", "direction_deg": -90, "length_ratio": 0.3}
    data.update(kw)
    return data


# ---- list_vocabulary -----------------------------------------------------------------------------


def test_vocabulary_is_json_and_lists_the_required_bones():
    vocab = list_vocabulary()
    json.dumps(vocab)
    assert len(vocab["required_bones"]) == 14 and vocab["required_bones"][0] == "root"
    assert len(vocab["bones"]) == 24
    assert vocab["limits"]["max_extra_bones"] == 16 and vocab["limits"]["max_total_bones"] == 40
    assert vocab["presets"] == list(PRESETS)


def test_vocabulary_optional_tokens_say_what_they_add_and_where():
    tokens = list_vocabulary()["optional_tokens"]
    assert tokens["hands"] == {"adds": ["hand_L", "hand_R"], "views": ["front", "side"]}
    assert tokens["shoulders"]["views"] == ["front"] and tokens["toes"]["views"] == ["side"]
    assert set(tokens) == {"chest", "neck", "spine_2", "hands", "shoulders", "toes", "jaw"}


def test_vocabulary_explains_parents_and_naming():
    vocab = list_vocabulary()
    assert any("torso top" in rule for rule in vocab["parent_rules"])
    assert "extra_" in vocab["naming"]["extra_bones"]


# ---- get_preset / get_view_rules -----------------------------------------------------------------


@pytest.mark.parametrize("name", list(PRESETS))
def test_preset_matches_the_table(name):
    result = get_preset(name)
    json.dumps(result)
    p = PRESETS[name]
    assert result["name"] == name
    assert result["base"] == {
        "heads_tall": p.heads_tall,
        "shoulder_width_hu": p.shoulder_width_hu,
        "hip_spacing_hu": p.hip_spacing_hu,
        "leg_ratio": p.leg_ratio,
        "arm_ratio": p.arm_ratio,
    }
    assert result["arm_split_upper_forearm_hand"] == list(p.arm_split)
    assert result["torso_split_hip_spine_chest"] == list(p.torso_split)


def test_view_rules_front():
    rules = get_view_rules("front")
    assert rules["rest_poses"] == ["A_pose", "T_pose"] and rules["shoulder_width_applies"]
    assert "shoulders" in rules["optional_bones_available"]
    assert rules["optional_bones_not_available"] == ["toes"]


def test_view_rules_side():
    rules = get_view_rules("side")
    assert rules["rest_poses"] == ["side_neutral"] and not rules["shoulder_width_applies"]
    assert "toes" in rules["optional_bones_available"]
    assert rules["optional_bones_not_available"] == ["shoulders"]
    assert "negative" in rules["depth"]


def test_view_rules_do_not_leak_state_between_calls():
    get_view_rules("front")["view"] = "changed"
    assert get_view_rules("front")["view"] == "front"


# ---- describe_proportions ------------------------------------------------------------------------


def test_a_default_spec_has_no_warnings():
    result = describe_proportions(make_spec(optional_bones=["chest", "neck", "hands"], **FRONT))
    json.dumps(result)
    assert result["warnings"] == [] and result["height"] == 2.0
    assert result["derived"]["heads_tall"] == {
        "value": 7.5,
        "plausible": [2.0, 10.0],
        "in_range": True,
    }
    assert result["lengths"]["leg_hip_to_ground"] == pytest.approx(0.94)


def test_out_of_range_values_become_warnings():
    result = describe_proportions(
        make_spec(overrides={"head_scale": 0.5, "foot_size": 1.5}, **FRONT)
    )
    assert any("foot_length_hu" in w for w in result["warnings"])
    assert result["derived"]["foot_length_hu"]["in_range"] is False


def test_side_view_leaves_out_the_shoulder_width():
    assert "shoulder_width_hu" not in describe_proportions(make_spec(**SIDE))["derived"]
    assert "shoulder_width_hu" in describe_proportions(make_spec(**FRONT))["derived"]


def test_impossible_proportions_return_an_error_instead_of_raising():
    result = describe_proportions(make_spec(base={"heads_tall": 2.0, "leg_ratio": 0.6}, **FRONT))
    assert "no room for a torso" in result["error"]


def test_a_default_spec_reports_ratios_between_the_main_parts():
    result = describe_proportions(make_spec(optional_bones=["chest", "neck", "hands"], **FRONT))
    ratios = result["ratios"]
    assert set(ratios) == {"head_to_rest_of_body", "leg_to_arm", "leg_to_torso", "arm_to_torso"}
    assert ratios["head_to_rest_of_body"] == pytest.approx(0.154, abs=1e-3)
    assert all(v is not None for v in ratios.values())


def test_pushing_heads_tall_and_the_limb_ratios_to_their_floor_maximises_the_head_ratio():
    result = describe_proportions(
        make_spec(
            optional_bones=["hands"],
            base={"heads_tall": 2.0, "leg_ratio": 0.25, "arm_ratio": 0.25},
            **FRONT,
        )
    )
    assert result["warnings"] == []
    assert result["ratios"]["head_to_rest_of_body"] == pytest.approx(1.857, abs=1e-3)


def test_dropping_neck_grows_the_head_ratio_further_than_keeping_it():
    common = {"base": {"heads_tall": 2.0, "leg_ratio": 0.25, "arm_ratio": 0.25}, **FRONT}
    without_neck = describe_proportions(make_spec(optional_bones=["hands"], **common))
    with_neck = describe_proportions(make_spec(optional_bones=["hands", "neck"], **common))
    assert (
        without_neck["ratios"]["head_to_rest_of_body"] > with_neck["ratios"]["head_to_rest_of_body"]
    )


# ---- dry_run_validate ----------------------------------------------------------------------------


def test_a_good_spec_passes_the_dry_run():
    report = dry_run_validate(make_spec(optional_bones=["chest"], extra_bones=[extra()], **FRONT))
    assert report.passed and report.issues == []


def test_the_dry_run_reports_validator_errors():
    spec = make_spec(extra_bones=[extra(parent="head", direction_deg=90, mirror=True)], **FRONT)
    report = dry_run_validate(spec)
    assert not report.passed and report.has(IssueCode.MIRROR_COINCIDENT)


def test_the_dry_run_reports_unbuildable_specs():
    spec = make_spec(base={"heads_tall": 2.0, "leg_ratio": 0.6}, **FRONT)
    report = dry_run_validate(spec)
    assert [i.code for i in report.issues] == [IssueCode.UNBUILDABLE]


def test_the_dry_run_names_a_missing_parent():
    report = dry_run_validate(make_spec(extra_bones=[extra(parent="chest")], **FRONT))
    issue = report.issues[0]
    assert issue.code == IssueCode.UNBUILDABLE and "'chest'" in issue.message


def test_the_report_is_json():
    json.loads(dry_run_validate(make_spec(**FRONT)).model_dump_json())


# ---- list_existing_bones -------------------------------------------------------------------------


def test_existing_bones_lists_canonical_in_table_order_and_resolved_extras():
    spec = make_spec(
        optional_bones=["chest", "neck"],
        extra_bones=[extra(name="extra_hair", parent="head", segments=2, mirror=True)],
        **FRONT,
    )
    result = list_existing_bones(spec)
    assert result["canonical"][:7] == [
        "root",
        "hip",
        "spine",
        "chest",
        "neck",
        "head",
        "upper_arm_L",
    ]
    assert result["extra"] == [
        "extra_hair_1_L",
        "extra_hair_2_L",
        "extra_hair_1_R",
        "extra_hair_2_R",
    ]
    assert "error" not in result


def test_existing_bones_reports_a_build_error():
    result = list_existing_bones(make_spec(extra_bones=[extra(parent="chest")], **FRONT))
    assert "'chest'" in result["error"] and result["extra"] == []
    assert "chest" not in result["canonical"]


def test_existing_bones_respects_the_view():
    canonical = list_existing_bones(make_spec(optional_bones=["toes"], **SIDE))["canonical"]
    assert "toe_L" in canonical and "shoulder_L" not in canonical


# ---- registration --------------------------------------------------------------------------------


def test_every_tool_is_documented_and_registerable():
    assert [t.__name__ for t in PLANNER_TOOLS] == [
        "list_vocabulary", "get_preset", "get_view_rules",
        "describe_proportions", "dry_run_validate", "list_existing_bones",
    ]  # fmt: skip
    for fn in PLANNER_TOOLS:
        assert fn.__doc__ and len(fn.__doc__) > 40
        tool = Tool(fn)
        assert tool.function_schema.json_schema["type"] == "object"


def test_spec_taking_tools_take_the_rigspec_fields_as_their_arguments():
    schema = Tool(dry_run_validate).function_schema.json_schema
    assert {"character_summary", "view", "optional_bones", "extra_bones"} <= set(
        schema["properties"]
    )
    assert {"character_summary", "style", "view", "rest_pose"} <= set(schema["required"])


def test_the_docstring_warns_against_combining_head_scale_with_a_floored_heads_tall():
    doc = describe_proportions.__doc__
    assert (
        "big neck_hu for that donation reaches the biggest head a valid rig can have. Leave head_scale"
        in doc
    )
    assert (
        "values, not the numbers you typed, and head_scale above 1.0 shrinks the whole column further,"
        in doc
    )


def test_head_scale_above_1_pushes_the_derived_heads_tall_below_its_own_floor():
    """Pins the exact failure a live run hit: heads_tall/leg_ratio/arm_ratio at their floor,
    plus a head_scale bump on top, silently breaks the very floors it looks like it should help."""
    at_floor = describe_proportions(
        make_spec(
            optional_bones=["hands"],
            base={"heads_tall": 2.0, "leg_ratio": 0.25, "arm_ratio": 0.25},
            **FRONT,
        )
    )
    assert at_floor["warnings"] == []

    with_head_scale = describe_proportions(
        make_spec(
            optional_bones=["hands"],
            base={"heads_tall": 2.0, "leg_ratio": 0.25, "arm_ratio": 0.25},
            overrides={"head_scale": 1.3},
            **FRONT,
        )
    )
    assert with_head_scale["derived"]["heads_tall"]["in_range"] is False
    assert with_head_scale["derived"]["leg_ratio"]["in_range"] is False
    assert with_head_scale["derived"]["heads_tall"]["value"] < 2.0
