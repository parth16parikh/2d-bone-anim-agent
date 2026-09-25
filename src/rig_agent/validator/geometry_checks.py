"""Numeric checks: connectivity, symmetry, depth order, bounds, proportions (LLD 3.8.2, 2.4.4, 2.7)."""

import math
from dataclasses import dataclass, field

from rig_agent.builder.geometry import Point, distance, mirror_x
from rig_agent.builder.proportions import ResolvedProportions
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.skeleton import Bone, Skeleton
from rig_agent.schemas.validation import IssueCode, ValidationIssue
from rig_agent.validator.structure import is_extra
from rig_agent.vocabulary.bones import BONES, View
from rig_agent.vocabulary.poses import (
    FAR_LIMB_OFFSET_RATIO,
    JAW_ATTACH_FRACTION,
    SHOULDER_TILT_DEG,
)
from rig_agent.vocabulary.presets import BANDS

CONNECT_TOL_RATIO = 0.005  # of H
SYMMETRY_TOL = 0.01  # of H
MIN_EXTRA_SEGMENT_RATIO = 0.005  # of H
BOX_HALF_WIDTH = 1.0  # x in [-H, H]
BOX_HEIGHT = 1.2  # y in [0, 1.2 H]
COINCIDENT_ANGLE_DEG = 5.0
LIMB_BASES = {"upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe"}


@dataclass
class GeometryResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


def _issue(code: IssueCode, message: str, bones: list[str]) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, bones=bones)


def _is_left(name: str) -> bool:
    return name.endswith("_L")


def _pairs(skeleton: Skeleton) -> list[tuple[Bone, Bone]]:
    by_name = {b.name: b for b in skeleton.bones}
    return [
        (b, by_name[b.name[:-1] + "R"])
        for b in skeleton.bones
        if _is_left(b.name) and b.name[:-1] + "R" in by_name
    ]


# ---- lengths ---------------------------------------------------------------------------------


def check_lengths(skeleton: Skeleton) -> list[ValidationIssue]:
    issues = []
    minimum = MIN_EXTRA_SEGMENT_RATIO * skeleton.height
    for b in skeleton.bones:
        if b.length <= 0:
            issues.append(
                _issue(IssueCode.NON_POSITIVE_LENGTH, f"'{b.name}' has length {b.length}", [b.name])
            )
        elif is_extra(b.name) and b.length < minimum:
            issues.append(
                _issue(
                    IssueCode.SEGMENT_TOO_SHORT,
                    f"'{b.name}' is {b.length:.4f} long; extra segments must be at least "
                    f"{minimum:.4f} (0.5% of the height)",
                    [b.name],
                )
            )
    return issues


# ---- connectivity ----------------------------------------------------------------------------


def _expected_head(
    b: Bone, parent: Bone, by_name: dict[str, Bone], props: ResolvedProportions, view: View
) -> tuple[Point, IssueCode]:
    """Where a canonical bone's head should be, and the issue code if it is not there."""
    name = b.name
    if name == "hip":
        return (0.0, props.leg_length), IssueCode.HIP_MISPLACED
    if name == "jaw":
        head = by_name["head"]
        fraction = JAW_ATTACH_FRACTION
        return (
            head.world_head[0] + fraction * (head.world_tail[0] - head.world_head[0]),
            head.world_head[1] + fraction * (head.world_tail[1] - head.world_head[1]),
        ), IssueCode.JAW_MISPLACED

    side_left = _is_left(name)
    far_dx = -FAR_LIMB_OFFSET_RATIO * props.height if side_left else 0.0  # side view: _L is far
    if name.startswith("thigh_"):
        hip_y = by_name["hip"].world_head[1]
        if view == "front":
            return (
                (1 if side_left else -1) * props.hip_spacing / 2,
                hip_y,
            ), IssueCode.LIMB_ROOT_MISPLACED
        return (far_dx, hip_y), IssueCode.LIMB_ROOT_MISPLACED
    if name.startswith("upper_arm_") and not parent.name.startswith("shoulder_"):
        top = parent.world_tail
        if view == "front":
            half = props.shoulder_width / 2
            drop = half * math.tan(math.radians(SHOULDER_TILT_DEG))
            return ((1 if side_left else -1) * half, top[1] - drop), IssueCode.LIMB_ROOT_MISPLACED
        return (top[0] + far_dx, top[1]), IssueCode.LIMB_ROOT_MISPLACED
    return parent.world_tail, IssueCode.DISCONNECTED_JOINT


