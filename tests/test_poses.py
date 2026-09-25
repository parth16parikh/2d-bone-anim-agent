import pytest

from rig_agent.vocabulary.bones import BONES, present_bones
from rig_agent.vocabulary.poses import IK_CHAINS, ik_tags, rest_angle

FRONT = ("A_pose", "T_pose")

# (bone, A_pose, T_pose, side_neutral); None = not used in that pose
LLD_TABLE = [
    ("root", 90, 90, 90),
    ("hip", 90, 90, 90),
    ("spine", 90, 90, 90),
    ("spine_2", 90, 90, 90),
    ("chest", 90, 90, 90),
    ("neck", 90, 90, 90),
    ("head", 90, 90, 90),
    ("shoulder_L", -10, -10, None),
    ("shoulder_R", -170, -170, None),
    ("upper_arm_L", -45, 0, -80),
    ("forearm_L", -45, 0, -80),
    ("hand_L", -45, 0, -80),
    ("upper_arm_R", -135, 180, -80),
    ("forearm_R", -135, 180, -80),
    ("hand_R", -135, 180, -80),
    ("thigh_L", -90, -90, -90),
    ("thigh_R", -90, -90, -90),
    ("shin_L", -90, -90, -90),
    ("shin_R", -90, -90, -90),
    ("foot_L", 0, 0, 0),
    ("foot_R", 180, 180, 0),
    ("toe_L", 0, 0, 0),
    ("toe_R", 180, 180, 0),
    ("jaw", -90, -90, -45),
]


@pytest.mark.parametrize(("bone", "a_pose", "t_pose", "side"), LLD_TABLE)
def test_rest_angles_match_the_lld_table(bone, a_pose, t_pose, side):
    assert rest_angle(bone, "A_pose") == a_pose
    assert rest_angle(bone, "T_pose") == t_pose
    if side is None:
        with pytest.raises(ValueError):
            rest_angle(bone, "side_neutral")
    else:
        assert rest_angle(bone, "side_neutral") == side


def test_every_canonical_bone_has_an_angle_in_front_poses():
    for bone in BONES:
        for pose in FRONT:
            assert -180 <= rest_angle(bone, pose) <= 180


def test_extra_bones_have_no_rest_angle():
    with pytest.raises(ValueError, match="not a canonical bone"):
        rest_angle("extra_cape_1", "A_pose")


def test_four_chains_of_root_joint_effector():
    assert [c.name for c in IK_CHAINS] == ["arm_L", "arm_R", "leg_L", "leg_R"]
    leg = next(c for c in IK_CHAINS if c.name == "leg_R")
    assert (leg.root, leg.joint, leg.effector) == ("thigh_R", "shin_R", "foot_R")


def test_ik_tags_for_a_rig_with_hands():
    tags = ik_tags(present_bones(["hands"]))
    assert tags["upper_arm_L"] == tags["forearm_L"] == tags["hand_L"] == "arm_L"
    assert tags["thigh_R"] == tags["shin_R"] == tags["foot_R"] == "leg_R"
    assert len(tags) == 12
    assert "spine" not in tags


def test_ik_tags_without_hands_leave_two_bone_arm_chains():
    tags = ik_tags(present_bones())
    assert "hand_L" not in tags
    assert tags["upper_arm_L"] == tags["forearm_L"] == "arm_L"
    assert len(tags) == 10
