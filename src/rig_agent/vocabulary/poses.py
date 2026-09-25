"""Rest-pose angles (LLD 2.8), rest-pose constants, and the IK chain table (LLD 2.9)."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from rig_agent.vocabulary.bones import BONES

RestPose = Literal["A_pose", "T_pose", "side_neutral"]

SHOULDER_TILT_DEG = 10.0  # shoulder bones point this far below horizontal
TOE_LENGTH_FACTOR = 0.3  # toe length as a fraction of the foot length
JAW_LENGTH_HU = 0.4
JAW_ATTACH_FRACTION = 0.35  # how far up the head bone the jaw pivots
ROOT_LENGTH_RATIO = 0.025  # root marker length, fraction of H (LLD 2.3)
FAR_LIMB_OFFSET_RATIO = 0.015  # side view: far limbs sit this far toward -X, fraction of H

_TORSO_COLUMN = {"root", "hip", "spine", "spine_2", "chest", "neck", "head"}

# World angles in degrees (0 = +X, 90 = up, counter-clockwise), as (left, right).
_ARM: dict[RestPose, tuple[float, float]] = {
    "A_pose": (-45.0, -135.0),
    "T_pose": (0.0, 180.0),
    "side_neutral": (-80.0, -80.0),
}
_FOOT: dict[RestPose, tuple[float, float]] = {
    "A_pose": (0.0, 180.0),
    "T_pose": (0.0, 180.0),
    "side_neutral": (0.0, 0.0),
}
_JAW: dict[RestPose, float] = {"A_pose": -90.0, "T_pose": -90.0, "side_neutral": -45.0}


def rest_angle(bone: str, pose: RestPose) -> float:
    """World angle of a canonical bone in the given rest pose (LLD 2.8)."""
    if bone not in BONES:
        raise ValueError(f"not a canonical bone: {bone}")
    if bone in _TORSO_COLUMN:
        return 90.0
    if bone == "jaw":
        return _JAW[pose]

    base, side = bone[:-2], bone[-1]
    index = 0 if side == "L" else 1
    if base == "shoulder":
        if pose == "side_neutral":
            raise ValueError("shoulder bones are front view only")
        return (-SHOULDER_TILT_DEG, -180.0 + SHOULDER_TILT_DEG)[index]
    if base in ("upper_arm", "forearm", "hand"):
        return _ARM[pose][index]
    if base in ("thigh", "shin"):
        return -90.0
    return _FOOT[pose][index]  # foot, toe


@dataclass(frozen=True)
class IKChain:
    name: str
    root: str
    joint: str
    effector: str


IK_CHAINS: tuple[IKChain, ...] = (
    IKChain("arm_L", "upper_arm_L", "forearm_L", "hand_L"),
    IKChain("arm_R", "upper_arm_R", "forearm_R", "hand_R"),
    IKChain("leg_L", "thigh_L", "shin_L", "foot_L"),
    IKChain("leg_R", "thigh_R", "shin_R", "foot_R"),
)


def ik_tags(present: Collection[str]) -> dict[str, str]:
    """Map each present bone that belongs to an IK chain to the chain's name (LLD 2.9)."""
    return {
        bone: chain.name
        for chain in IK_CHAINS
        for bone in (chain.root, chain.joint, chain.effector)
        if bone in present
    }
