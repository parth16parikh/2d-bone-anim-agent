"""validate_clip(): checks a baked (or hand-edited) AnimationClip against its skeleton.

It recomputes every frame with forward kinematics from the clip's own rotation and position
tracks, so it checks what Unity will actually play, not what the templates intended:
  - the clip fits the rig (view, bone names, IK chains) and every number is finite;
  - each IK target sits on its effector (so Unity's solvers reproduce the rotation curves);
  - knees and elbows bend only their own way, and the torso and ankles stay within range;
  - a foot on the ground moves at the clip's ground speed, not faster or slower (no sliding);
  - no foot goes below the ground;
  - a looping clip ends on the pose it started from (its closing frame), so it loops without a jump.
Measured values go into the report's metrics, as for skeletons.
"""

import math
from collections.abc import Iterable

from rig_agent.animation.ik import bend_sign
from rig_agent.animation.pose import WorldBone, forward
from rig_agent.builder.geometry import normalize_angle
from rig_agent.schemas.animation import CLIP_VIEWS, AnimationClip
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport

TORSO = ("spine", "spine_2", "chest", "neck", "head")
TARGET_TOLERANCE = 1e-4  # fraction of H
SLIP_TOLERANCE = 0.005  # fraction of H per frame
CONTACT_HEIGHT = 0.003  # fraction of H above the rest ankle that still counts as on the ground
GROUND_TOLERANCE = 0.003  # fraction of H below the rest ankle allowed
MAX_TORSO_DEG = 45.0
MAX_ANKLE_DEG = 70.0
MAX_BEND_DEG = 165.0
WRONG_WAY_DEG = 5.0
LOOP_TOLERANCE = 1e-4  # a looping clip's last frame must match its first: degrees, or fraction of H


def _issue(code: IssueCode, message: str, bones: Iterable[str] = ()) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, bones=sorted(set(bones)))


def _numbers(clip: AnimationClip) -> Iterable[float]:
    for values in clip.rotations.values():
        yield from values
    for points in clip.positions.values():
        for x, y in points:
            yield x
            yield y
    for track in clip.ik_targets:
        yield from track.rotations_deg
        for x, y in track.positions:
            yield x
            yield y
    yield clip.ground_speed


def _fit(clip: AnimationClip, skeleton: Skeleton) -> list[ValidationIssue]:
    issues = []
    if clip.view != skeleton.view or skeleton.view not in CLIP_VIEWS[clip.clip]:
        issues.append(
            _issue(
                IssueCode.CLIP_VIEW_MISMATCH,
                f"a {clip.clip} clip for a {clip.view}-view rig does not fit this "
                f"{skeleton.view}-view rig (allowed: {', '.join(CLIP_VIEWS[clip.clip])})",
            )
        )
    names = {b.name for b in skeleton.bones}
    unknown = (set(clip.rotations) | set(clip.positions)) - names
    if unknown:
        issues.append(
            _issue(
                IssueCode.CLIP_RIG_MISMATCH,
                f"the clip animates bones the rig does not have: {sorted(unknown)}",
                unknown,
            )
        )
    chains = {c.name: c for c in skeleton.ik_chains if c.effector}
    for track in clip.ik_targets:
        chain = chains.get(track.chain)
        if chain is None or track.target != f"target_{chain.effector}":
            issues.append(
                _issue(
                    IssueCode.CLIP_RIG_MISMATCH,
                    f"IK target {track.target} ({track.chain}) is not a target of this rig",
                )
            )
    if not all(math.isfinite(v) for v in _numbers(clip)):
        issues.append(_issue(IssueCode.NON_FINITE, "the clip contains a NaN or infinite value"))
    return issues


def _frames(clip: AnimationClip, skeleton: Skeleton) -> list[dict[str, WorldBone]]:
    return [
        forward(
            skeleton,
            {bone: values[i] for bone, values in clip.rotations.items()},
            {bone: points[i] for bone, points in clip.positions.items()},
        )
        for i in range(clip.frame_count)
    ]


def _step(a: float, b: float) -> float:
    return abs(normalize_angle(b - a))


