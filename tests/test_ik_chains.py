import pytest

from layout_helpers import bone, good_skeleton
from rig_agent.schemas.validation import IssueCode
from rig_agent.validator.structure import check_structure
from rig_agent.vocabulary.bones import present_bones
from rig_agent.vocabulary.poses import IK_CHAINS, bend_side, ik_chain_defs

FRONT = {"view": "front", "rest_pose": "A_pose", "optional_bones": ["hands"]}
SIDE = {"view": "side", "rest_pose": "side_neutral", "optional_bones": ["hands"]}


def chains(skeleton):
    return {c.name: c for c in skeleton.ik_chains}


def ik_issues(skeleton):
    return [i for i in check_structure(skeleton) if i.code == IssueCode.INVALID_IK_CHAIN]


# ---- what the builder writes ---------------------------------------------------------------------


@pytest.mark.parametrize("kw", [FRONT, SIDE])
def test_every_rig_lists_its_four_chains_with_their_roles(kw):
    got = chains(good_skeleton(**kw))
    assert list(got) == ["arm_L", "arm_R", "leg_L", "leg_R"]
    for chain in IK_CHAINS:
        c = got[chain.name]
        assert (c.root, c.joint, c.effector) == (chain.root, chain.joint, chain.effector)


def test_an_arm_without_a_hand_has_no_effector_but_the_legs_still_do():
    got = chains(good_skeleton(view="front", rest_pose="A_pose"))
    assert got["arm_L"].effector is None and got["arm_R"].effector is None
    assert got["leg_L"].effector == "foot_L"


def test_side_view_elbows_point_back_and_knees_forward():
    # facing right: a hanging limb points down, so its left (counter-clockwise) side is forward
    got = chains(good_skeleton(**SIDE))
    assert got["arm_R"].bend_side == got["arm_L"].bend_side == "right"  # elbow back
    assert got["leg_R"].bend_side == got["leg_L"].bend_side == "left"  # knee forward


def test_front_view_sides_mirror_between_the_left_and_right_limbs():
    got = chains(good_skeleton(**FRONT))
    assert got["arm_L"].bend_side == "right" and got["arm_R"].bend_side == "left"
    assert got["leg_L"].bend_side == "left" and got["leg_R"].bend_side == "right"


def test_a_pair_of_front_limbs_always_bends_to_opposite_sides():
    for a, b in (("arm_L", "arm_R"), ("leg_L", "leg_R")):
        assert bend_side(a, "front") != bend_side(b, "front")


def test_the_chain_bones_hang_from_each_other():
    sk = good_skeleton(**FRONT)
    by_id = {b.id: b for b in sk.bones}
    for c in sk.ik_chains:
        assert by_id[bone(sk, c.joint).parent_id].name == c.root
        assert by_id[bone(sk, c.effector).parent_id].name == c.joint


def test_the_vocabulary_helper_matches_the_builder():
    sk = good_skeleton(**SIDE)
    defs = ik_chain_defs(present_bones(["hands"]), "side")
    assert [(d.name, d.effector, d.bend_side) for d in defs] == [
        (c.name, c.effector, c.bend_side) for c in sk.ik_chains
    ]
    assert bend_side("leg_R", "side") == "left"


def test_the_json_carries_the_chains():
    import json

    data = json.loads(good_skeleton(**FRONT).model_dump_json())
    assert data["schema_version"] == "1.1"
    assert data["ik_chains"][1] == {
        "name": "arm_R",
        "root": "upper_arm_R",
        "joint": "forearm_R",
        "effector": "hand_R",
        "bend_side": "left",
    }


# ---- what the validator checks -------------------------------------------------------------------


@pytest.mark.parametrize("kw", [FRONT, SIDE, {"view": "front", "rest_pose": "T_pose"}])
def test_a_built_rig_has_no_ik_issues(kw):
    assert ik_issues(good_skeleton(**kw)) == []


def test_a_missing_chain_is_reported():
    sk = good_skeleton(**FRONT)
    sk.ik_chains = [c for c in sk.ik_chains if c.name != "leg_R"]
    assert "'leg_R' is missing" in ik_issues(sk)[0].message


def test_an_unknown_or_repeated_chain_is_reported():
    sk = good_skeleton(**FRONT)
    sk.ik_chains = [*sk.ik_chains, sk.ik_chains[0].model_copy(update={"name": "tail"})]
    assert any("'tail' is not an IK chain" in i.message for i in ik_issues(sk))
    sk = good_skeleton(**FRONT)
    sk.ik_chains = [*sk.ik_chains, sk.ik_chains[0]]
    assert any("listed twice" in i.message for i in ik_issues(sk))


def test_wrong_roles_are_reported():
    sk = good_skeleton(**FRONT)
    sk.ik_chains[0] = sk.ik_chains[0].model_copy(update={"joint": "shin_L"})
    assert "has bones" in ik_issues(sk)[0].message


def test_a_chain_whose_bones_are_not_connected_is_reported():
    sk = good_skeleton(**FRONT)
    bone(sk, "hand_L").parent_id = bone(sk, "upper_arm_L").id
    issues = ik_issues(sk)
    assert any("'hand_L' does not hang from 'forearm_L'" in i.message for i in issues)
    assert issues[0].bones == ["forearm_L", "hand_L"]


def test_the_wrong_bend_side_for_the_view_is_reported():
    sk = good_skeleton(**SIDE)
    sk.ik_chains[3] = sk.ik_chains[3].model_copy(update={"bend_side": "right"})
    assert "bend_side 'right' should be 'left' in the side view" in ik_issues(sk)[0].message


def test_a_bone_with_the_wrong_tag_is_reported():
    sk = good_skeleton(**FRONT)
    bone(sk, "spine").ik_chain = "arm_L"
    bone(sk, "forearm_R").ik_chain = None
    messages = " ".join(i.message for i in ik_issues(sk))
    assert "'spine' is tagged 'arm_L'" in messages and "'forearm_R' is tagged 'None'" in messages


def test_a_1_0_skeleton_is_not_checked_for_chains():
    sk = good_skeleton(**FRONT)
    sk.schema_version = "1.0"
    sk.ik_chains = []
    assert ik_issues(sk) == []
