import pytest

from layout_helpers import bone, good_skeleton
from rig_agent.schemas.skeleton import Bone
from rig_agent.schemas.validation import IssueCode
from rig_agent.validator.structure import FATAL, check_structure

TOKENS = {"optional_bones": ["chest", "neck", "hands", "jaw"]}


def codes(skeleton):
    return {i.code for i in check_structure(skeleton)}


def dummy_extra(index, parent_id=0):
    return Bone(
        id=100 + index,
        name=f"extra_dummy_{index}",
        parent_id=parent_id,
        world_head=(0, 0),
        world_tail=(0, 0.1),
        local_position=(0, 0),
        local_rotation_deg=0,
        length=0.1,
        depth=0,
        layer="front",
    )


def test_a_good_skeleton_has_no_structural_issues():
    assert check_structure(good_skeleton(**TOKENS)) == []
    assert check_structure(good_skeleton(view="side", rest_pose="side_neutral")) == []


def test_no_root():
    sk = good_skeleton()
    bone(sk, "root").parent_id = 5
    assert IssueCode.NO_ROOT in codes(sk)


def test_multiple_roots():
    sk = good_skeleton()
    bone(sk, "hip").parent_id = -1
    issues = check_structure(sk)
    multiple = next(i for i in issues if i.code == IssueCode.MULTIPLE_ROOTS)
    assert set(multiple.bones) == {"root", "hip"}


def test_orphan_bone():
    sk = good_skeleton()
    bone(sk, "head").parent_id = 999
    issue = next(i for i in check_structure(sk) if i.code == IssueCode.ORPHAN_BONE)
    assert issue.bones == ["head"] and "999" in issue.message


def test_cycle():
    sk = good_skeleton()
    bone(sk, "hip").parent_id = bone(sk, "spine").id
    issue = next(i for i in check_structure(sk) if i.code == IssueCode.CYCLE)
    assert {"hip", "spine"} <= set(issue.bones)


def test_a_bone_that_is_its_own_parent_is_a_cycle():
    sk = good_skeleton()
    b = bone(sk, "head")
    b.parent_id = b.id
    assert IssueCode.CYCLE in codes(sk)


def test_duplicate_name_and_duplicate_id():
    sk = good_skeleton()
    bone(sk, "hip").name = "spine"
    assert IssueCode.DUPLICATE_NAME in codes(sk)
    sk = good_skeleton()
    bone(sk, "hip").id = bone(sk, "spine").id
    assert IssueCode.DUPLICATE_NAME in codes(sk)


@pytest.mark.parametrize(
    "name",
    ["root", "hip", "spine", "head", "upper_arm_L", "forearm_R", "thigh_L", "shin_R", "foot_L"],
)
def test_each_missing_required_bone_is_reported(name):
    sk = good_skeleton()
    sk.bones = [b for b in sk.bones if b.name != name]
    missing = [i for i in check_structure(sk) if i.code == IssueCode.MISSING_REQUIRED_BONE]
    assert [i.bones for i in missing] == [[name]]


def test_optional_bones_may_be_absent():
    assert check_structure(good_skeleton()) == []


def test_unknown_bone_names():
    sk = good_skeleton()
    bone(sk, "hip").name = "pelvis"
    issue = next(i for i in check_structure(sk) if i.code == IssueCode.UNKNOWN_BONE)
    assert issue.bones == ["pelvis"]


def test_extra_bone_names_are_accepted_with_or_without_a_side():
    sk = good_skeleton()
    sk.bones += [dummy_extra(1)]
    sk.bones[-1].name = "extra_hair_2_L"
    assert IssueCode.UNKNOWN_BONE not in codes(sk)


def test_bone_cap():
    sk = good_skeleton()
    sk.bones += [dummy_extra(i) for i in range(40 - len(sk.bones) + 1)]
    assert len(sk.bones) == 41
    assert IssueCode.TOO_MANY_BONES in codes(sk)


def test_extra_bone_cap():
    sk = good_skeleton()
    sk.bones += [dummy_extra(i) for i in range(17)]
    found = codes(sk)
    assert IssueCode.TOO_MANY_EXTRA_BONES in found
    assert IssueCode.TOO_MANY_BONES not in found


def test_exactly_sixteen_extras_is_fine():
    sk = good_skeleton()
    sk.bones += [dummy_extra(i) for i in range(16)]
    assert IssueCode.TOO_MANY_EXTRA_BONES not in codes(sk)


def test_wrong_canonical_parent():
    sk = good_skeleton(**TOKENS)
    bone(sk, "thigh_L").parent_id = bone(sk, "spine").id
    issue = next(i for i in check_structure(sk) if i.code == IssueCode.WRONG_PARENT)
    assert issue.bones == ["thigh_L"] and "'hip'" in issue.message


def test_parent_resolution_respects_the_optional_bones():
    sk = good_skeleton(optional_bones=["chest"])
    bone(sk, "upper_arm_L").parent_id = bone(sk, "spine").id
    assert IssueCode.WRONG_PARENT in codes(sk)


def test_fatal_codes_are_a_subset_of_the_structural_codes():
    assert IssueCode.NO_ROOT in FATAL and IssueCode.WRONG_PARENT not in FATAL
