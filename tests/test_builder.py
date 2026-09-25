import itertools
import json

import pytest

from layout_helpers import make_spec
from rig_agent.builder.errors import BuildError
from rig_agent.builder.geometry import distance, local_to_world
from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.vocabulary.bones import OPTIONAL_TOKENS, present_bones, token_views

# The LLD 3.5b example: a tall, lanky elf archer with a long cape.
ELF = {
    "character_summary": "a tall, lanky elf archer with a long cape",
    "style": "lanky elf",
    "preset": "stylized",
    "view": "front",
    "rest_pose": "A_pose",
    "overrides": {"leg_scale": 1.15, "arm_scale": 1.15, "torso_scale": 0.95},
    "optional_bones": ["chest", "neck", "hands"],
    "extra_bones": [
        {
            "name": "extra_cape",
            "parent": "chest",
            "direction_deg": -90,
            "length_ratio": 0.45,
            "segments": 3,
            "layer": "behind",
        }
    ],
    "assumptions": ["'lanky' → arm/leg scale 1.15"],
}


def by_name(skeleton):
    return {b.name: b for b in skeleton.bones}


def test_the_lld_example_builds_a_skeleton():
    skeleton = build_skeleton(
        make_spec(**ELF), source_prompt=ELF["character_summary"], model="test:model", iterations=2
    )
    bones = by_name(skeleton)
    assert skeleton.rig_name == "a_tall_lanky_elf_archer_with_a_long_cape"
    assert (skeleton.view, skeleton.facing, skeleton.rest_pose) == ("front", None, "A_pose")
    assert skeleton.height == 2.0 and skeleton.pixels_per_unit == 100
    assert skeleton.metadata.generator.startswith("rig-agent/")
    assert (skeleton.metadata.model, skeleton.metadata.iterations) == ("test:model", 2)
    assert skeleton.metadata.assumptions == ["'lanky' → arm/leg scale 1.15"]
    assert len(skeleton.bones) == 14 + 1 + 1 + 2 + 3  # + chest, neck, two hands, cape x3
    assert bones["forearm_L"].ik_chain == "arm_L" and bones["forearm_L"].mirror_of == "forearm_R"
    assert bones["extra_cape_2"].layer == "behind" and bones["extra_cape_2"].depth == 0
    assert bones["extra_cape_1"].parent_id == bones["chest"].id


def test_ids_are_sequential_and_parents_come_first():
    for spec in (make_spec(**ELF), make_spec(view="side", rest_pose="side_neutral")):
        skeleton = build_skeleton(spec)
        assert [b.id for b in skeleton.bones] == list(range(len(skeleton.bones)))
        assert skeleton.bones[0].name == "root" and skeleton.bones[0].parent_id == -1
        assert all(b.parent_id < b.id for b in skeleton.bones[1:])
        assert len({b.name for b in skeleton.bones}) == len(skeleton.bones)


def test_root_matches_the_lld_example():
    root = build_skeleton(make_spec(**ELF)).bones[0]
    assert root.world_head == (0.0, 0.0) and root.world_tail == (0.0, 0.05)
    assert root.local_position == (0.0, 0.0) and root.local_rotation_deg == 90.0
    assert root.length == 0.05 and root.depth == 0 and root.layer is None


def test_hip_is_placed_by_a_local_offset_in_the_rotated_root_frame():
    skeleton = build_skeleton(make_spec(**ELF))
    hip = by_name(skeleton)["hip"]
    assert hip.world_head[0] == 0 and hip.local_rotation_deg == 0
    assert hip.local_position[0] == pytest.approx(hip.world_head[1], abs=1e-5)
    assert hip.local_position[1] == pytest.approx(0, abs=1e-5)


def test_a_child_on_its_parents_tail_has_a_local_position_along_x():
    bones = by_name(build_skeleton(make_spec(**ELF)))
    assert bones["forearm_L"].local_position[0] == pytest.approx(
        bones["upper_arm_L"].length, abs=1e-5
    )
    assert bones["forearm_L"].local_position[1] == pytest.approx(0, abs=1e-5)
    assert bones["forearm_L"].local_rotation_deg == 0


