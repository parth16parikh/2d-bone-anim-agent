"""Front-view joint layout: _L/_R limbs mirrored across the Y-axis (LLD 2.5, 2.7)."""

import math

from rig_agent.builder.column import (
    arm_links,
    leg_links,
    place_chain,
    place_column,
    torso_top_point,
)
from rig_agent.builder.geometry import Placed
from rig_agent.builder.proportions import ResolvedProportions
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.vocabulary.bones import present_bones, resolve_parent
from rig_agent.vocabulary.poses import SHOULDER_TILT_DEG, rest_angle

LIMB_DEPTH = 1  # limbs sit slightly in front of the torso plane


def layout_front(spec: RigSpec, props: ResolvedProportions) -> dict[str, Placed]:
    """Canonical bones of a front-view rig. The character's left is +X."""
    present = present_bones(spec.optional_bones)
    pose = spec.rest_pose
    placed = place_column(spec, props, present)

    top = torso_top_point(placed, present)
    half_width = props.shoulder_width / 2
    tilt = math.radians(SHOULDER_TILT_DEG)
    joint_y = top[1] - half_width * math.tan(tilt)

    for side, sign in (("L", 1.0), ("R", -1.0)):
        shoulder = f"shoulder_{side}"
        if shoulder in present:
            placed[shoulder] = Placed(
                shoulder,
                resolve_parent(shoulder, present),
                top,
                rest_angle(shoulder, pose),
                half_width / math.cos(tilt),
            )
        place_chain(
            placed, present, pose, arm_links(props, side), (sign * half_width, joint_y), LIMB_DEPTH
        )
        hip_joint = (sign * props.hip_spacing / 2, placed["hip"].head[1])
        place_chain(placed, present, pose, leg_links(props, side), hip_joint, LIMB_DEPTH)

    return placed
