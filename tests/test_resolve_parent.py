from itertools import combinations

import pytest

from rig_agent.vocabulary.bones import (
    BONES,
    OPTIONAL_TOKENS,
    present_bones,
    resolve_parent,
    torso_top,
)


def parent(bone, *tokens):
    return resolve_parent(bone, present_bones(tokens))


@pytest.mark.parametrize(
    ("bone", "expected"),
    [
        ("root", None),
        ("hip", "root"),
        ("spine", "hip"),
        ("thigh_L", "hip"),
        ("thigh_R", "hip"),
        ("shin_L", "thigh_L"),
        ("foot_R", "shin_R"),
        ("forearm_L", "upper_arm_L"),
        ("head", "spine"),
        ("upper_arm_L", "spine"),
        ("upper_arm_R", "spine"),
    ],
)
def test_minimal_rig(bone, expected):
    assert parent(bone) == expected


@pytest.mark.parametrize(
    ("bone", "tokens", "expected"),
    [
        ("chest", ["chest"], "spine"),
        ("head", ["chest"], "chest"),
        ("upper_arm_R", ["chest"], "chest"),
        ("spine_2", ["spine_2"], "spine"),
        ("head", ["spine_2"], "spine_2"),
        ("upper_arm_L", ["spine_2"], "spine_2"),
        ("chest", ["chest", "spine_2"], "spine_2"),
        ("head", ["chest", "spine_2"], "chest"),
        ("neck", ["neck"], "spine"),
        ("head", ["neck"], "neck"),
        ("upper_arm_L", ["neck"], "spine"),
        ("neck", ["chest", "neck"], "chest"),
        ("head", ["chest", "neck"], "neck"),
        ("upper_arm_L", ["chest", "neck"], "chest"),
        ("shoulder_L", ["shoulders"], "spine"),
        ("shoulder_R", ["shoulders", "chest"], "chest"),
        ("upper_arm_L", ["shoulders"], "shoulder_L"),
        ("upper_arm_R", ["shoulders", "chest"], "shoulder_R"),
        ("forearm_R", ["shoulders"], "upper_arm_R"),
        ("hand_L", ["hands"], "forearm_L"),
        ("toe_R", ["toes"], "foot_R"),
        ("jaw", ["jaw"], "head"),
        ("jaw", ["jaw", "neck", "chest"], "head"),
    ],
)
def test_optional_bones(bone, tokens, expected):
    assert parent(bone, *tokens) == expected


def test_torso_top():
    assert torso_top(present_bones()) == "spine"
    assert torso_top(present_bones(["spine_2"])) == "spine_2"
    assert torso_top(present_bones(["chest", "spine_2"])) == "chest"
    assert torso_top(present_bones(["neck"])) == "spine"


def test_torso_top_needs_a_torso_bone():
    with pytest.raises(ValueError):
        torso_top({"root", "hip"})


def test_extra_bones_are_not_resolved_here():
    with pytest.raises(ValueError, match="not a canonical bone"):
        resolve_parent("extra_cape", present_bones())


def test_absent_bone_is_rejected():
    with pytest.raises(ValueError, match="not present"):
        resolve_parent("chest", present_bones())


def test_every_token_combination_forms_a_tree_rooted_at_root():
    for size in range(len(OPTIONAL_TOKENS) + 1):
        for tokens in combinations(OPTIONAL_TOKENS, size):
            present = present_bones(tokens)
            for bone in present:
                node, hops = bone, 0
                while node is not None:
                    assert node in present
                    node = resolve_parent(node, present)
                    hops += 1
                    assert hops <= len(BONES)
