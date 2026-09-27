"""Rest-pose angles (LLD 2.8), rest-pose constants, and the IK chain table (LLD 2.9)."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from rig_agent.vocabulary.bones import BONES

RestPose = Literal["A_pose", "T_pose", "side_neutral"]
BendSide = Literal["left", "right"]

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


# Which side of the line from a chain's root toward its target the joint (elbow or knee) sits on,
# looking from the root toward the target: "left" is the counter-clockwise side (LLD 2.9). This is
# what a limb solver needs (Unity's LimbSolver2D.flip) and it stays the same however the limb is
# posed. Side view faces right (+X): elbows point back, knees forward. Front view (the character's
# left is screen +X): elbows point outward and down, knees outward.
_BEND_SIDE: dict[str, dict[str, BendSide]] = {
    "front": {"arm_L": "right", "arm_R": "left", "leg_L": "left", "leg_R": "right"},
    "side": {"arm_L": "right", "arm_R": "right", "leg_L": "left", "leg_R": "left"},
}


def bend_side(chain_name: str, view: str) -> BendSide:
    """ "left" or "right": the side of the root-to-target line that the elbow or knee sits on."""
    return _BEND_SIDE[view][chain_name]


@dataclass(frozen=True)
class IKChainDef:
    """A chain as it appears in a rig: the same roles as IKChain, with the effector missing when
    the rig has no hands, and the bend side for the rig's view."""

    name: str
    root: str
    joint: str
    effector: str | None
    bend_side: BendSide


def ik_chain_defs(present: Collection[str], view: str) -> list[IKChainDef]:
    """The chains a rig with these bones has. A chain needs its root and joint bones; the
    effector is None for an arm without a hand (LLD 2.9)."""
    return [
        IKChainDef(
            c.name,
            c.root,
            c.joint,
            c.effector if c.effector in present else None,
            bend_side(c.name, view),
        )
        for c in IK_CHAINS
        if c.root in present and c.joint in present
    ]


def ik_tags(present: Collection[str]) -> dict[str, str]:
    """Map each present bone that belongs to an IK chain to the chain's name (LLD 2.9)."""
    return {
        bone: chain.name
        for chain in IK_CHAINS
        for bone in (chain.root, chain.joint, chain.effector)
        if bone in present
    }
