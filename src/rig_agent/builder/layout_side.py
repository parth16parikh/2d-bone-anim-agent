"""Side-view joint layout: near/far limbs stacked with a small depth offset (LLD 2.5)."""

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
from rig_agent.vocabulary.bones import present_bones
from rig_agent.vocabulary.poses import FAR_LIMB_OFFSET_RATIO

NEAR_DEPTH = 1
FAR_DEPTH = -1


def far_limb_offset(height: float) -> float:
    """How far the far limbs sit toward -X, so they stay selectable (LLD 2.5)."""
    return FAR_LIMB_OFFSET_RATIO * height


def layout_side(spec: RigSpec, props: ResolvedProportions) -> dict[str, Placed]:
    """Canonical bones of a side-view rig facing +X.

    A right-facing character shows its right side to the camera, so `_R` is the near side (in
    front of the torso) and `_L` is the far side (behind it, offset toward -X). LLD 2.2.
    """
    present = present_bones(spec.optional_bones)
    pose = spec.rest_pose
    placed = place_column(spec, props, present)

    top = torso_top_point(placed, present)
    hip_y = placed["hip"].head[1]
    for side, dx, depth in (
        ("R", 0.0, NEAR_DEPTH),
        ("L", -far_limb_offset(props.height), FAR_DEPTH),
    ):
        place_chain(placed, present, pose, arm_links(props, side), (top[0] + dx, top[1]), depth)
        place_chain(placed, present, pose, leg_links(props, side), (dx, hip_y), depth)
    return placed