def test_local_transforms_reproduce_the_world_geometry():
    for spec in (
        make_spec(**ELF),
        make_spec(view="side", rest_pose="side_neutral", optional_bones=["toes", "hands"]),
    ):
        skeleton = build_skeleton(spec)
        bones = by_name(skeleton)
        world_angle = {}
        for b in skeleton.bones:
            if b.parent_id == -1:
                parent_head, parent_angle = (0.0, 0.0), 0.0
            else:
                parent = skeleton.bones[b.parent_id]
                parent_head, parent_angle = parent.world_head, world_angle[parent.name]
            head, angle = local_to_world(
                parent_head, parent_angle, b.local_position, b.local_rotation_deg
            )
            world_angle[b.name] = angle
            assert head == pytest.approx(b.world_head, abs=1e-4), b.name
            assert distance(b.world_head, b.world_tail) == pytest.approx(b.length, abs=1e-5), b.name
        assert set(world_angle) == set(bones)


def test_the_result_serialises_and_reloads():
    skeleton = build_skeleton(make_spec(**ELF))
    assert Skeleton.model_validate_json(skeleton.model_dump_json()) == skeleton
    assert "-0.0" not in skeleton.model_dump_json()


def test_side_view_skeleton():
    skeleton = build_skeleton(
        make_spec(view="side", rest_pose="side_neutral", optional_bones=["toes"])
    )
    bones = by_name(skeleton)
    assert skeleton.facing == "right"
    assert (
        bones["thigh_R"].depth == 1 and bones["thigh_L"].depth == -1 and bones["spine"].depth == 0
    )
    assert bones["toe_L"].parent_id == bones["foot_L"].id
    assert bones["foot_L"].ik_chain == "leg_L"


def test_ik_chains_and_mirror_links():
    bones = by_name(build_skeleton(make_spec(optional_bones=["hands"])))
    assert {n for n, b in bones.items() if b.ik_chain == "arm_R"} == {
        "upper_arm_R",
        "forearm_R",
        "hand_R",
    }
    assert bones["spine"].ik_chain is None and bones["spine"].mirror_of is None
    assert bones["thigh_L"].mirror_of == "thigh_R" and bones["thigh_R"].mirror_of == "thigh_L"


def test_without_hands_the_arm_chain_has_two_bones():
    bones = by_name(build_skeleton(make_spec()))
    assert {n for n, b in bones.items() if b.ik_chain == "arm_L"} == {"upper_arm_L", "forearm_L"}


def test_mirrored_extras_are_linked_to_each_other():
    spec = make_spec(
        optional_bones=["neck"],
        extra_bones=[
            {
                "name": "extra_hair",
                "parent": "head",
                "direction_deg": -45,
                "length_ratio": 0.2,
                "mirror": True,
            }
        ],
    )
    bones = by_name(build_skeleton(spec))
    assert bones["extra_hair_L"].mirror_of == "extra_hair_R"
    assert bones["extra_hair_R"].mirror_of == "extra_hair_L"


def test_rig_name_can_be_given_or_is_slugged():
    assert build_skeleton(make_spec(), rig_name="knight").rig_name == "knight"
    assert build_skeleton(make_spec(character_summary="!!!")).rig_name == "rig"


def test_full_rig_has_24_canonical_bones():
    spec = make_spec(optional_bones=["chest", "neck", "spine_2", "hands", "shoulders", "jaw"])
    assert len(build_skeleton(spec).bones) == 24 - 2  # front view has no toes
    side = make_spec(
        view="side",
        rest_pose="side_neutral",
        optional_bones=["chest", "neck", "spine_2", "hands", "toes", "jaw"],
    )
    assert len(build_skeleton(side).bones) == 24 - 2  # side view has no shoulders


def test_a_spec_that_cannot_be_built_raises():
    with pytest.raises(BuildError):
        build_skeleton(make_spec(base={"heads_tall": 2.0, "leg_ratio": 0.6}))


def test_every_optional_subset_builds_in_both_views():
    for view, pose in (("front", "A_pose"), ("front", "T_pose"), ("side", "side_neutral")):
        tokens = [t for t in OPTIONAL_TOKENS if view in token_views(t)]
        for size in range(len(tokens) + 1):
            for subset in itertools.combinations(tokens, size):
                skeleton = build_skeleton(
                    make_spec(view=view, rest_pose=pose, optional_bones=list(subset))
                )
                assert {b.name for b in skeleton.bones} == present_bones(subset)


def test_the_json_is_plain_data():
    data = json.loads(build_skeleton(make_spec(**ELF)).model_dump_json())
    assert data["schema_version"] == "1.0" and data["units"] == "unity_world"
    assert isinstance(data["bones"][0]["world_head"], list)
