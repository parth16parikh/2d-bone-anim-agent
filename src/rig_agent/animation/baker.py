"""bake(): an AnimationSpec and a Skeleton become an AnimationClip, frame by frame.

For each frame the template says where the hip, torso, arms and feet should be; the baker lowers
the hip if a leg could not reach its foot, solves each leg with two-bone IK (with the rig's own
bend sides), and then reads every IK target off the final pose. So the rotation curves and the IK
target curves describe the same motion: Unity's solvers re-solving from the targets land on the
same pose, and a rig built without IK plays correctly from the rotations alone.
"""

import math
from dataclasses import dataclass, replace

import rig_agent
from rig_agent.animation.ik import solve_two_bone
from rig_agent.animation.pose import WorldBone, forward
from rig_agent.animation.templates import (
    MAX_EXTENSION,
    TEMPLATES,
    Intent,
    RigInfo,
    Template,
    cycle_frames,
    ground_speed,
)
from rig_agent.builder.geometry import Point, normalize_angle
from rig_agent.schemas.animation import (
    CLIP_VIEWS,
    LOOPING_CLIPS,
    AnimationClip,
    AnimationSpec,
    IKTargetTrack,
)
from rig_agent.schemas.skeleton import Skeleton

DECIMALS = 6
HIP = "hip"
AIR_MARGIN = 0.01  # fraction of H every bone keeps above the floor in the air


class BakeError(ValueError):
    """The spec cannot be baked onto this rig (for example a walk on a front-view rig)."""


def _r(value: float) -> float:
    return round(value, DECIMALS) + 0.0


def _max_hip_rise(rig: RigInfo, intent: Intent, dx: float, extension: float) -> float:
    """The highest hip offset at which every leg still reaches its foot with a slightly bent knee."""
    limit = math.inf
    for chain_name, (ankle, _) in intent.feet.items():
        chain = rig.chains[chain_name]
        thigh = rig.rest[chain.root]
        reach = extension * (thigh.length + rig.rest[chain.joint].length)
        across = ankle[0] - (thigh.head[0] + dx)
        if abs(across) < reach:
            limit = min(
                limit, ankle[1] + math.sqrt(reach * reach - across * across) - thigh.head[1]
            )
    return limit


def _unwrap(values: list[float], start: float) -> list[float]:
    """Keep an angle track continuous (no 179 -> -179 jumps, which Unity would play as a spin)."""
    out, previous = [], start
    for value in values:
        previous = previous + normalize_angle(value - previous)
        out.append(_r(previous))
    return out


@dataclass(frozen=True)
class _Frame:
    intent: Intent
    local: dict[str, float]  # local rotations that differ from rest
    hip_local: Point
    world: dict[str, WorldBone]


def _pose(
    spec: AnimationSpec, rig: RigInfo, template: Template, p: float, extension: float
) -> _Frame:
    """One frame: the template's intent made physical (hip clamped to the feet, legs solved)."""
    skeleton = rig.skeleton
    by_name = {b.name: b for b in skeleton.bones}
    by_id = {b.id: b for b in skeleton.bones}
    hip = by_name[HIP]
    hip_parent_angle = rig.rest[by_id[hip.parent_id].name].angle if hip.parent_id in by_id else 0.0

    intent = template(spec, rig, p)
    local = {bone: by_name[bone].local_rotation_deg + d for bone, d in intent.deltas.items()}
    dx, dy = intent.hip_offset
    if not intent.airborne:  # in the air nothing holds the hip down to the feet
        dy = min(dy, _max_hip_rise(rig, intent, dx, extension))
    a = math.radians(-hip_parent_angle)  # the offset is in world space; the hip is in its parent's
    hip_local = (
        hip.local_position[0] + dx * math.cos(a) - dy * math.sin(a),
        hip.local_position[1] + dx * math.sin(a) + dy * math.cos(a),
    )
    positions = {HIP: hip_local}

    world = forward(skeleton, local, positions)
    for chain_name, (ankle, foot_angle) in intent.feet.items():
        chain = rig.chains[chain_name]
        assert chain.effector is not None
        upper, lower = world[chain.root], world[chain.joint]
        solved = solve_two_bone(upper.head, ankle, upper.length, lower.length, chain.bend_side)
        parent_angle = world[by_id[by_name[chain.root].parent_id].name].angle
        local[chain.root] = solved.upper_deg - parent_angle
        local[chain.joint] = solved.lower_deg - solved.upper_deg
        local[chain.effector] = foot_angle - solved.lower_deg
    return _Frame(intent, local, hip_local, forward(skeleton, local, positions))


