import json

import pytest
from pydantic import ValidationError

from rig_agent.schemas.skeleton import Bone, Skeleton

# The example from LLD 3.5b.
LLD_EXAMPLE = {
    "schema_version": "1.1",
    "rig_name": "lanky_elf_archer",
    "source_prompt": "a tall, lanky elf archer with a long cape",
    "units": "unity_world",
    "pixels_per_unit": 100,
    "height": 2.0,
    "view": "front",
    "facing": None,
    "rest_pose": "A_pose",
    "style": "stylized",
    "bones": [
        {
            "id": 0,
            "name": "root",
            "parent_id": -1,
            "world_head": [0.0, 0.0],
            "world_tail": [0.0, 0.05],
            "local_position": [0.0, 0.0],
            "local_rotation_deg": 90.0,
            "length": 0.05,
            "depth": 0,
            "layer": None,
            "rotation_limits_deg": None,
            "ik_chain": None,
            "mirror_of": None,
        },
        {
            "id": 7,
            "name": "forearm_L",
            "parent_id": 6,
            "world_head": [0.41, 1.38],
            "world_tail": [0.643, 1.147],
            "local_position": [0.29, 0.0],
            "local_rotation_deg": 0.0,
            "length": 0.33,
            "depth": 1,
            "layer": None,
            "rotation_limits_deg": [0, 150],
            "ik_chain": "arm_L",
            "mirror_of": "forearm_R",
        },
    ],
    "ik_chains": [
        {
            "name": "arm_L",
            "root": "upper_arm_L",
            "joint": "forearm_L",
            "effector": "hand_L",
            "bend_side": "right",
        }
    ],
    "metadata": {
        "generator": "rig-agent/0.1",
        "model": "<provider:model>",
        "iterations": 2,
        "assumptions": ["'lanky' → arm/leg scale 1.15"],
    },
}


def test_lld_example_round_trips_unchanged():
    skeleton = Skeleton.model_validate(LLD_EXAMPLE)
    assert skeleton.model_dump(mode="json") == LLD_EXAMPLE


def test_a_1_0_file_without_ik_chains_is_still_read():
    old = {k: v for k, v in LLD_EXAMPLE.items() if k != "ik_chains"} | {"schema_version": "1.0"}
    skeleton = Skeleton.model_validate(old)
    assert skeleton.schema_version == "1.0" and skeleton.ik_chains == []


def test_the_bend_side_must_be_left_or_right():
    chain = LLD_EXAMPLE["ik_chains"][0]
    with pytest.raises(ValidationError):
        Skeleton.model_validate(LLD_EXAMPLE | {"ik_chains": [chain | {"bend_side": "up"}]})


def test_ik_chain_fields_are_strict():
    chain = LLD_EXAMPLE["ik_chains"][0]
    with pytest.raises(ValidationError):
        Skeleton.model_validate(LLD_EXAMPLE | {"ik_chains": [chain | {"extra": 1}]})
    with pytest.raises(ValidationError):
        Skeleton.model_validate(
            LLD_EXAMPLE | {"ik_chains": [{k: v for k, v in chain.items() if k != "joint"}]}
        )


def test_json_string_round_trip():
    skeleton = Skeleton.model_validate(LLD_EXAMPLE)
    again = Skeleton.model_validate_json(skeleton.model_dump_json())
    assert again == skeleton
    assert json.loads(skeleton.model_dump_json())["bones"][1]["rotation_limits_deg"] == [0, 150]


def test_defaults_for_a_minimal_skeleton():
    skeleton = Skeleton(
        rig_name="r",
        source_prompt="p",
        height=2.0,
        view="side",
        facing="right",
        rest_pose="side_neutral",
        style="s",
        bones=[],
        metadata={"generator": "rig-agent/0.1"},
    )
    assert skeleton.schema_version == "1.1" and skeleton.ik_chains == []
    assert skeleton.units == "unity_world"
    assert skeleton.pixels_per_unit == 100
    assert skeleton.metadata.iterations == 1
    assert skeleton.metadata.model is None


def test_bone_optional_fields_default_to_none():
    bone = Bone(
        id=1,
        name="hip",
        parent_id=0,
        world_head=(0, 0.9),
        world_tail=(0, 1.0),
        local_position=(0, 0.9),
        local_rotation_deg=0,
        length=0.1,
        depth=0,
    )
    assert bone.layer is None and bone.ik_chain is None and bone.mirror_of is None
    assert bone.rotation_limits_deg is None


def test_extra_bone_layer_values():
    data = LLD_EXAMPLE["bones"][0] | {"layer": "behind"}
    assert Bone.model_validate(data).layer == "behind"
    with pytest.raises(ValidationError):
        Bone.model_validate(data | {"layer": "middle"})


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"units": "pixels"},
        {"view": "top"},
        {"rest_pose": "sitting"},
        {"facing": "left"},
        {"height": 0},
        {"unknown": 1},
    ],
)
def test_invalid_top_level_values_are_rejected(change):
    with pytest.raises(ValidationError):
        Skeleton.model_validate(LLD_EXAMPLE | change)


def test_a_point_needs_two_numbers():
    bad = LLD_EXAMPLE["bones"][0] | {"world_head": [0.0, 0.0, 1.0]}
    with pytest.raises(ValidationError):
        Bone.model_validate(bad)