def validate_clip(clip: AnimationClip, skeleton: Skeleton) -> ValidationReport:
    issues = _fit(clip, skeleton)
    if issues:
        return ValidationReport(issues=issues)

    H = skeleton.height
    frames = _frames(clip, skeleton)
    rest = forward(skeleton)
    by_name = {b.name: b for b in skeleton.bones}
    chains = {c.name: c for c in skeleton.ik_chains}
    metrics: dict[str, float] = {"frame_count": clip.frame_count, "ground_speed": clip.ground_speed}

    # IK targets sit on their effectors
    worst = 0.0
    for track in clip.ik_targets:
        effector = track.target[len("target_") :]
        for i, frame in enumerate(frames):
            worst = max(worst, math.dist(frame[effector].head, track.positions[i]) / H)
            worst = max(worst, _step(frame[effector].angle, track.rotations_deg[i]) / 360.0)
    metrics["max_target_error"] = worst
    if worst > TARGET_TOLERANCE:
        issues.append(
            _issue(
                IssueCode.IK_TARGET_MISMATCH,
                f"an IK target is {worst * 100:.3f}% of the height away from its hand or foot; Unity's solver would pull the limb elsewhere",
            )
        )

    # joints bend their own way, torso and ankles stay in range
    worst_bend = 0.0
    for chain in chains.values():
        sign = bend_sign(chain.bend_side)
        for frame in frames:
            bend = sign * normalize_angle(frame[chain.joint].angle - frame[chain.root].angle)
            worst_bend = max(worst_bend, bend)
            if bend < -WRONG_WAY_DEG or bend > MAX_BEND_DEG:
                issues.append(
                    _issue(
                        IssueCode.JOINT_LIMIT,
                        f"{chain.joint} bends {bend:.0f}° ({'the wrong way' if bend < 0 else 'too far'})",
                        [chain.joint],
                    )
                )
                break
    metrics["max_joint_bend_deg"] = worst_bend
    for bone in TORSO:
        if bone in clip.rotations:
            off = max(_step(by_name[bone].local_rotation_deg, v) for v in clip.rotations[bone])
            if off > MAX_TORSO_DEG:
                issues.append(
                    _issue(
                        IssueCode.JOINT_LIMIT,
                        f"{bone} turns {off:.0f}° from rest (limit {MAX_TORSO_DEG:.0f}°)",
                        [bone],
                    )
                )
    for chain in chains.values():
        if chain.effector and chain.name.startswith("leg_") and chain.effector in clip.rotations:
            off = max(
                _step(by_name[chain.effector].local_rotation_deg, v)
                for v in clip.rotations[chain.effector]
            )
            if off > MAX_ANKLE_DEG:
                issues.append(
                    _issue(
                        IssueCode.JOINT_LIMIT,
                        f"{chain.effector} turns {off:.0f}° at the ankle (limit {MAX_ANKLE_DEG:.0f}°)",
                        [chain.effector],
                    )
                )

    # feet: on the ground they move at ground speed; they never go below it
    per_frame = clip.ground_speed / clip.fps
    direction = -1.0 if skeleton.view == "side" else 0.0  # side view faces +X: the ground runs back
    worst_slip, lowest = 0.0, 0.0
    for chain in chains.values():
        if not (chain.name.startswith("leg_") and chain.effector):
            continue
        foot = chain.effector
        toe = "toe" + foot[4:]
        ground = rest[foot].head[1]
        for i, frame in enumerate(frames):
            points = [frame[foot].head, frame[foot].tail] + (
                [frame[toe].tail] if toe in frame else []
            )
            lowest = max(lowest, max(ground - y for _, y in points) / H)
            if i + 1 == len(frames):
                break
            nxt = frames[i + 1]
            on_ground = frame[foot].head[1] <= ground + CONTACT_HEIGHT * H
            stays = nxt[foot].head[1] <= ground + CONTACT_HEIGHT * H
            if on_ground and stays:
                moved = nxt[foot].head[0] - frame[foot].head[0]
                worst_slip = max(worst_slip, abs(moved - direction * per_frame) / H)
    metrics["max_foot_slip"] = worst_slip
    metrics["max_ground_penetration"] = lowest
    if worst_slip > SLIP_TOLERANCE:
        issues.append(
            _issue(
                IssueCode.FOOT_SLIDING,
                f"a planted foot slides {worst_slip * 100:.2f}% of the height per frame against the ground (limit {SLIP_TOLERANCE * 100:.1f}%)",
            )
        )
    if lowest > GROUND_TOLERANCE:
        issues.append(
            _issue(
                IssueCode.GROUND_PENETRATION,
                f"a foot goes {lowest * 100:.2f}% of the height below the ground",
            )
        )

    # no other part of the body goes through the floor (y = 0, where the root stands) either: a
    # flip too low to clear the head is caught here. A prop that already stands on the floor at
    # rest (a staff held down to the ground) is left out: it would really stay planted while the
    # hand slides on it, which the baked clip does not model, and the bob of an idle would
    # otherwise count as sinking it.
    skip = {c.effector for c in chains.values() if c.name.startswith("leg_") and c.effector}
    skip |= {"toe" + f[4:] for f in skip}
    skip |= {
        name
        for name, placed in rest.items()
        if min(placed.head[1], placed.tail[1]) <= GROUND_TOLERANCE * H
    }
    worst_body, deepest = 0.0, ""
    for frame in frames:
        for name, placed in frame.items():
            if name in skip:
                continue
            depth = -min(placed.head[1], placed.tail[1]) / H
            if depth > worst_body:
                worst_body, deepest = depth, name
    metrics["max_body_below_floor"] = worst_body
    if worst_body > GROUND_TOLERANCE:
        issues.append(
            _issue(
                IssueCode.GROUND_PENETRATION,
                f"{deepest} goes {worst_body * 100:.2f}% of the height below the floor",
                [deepest],
            )
        )

    # a looping clip ends on the pose it started from
    worst_gap, open_tracks = 0.0, []
    for bone, values in clip.rotations.items():
        gap = _step(values[0], values[-1])
        worst_gap = max(worst_gap, gap)
        if gap > LOOP_TOLERANCE:
            open_tracks.append(bone)
    point_tracks = list(clip.positions.items()) + [(t.target, t.positions) for t in clip.ik_targets]
    for name, points in point_tracks:
        gap = math.dist(points[0], points[-1]) / H
        worst_gap = max(worst_gap, gap)
        if gap > LOOP_TOLERANCE:
            open_tracks.append(name)
    for track in clip.ik_targets:
        gap = _step(track.rotations_deg[0], track.rotations_deg[-1])
        worst_gap = max(worst_gap, gap)
        if gap > LOOP_TOLERANCE:
            open_tracks.append(track.target)
    metrics["loop_error"] = worst_gap
    if clip.loop and open_tracks:
        issues.append(
            _issue(
                IssueCode.LOOP_DISCONTINUITY,
                f"the clip loops but its last frame is not its first pose on {sorted(set(open_tracks))}; it would jump when it restarts",
                [n for n in open_tracks if n in by_name],
            )
        )

    return ValidationReport(issues=issues, metrics=metrics)