def _needed_lift(frames: list[_Frame], rig: RigInfo) -> float:
    """How much higher an airborne arc must peak for every bone to clear the floor (y = 0; the
    feet, which stand on the ankle line, must clear that). Raising the peak lifts the whole body
    by `arc` times as much at each frame, so one correction is enough."""
    H = rig.skeleton.height
    feet = {rig.chains[c].effector: y for c, (_, y) in rig.ankle.items()}
    floors = dict(feet) | {"toe" + f[4:]: y for f, y in feet.items() if f}
    need = 0.0
    for frame in frames:
        if not frame.intent.airborne or frame.intent.arc <= 1e-6:
            continue
        below = max(
            floors.get(name, 0.0) + AIR_MARGIN * H - min(bone.head[1], bone.tail[1])
            for name, bone in frame.world.items()
        )
        if below > 0:
            need = max(need, below / frame.intent.arc)
    return need


def bake(spec: AnimationSpec, skeleton: Skeleton, name: str | None = None) -> AnimationClip:
    if skeleton.view not in CLIP_VIEWS[spec.clip]:
        allowed = " or ".join(CLIP_VIEWS[spec.clip])
        raise BakeError(
            f"a {spec.clip} clip needs a {allowed}-view rig; this rig is {skeleton.view} view"
        )
    if HIP not in {b.name for b in skeleton.bones}:
        raise BakeError("the rig has no hip bone")
    rig = RigInfo.of(skeleton)
    template = TEMPLATES[spec.clip]
    extension = MAX_EXTENSION[spec.clip]
    hip = next(b for b in skeleton.bones if b.name == HIP)
    effectors = {
        c.name: c.effector for c in rig.chains.values() if c.effector
    }  # chain -> hand/foot

    n = cycle_frames(spec)
    frames = [_pose(spec, rig, template, i / n, extension) for i in range(n + 1)]
    lift = _needed_lift(frames, rig)
    if lift > 0:  # the body would go through the floor in the air: jump higher, then pose again
        rig = replace(rig, air_lift=lift)
        frames = [_pose(spec, rig, template, i / n, extension) for i in range(n + 1)]

    # n + 1 frames: the last is the template at phase 1.0, computed rather than copied from frame 0,
    # so it is both the loop's closing key and a real check that the motion is periodic
    rotations: dict[str, list[float]] = {b.name: [] for b in skeleton.bones}
    hip_track: list[Point] = []
    targets: dict[str, tuple[list[Point], list[float]]] = {c: ([], []) for c in effectors}
    for frame in frames:
        for bone in skeleton.bones:
            rotations[bone.name].append(frame.local.get(bone.name, bone.local_rotation_deg))
        hip_track.append((_r(frame.hip_local[0]), _r(frame.hip_local[1])))
        for chain_name, effector_name in effectors.items():
            effector = frame.world[effector_name]
            targets[chain_name][0].append((_r(effector.head[0]), _r(effector.head[1])))
            targets[chain_name][1].append(effector.angle)

    animated = {}
    for bone in skeleton.bones:
        rest = bone.local_rotation_deg
        if any(abs(normalize_angle(v - rest)) > 1e-7 for v in rotations[bone.name]):
            animated[bone.name] = _unwrap(rotations[bone.name], rest)
    positions_out = {}
    if any(p != (_r(hip.local_position[0]), _r(hip.local_position[1])) for p in hip_track):
        positions_out[HIP] = hip_track

    return AnimationClip(
        rig_name=skeleton.rig_name,
        name=name or spec.clip,
        clip=spec.clip,
        view=skeleton.view,
        fps=spec.fps,
        frame_count=n + 1,
        loop=spec.clip in LOOPING_CLIPS,
        ground_speed=_r(ground_speed(spec, rig)),
        rotations=animated,
        positions=positions_out,
        ik_targets=[
            IKTargetTrack(
                chain=chain_name,
                target=f"target_{effector_name}",
                positions=targets[chain_name][0],
                rotations_deg=_unwrap(targets[chain_name][1], rig.rest[effector_name].angle),
            )
            for chain_name, effector_name in effectors.items()
        ],
        spec=spec,
        generator=f"rig-agent/{rig_agent.__version__}",
    )