def check_connectivity(
    skeleton: Skeleton, props: ResolvedProportions, view: View
) -> tuple[list[ValidationIssue], float]:
    """Issues plus the fraction of canonical bones that start where they should (Q5)."""
    by_id = {b.id: b for b in skeleton.bones}
    by_name = {b.name: b for b in skeleton.bones}
    tolerance = CONNECT_TOL_RATIO * skeleton.height
    issues: list[ValidationIssue] = []
    checked = ok = 0

    for b in skeleton.bones:
        if b.parent_id == -1:
            continue
        parent = by_id[b.parent_id]
        if is_extra(b.name):
            anchors = [parent.world_head, parent.world_tail]
            if view == "side":  # a far twin on a center bone sits at the far-limb offset
                shift = FAR_LIMB_OFFSET_RATIO * skeleton.height
                anchors += [(x - shift, y) for x, y in anchors]
            gap = min(distance(b.world_head, anchor) for anchor in anchors)
            if gap > tolerance:
                issues.append(
                    _issue(
                        IssueCode.DISCONNECTED_JOINT,
                        f"extra bone '{b.name}' starts {gap:.4f} from where it attaches to "
                        f"'{parent.name}'",
                        [b.name],
                    )
                )
            continue
        if b.name not in BONES:
            continue
        expected, code = _expected_head(b, parent, by_name, props, view)
        gap = distance(b.world_head, expected)
        checked += 1
        if gap <= tolerance:
            ok += 1
        else:
            issues.append(
                _issue(
                    code, f"'{b.name}' starts {gap:.4f} away from its expected position", [b.name]
                )
            )
    return issues, (ok / checked if checked else 1.0)


# ---- symmetry and depth ----------------------------------------------------------------------


def check_symmetry(skeleton: Skeleton, view: View) -> tuple[list[ValidationIssue], float]:
    """Issues plus the mean symmetry error over all mirror pairs, as a fraction of H (Q6)."""
    height = skeleton.height
    offset = (FAR_LIMB_OFFSET_RATIO * height, 0.0)
    issues: list[ValidationIssue] = []
    errors = []
    for left, right in _pairs(skeleton):
        if view == "front":
            error = (
                (
                    distance(mirror_x(left.world_head), right.world_head)
                    + distance(mirror_x(left.world_tail), right.world_tail)
                )
                / 2
                / height
            )
        else:
            # the near (_R) limb sits `offset` in front of the far (_L) limb
            delta = (
                right.world_head[0] - left.world_head[0] - offset[0],
                right.world_head[1] - left.world_head[1] - offset[1],
            )
            error = (abs(left.length - right.length) + math.hypot(*delta)) / height
        errors.append(error)
        if error > SYMMETRY_TOL:
            issues.append(
                _issue(
                    IssueCode.ASYMMETRIC_PAIR,
                    f"'{left.name}' and '{right.name}' differ by {error:.3f} of the height "
                    f"(limit {SYMMETRY_TOL})",
                    [left.name, right.name],
                )
            )
    return issues, (sum(errors) / len(errors) if errors else 0.0)


def check_depth_order(skeleton: Skeleton) -> list[ValidationIssue]:
    """Side view: far limbs behind the torso plane, near limbs in front (Q6b)."""
    torso = next((b.depth for b in skeleton.bones if b.name == "spine"), 0)
    issues = []
    for far, near in _pairs(skeleton):  # the _L bone is far, the _R bone is near
        base = near.name[:-2]
        if base not in LIMB_BASES:
            continue
        if not far.depth < torso < near.depth:
            issues.append(
                _issue(
                    IssueCode.DEPTH_ORDER,
                    f"'{far.name}' (depth {far.depth}) must be behind the torso (depth {torso}) "
                    f"and '{near.name}' (depth {near.depth}) in front of it",
                    [near.name, far.name],
                )
            )
    return issues


