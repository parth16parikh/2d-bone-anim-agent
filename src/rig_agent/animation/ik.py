"""Analytic two-bone IK in 2D, with the bend-side convention of skeleton.json's ik_chains (and so
of Unity's LimbSolver2D.flip): "left" puts the joint on the counter-clockwise side of the line
from the chain's root to its target, looking from the root."""

import math
from dataclasses import dataclass

from rig_agent.builder.geometry import Point, advance
from rig_agent.vocabulary.poses import BendSide


@dataclass(frozen=True)
class TwoBoneSolution:
    upper_deg: float  # world angle of the upper bone (upper arm or thigh)
    lower_deg: float  # world angle of the lower bone (forearm or shin)
    joint: Point  # elbow or knee
    reached: bool  # False when the target was out of reach and the limb was stretched toward it


def bend_sign(side: BendSide) -> int:
    """+1 when the lower bone turns counter-clockwise from the upper one as the joint bends."""
    return 1 if side == "right" else -1


def solve_two_bone(
    root: Point, target: Point, upper: float, lower: float, side: BendSide
) -> TwoBoneSolution:
    dx, dy = target[0] - root[0], target[1] - root[1]
    wanted = math.hypot(dx, dy)
    shortest, longest = abs(upper - lower), upper + lower
    distance = min(max(wanted, shortest), longest)
    reached = shortest - 1e-9 <= wanted <= longest + 1e-9
    base = math.degrees(math.atan2(dy, dx))
    cos_root = (upper * upper + distance * distance - lower * lower) / (2 * upper * distance)
    opening = math.degrees(math.acos(max(-1.0, min(1.0, cos_root))))
    upper_deg = base + opening if side == "left" else base - opening
    joint = advance(root, upper_deg, upper)
    end = advance(root, base, distance)  # the target, or the nearest reachable point toward it
    lower_deg = math.degrees(math.atan2(end[1] - joint[1], end[0] - joint[0]))
    return TwoBoneSolution(upper_deg, lower_deg, joint, reached)