# ---- bounds ----------------------------------------------------------------------------------


def check_bounds(skeleton: Skeleton) -> list[ValidationIssue]:
    height = skeleton.height
    eps = CONNECT_TOL_RATIO * height
    issues = []
    for b in skeleton.bones:
        for x, y in (b.world_head, b.world_tail):
            if not (
                -BOX_HALF_WIDTH * height - eps <= x <= BOX_HALF_WIDTH * height + eps
                and -eps <= y <= BOX_HEIGHT * height + eps
            ):
                issues.append(
                    _issue(
                        IssueCode.OUT_OF_BOUNDS,
                        f"'{b.name}' has a joint at ({x:.3f}, {y:.3f}), outside x in [-H, H] and "
                        f"y in [0, 1.2 H]",
                        [b.name],
                    )
                )
                break
    return issues


# ---- proportions -----------------------------------------------------------------------------


def check_bands(props: ResolvedProportions, view: View) -> list[ValidationIssue]:
    issues = []
    for name, value in props.derived_values(view).items():
        low, high = BANDS[name]
        if not low <= value <= high:
            issues.append(
                _issue(
                    IssueCode.PROPORTION_OUT_OF_BAND,
                    f"{name} is {value:.3f}, outside the plausible range {low}–{high}",
                    [],
                )
            )
    return issues


def proportion_error(skeleton: Skeleton, props: ResolvedProportions, view: View) -> float:
    """Mean relative error of the built rig against the resolved proportions (Q7)."""
    by_name = {b.name: b for b in skeleton.bones}
    arm_end = by_name["hand_L"] if "hand_L" in by_name else by_name["forearm_L"]
    pairs = [
        (by_name["head"].length, props.head),
        (by_name["hip"].world_head[1], props.leg_length),
        (distance(by_name["upper_arm_L"].world_head, arm_end.world_tail), props.arm_length),
    ]
    if view == "front":
        width = abs(by_name["upper_arm_L"].world_head[0] - by_name["upper_arm_R"].world_head[0])
        pairs.append((width, props.shoulder_width))
    return sum(abs(measured - target) / target for measured, target in pairs) / len(pairs)


def check_mirror_coincident(spec: RigSpec) -> list[ValidationIssue]:
    """Front view: a mirrored chain on a center bone pointing straight up or down lands on its twin."""
    if spec.view != "front":
        return []
    return [
        _issue(
            IssueCode.MIRROR_COINCIDENT,
            f"mirrored extra '{e.name}' points {e.direction_deg:g}° from a center bone, so its twin "
            f"would sit exactly on top of it. Change the direction.",
            [e.name],
        )
        for e in spec.extra_bones
        if e.mirror
        and not e.parent.endswith(("_L", "_R"))
        and abs(abs(e.direction_deg) - 90) <= COINCIDENT_ANGLE_DEG
    ]


# ---- everything ------------------------------------------------------------------------------


def check_geometry(skeleton: Skeleton, spec: RigSpec, props: ResolvedProportions) -> GeometryResult:
    view = spec.view
    result = GeometryResult()
    result.issues += check_lengths(skeleton)
    connectivity_issues, connectivity = check_connectivity(skeleton, props, view)
    symmetry_issues, symmetry = check_symmetry(skeleton, view)
    result.issues += connectivity_issues + symmetry_issues
    result.metrics["joint_connectivity"] = connectivity
    result.metrics["symmetry_error"] = symmetry
    if view == "side":
        depth_issues = check_depth_order(skeleton)
        result.issues += depth_issues
        result.metrics["depth_order_correct"] = 0.0 if depth_issues else 1.0
    result.issues += check_bounds(skeleton)
    result.metrics["proportion_error"] = proportion_error(skeleton, props, view)
    return result
