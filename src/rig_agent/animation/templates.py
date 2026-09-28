"""The motion of each clip type as a function of the cycle phase p in [0, 1): what the hip, torso
and arms do, and where each foot is. Pure and periodic, so a clip loops exactly.

A template says *what* should happen (a foot here, the chest tilted this much); the baker turns
that into bone rotations with IK and makes it physically consistent (for example it lowers the hip
if a leg could not otherwise reach its foot).
"""

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from rig_agent.animation.ik import bend_sign
from rig_agent.animation.pose import WorldBone, forward
from rig_agent.builder.geometry import Point
from rig_agent.schemas.animation import AnimationSpec, ClipType
from rig_agent.schemas.skeleton import IKChainInfo, Skeleton

TAU = 2 * math.pi

# Seconds per cycle at speed 1.0. Walk and run cycles hold two steps (one per leg).
CYCLE_SECONDS: dict[ClipType, float] = {"idle": 3.0, "walk": 1.1, "run": 0.7, "backflip": 1.3}
# How straight a leg may get: a gait keeps the knees a little bent, which also keeps IK stable.
MAX_EXTENSION: dict[ClipType, float] = {"idle": 1.0, "walk": 0.985, "run": 0.97, "backflip": 1.0}


@dataclass(frozen=True)
class RigInfo:
    """What the templates need to know about a rig, measured from its rest pose."""

    skeleton: Skeleton
    rest: dict[str, WorldBone]
    chains: dict[str, IKChainInfo]
    leg_length: float  # mean thigh + shin
    ankle: dict[str, Point]  # rest ankle (foot head) per leg chain
    foot_angle: dict[str, float]  # rest foot world angle per leg chain
    foot_reach: dict[str, float]  # foot plus toe length: how far the sole reaches past the ankle
    holding: frozenset[str] = frozenset()  # hands that hold an accessory (an extra bone on them)
    # extra height an airborne arc must reach so the body clears the floor; the baker sets it
    air_lift: float = 0.0

    @classmethod
    def of(cls, skeleton: Skeleton) -> "RigInfo":
        rest = forward(skeleton)
        chains = {c.name: c for c in skeleton.ik_chains}
        legs = [c for c in chains.values() if c.name.startswith("leg_") and c.effector]
        names = {b.name for b in skeleton.bones}
        leg_length = sum(rest[c.root].length + rest[c.joint].length for c in legs) / len(legs)
        ankle, foot_angle, foot_reach = {}, {}, {}
        for c in legs:
            assert c.effector is not None
            foot = rest[c.effector]
            toe = "toe" + c.effector[4:]  # foot_L -> toe_L
            ankle[c.name] = foot.head
            foot_angle[c.name] = foot.angle
            foot_reach[c.name] = foot.length + (rest[toe].length if toe in names else 0.0)
        by_id = {b.id: b.name for b in skeleton.bones}
        holding = frozenset(
            by_id[b.parent_id]
            for b in skeleton.bones
            if b.name.startswith("extra_") and by_id.get(b.parent_id, "").startswith("hand_")
        )
        return cls(skeleton, rest, chains, leg_length, ankle, foot_angle, foot_reach, holding)

    def has(self, bone: str) -> bool:
        return bone in self.rest


@dataclass
class Intent:
    """One frame, as the template wants it."""

    hip_offset: Point = (0.0, 0.0)  # world units, from the rest hip; the baker may lower it
    deltas: dict[str, float] = field(default_factory=dict)  # degrees added to rest local rotations
    feet: dict[str, tuple[Point, float]] = field(
        default_factory=dict
    )  # leg chain -> ankle, foot angle
    airborne: bool = False  # the feet are off the ground: the baker must not lower the hip to them
    arc: float = 0.0  # in the air: the share of any extra lift (air_lift) applied at this frame


Template = Callable[[AnimationSpec, RigInfo, float], Intent]


def _add(deltas: dict[str, float], rig: RigInfo, bone: str, degrees: float) -> None:
    if rig.has(bone):
        deltas[bone] = deltas.get(bone, 0.0) + degrees


def _lean(deltas: dict[str, float], rig: RigInfo, lean: float) -> None:
    """Tilt the torso forward by `lean` degrees (side view, facing +X: forward is clockwise) and
    turn the head back by most of it, so the character keeps looking ahead."""
    upper = "chest" if rig.has("chest") else None
    _add(deltas, rig, "spine", -lean * (0.6 if upper else 1.0))
    if upper:
        _add(deltas, rig, upper, -lean * 0.4)
    _add(deltas, rig, "neck" if rig.has("neck") else "head", lean * 0.7)


def _hermite(p0: float, p1: float, m0: float, m1: float, s: float) -> float:
    s2, s3 = s * s, s * s * s
    return (
        (2 * s3 - 3 * s2 + 1) * p0
        + (s3 - 2 * s2 + s) * m0
        + (-2 * s3 + 3 * s2) * p1
        + (s3 - s2) * m1
    )


def idle(spec: AnimationSpec, rig: RigInfo, p: float) -> Intent:
    """Breathing: the hip dips (the knees give a little), the chest rises, the head follows late,
    the arms sway. Feet stay planted. Works in both views; lean is side view only."""
    intent = Intent()
    dip = spec.bounce * 0.012 * rig.leg_length * (0.5 - 0.5 * math.cos(TAU * p))
    intent.hip_offset = (0.0, -dip)
    _add(
        intent.deltas,
        rig,
        "chest" if rig.has("chest") else "spine",
        0.8 * spec.bounce * math.sin(TAU * p),
    )
    _add(intent.deltas, rig, "head", 1.2 * math.sin(TAU * (p - 0.15)))
    if rig.skeleton.view == "side":
        _lean(intent.deltas, rig, spec.lean_deg)
    sway = spec.arm_swing * 3.0 * math.sin(TAU * (p + 0.25))
    for chain_name, mirror in (("arm_L", 1.0), ("arm_R", -1.0)):
        chain = rig.chains.get(chain_name)
        if chain is None:
            continue
        # front view: both arms sway outward together (mirrored); side view: the same way
        direction = mirror if rig.skeleton.view == "front" else 1.0
        _add(intent.deltas, rig, chain.root, direction * sway)
        _add(
            intent.deltas,
            rig,
            chain.joint,
            bend_sign(chain.bend_side) * (4.0 + 1.5 * math.sin(TAU * p)),
        )
    for chain_name in rig.ankle:
        intent.feet[chain_name] = (rig.ankle[chain_name], rig.foot_angle[chain_name])
    return intent


def _gait(spec: AnimationSpec, rig: RigInfo, p: float, run: bool) -> Intent:
    """A side-view walk or run on the spot, facing +X. A planted foot moves back at a constant
    ground speed (as on a treadmill); the swinging foot comes forward on a smooth arc."""
    intent = Intent()
    L = rig.leg_length
    g = gait_numbers(spec, rig)
    duty, step, belt = g.duty, g.step, g.speed
    swing_time = (1 - duty) * g.period
    lift = spec.knee_lift * (0.28 if run else 0.14) * L

    for chain_name, offset in (("leg_R", 0.0), ("leg_L", 0.5)):
        if chain_name not in rig.ankle:
            continue
        q = (p + offset) % 1.0
        rest_x, rest_y = rig.ankle[chain_name]
        if q < duty:
            x, y, angle = step / 2 - step * (q / duty), 0.0, 0.0
        else:
            s = (q - duty) / (1 - duty)
            # leaves and lands moving at ground speed, so there is no jolt at either end
            x = _hermite(-step / 2, step / 2, -belt * swing_time, -belt * swing_time, s)
            y = lift * math.sin(math.pi * s)
            angle = spec.knee_lift * (
                -30.0 * math.sin(math.pi * s) * (1 - s) + 12.0 * math.sin(math.pi * s) * s
            )
            if angle < 0:  # toe down: raise the ankle so the toe stays on or above the ground
                y = max(y, rig.foot_reach[chain_name] * math.sin(math.radians(-angle)))
        intent.feet[chain_name] = ((rest_x + x, rest_y + y), rig.foot_angle[chain_name] + angle)

    # the hip is highest at mid-stance (walk) or mid-flight (run), twice per cycle
    peak = (duty + 0.5) / 2 if run else duty / 2
    rise = spec.bounce * (0.05 if run else 0.025) * L
    intent.hip_offset = (0.0, -(0.03 * L if run else 0.0) + rise * math.cos(2 * TAU * (p - peak)))

    _lean(intent.deltas, rig, spec.lean_deg + (8.0 if run else 2.0))
    _add(intent.deltas, rig, "spine", 1.5 * spec.bounce * math.sin(2 * TAU * p))

    amplitude = spec.arm_swing * (35.0 if run else 20.0)
    elbow = 75.0 if run else 12.0
    for chain_name, sign in (("arm_R", -1.0), ("arm_L", 1.0)):
        chain = rig.chains.get(chain_name)
        if chain is None:
            continue
        swing = sign * amplitude * math.cos(TAU * p)  # opposite to the same side's leg
        forward_share = max(0.0, swing / amplitude) if amplitude else 0.0
        _add(intent.deltas, rig, chain.root, swing)
        _add(
            intent.deltas,
            rig,
            chain.joint,
            bend_sign(chain.bend_side) * (elbow + (25.0 if run else 18.0) * forward_share),
        )
    return intent


def _smooth(s: float) -> float:
    """Smootherstep: 0 -> 1 with zero velocity and acceleration at both ends."""
    s = min(max(s, 0.0), 1.0)
    return s * s * s * (s * (6 * s - 15) + 10)


def _keys(p: float, points: list[tuple[float, float]]) -> float:
    """A value that eases between (phase, value) keys; held before the first and after the last."""
    if p <= points[0][0]:
        return points[0][1]
    for (p0, v0), (p1, v1) in itertools.pairwise(points):
        if p <= p1:
            return v0 + (v1 - v0) * _smooth((p - p0) / (p1 - p0))
    return points[-1][1]


TAKEOFF, LANDING = 0.35, 0.80  # the share of the clip spent before leaving and before landing


def backflip(spec: AnimationSpec, rig: RigInfo, p: float) -> Intent:
    """A standing backflip, side view, facing +X; in place, starting and ending in the rest pose.

    Crouch (arms swing back) -> take off (arms throw up) -> in the air the whole body turns 360°
    backwards (counter-clockwise) about the hip while the knees tuck -> land and absorb. On the
    ground the feet are planted; in the air they are placed relative to the turning body, so the
    legs keep their shape as it rotates and Unity's IK reproduces them from the targets."""
    intent = Intent()
    L = rig.leg_length
    crouch = 0.14 * L
    apex = (
        0.1 * spec.bounce * L
    )  # extra height; the baker adds what the body needs to clear the floor
    tuck = 0.6 + 0.4 * (spec.knee_lift - 0.5)  # 0.6 (loose) .. 1.0 (tight)
    arms = min(max(spec.arm_swing, 0.3), 1.2)

    in_air = TAKEOFF <= p < LANDING
    s = (p - TAKEOFF) / (LANDING - TAKEOFF) if in_air else 0.0
    turn = 360.0 * _smooth(s) if in_air else (360.0 if p >= LANDING else 0.0)
    if p < TAKEOFF:
        rise = _keys(p, [(0.0, 0.0), (0.22, -crouch), (TAKEOFF, 0.0)])
    elif in_air:
        rise = (apex + rig.air_lift) * 4 * s * (1 - s)  # a ballistic arc from and to rest height
    else:
        rise = _keys(p, [(LANDING, 0.0), (0.88, -0.8 * crouch), (1.0, 0.0)])
    intent.hip_offset = (0.0, rise)
    _add(intent.deltas, rig, "hip", turn)

    hip = rig.rest["hip"].head
    a = math.radians(turn)
    for chain_name, ankle in rig.ankle.items():
        if not in_air:
            intent.feet[chain_name] = (ankle, rig.foot_angle[chain_name])
            continue
        # the ankle in the body's own frame: from standing, pulled up and forward into a tuck
        amount = tuck * math.sin(math.pi * s) ** 0.7
        rx, ry = ankle[0] - hip[0], ankle[1] - hip[1]
        rx, ry = rx + amount * 0.30 * L, ry * (1 - 0.55 * amount)
        world = (
            hip[0] + rx * math.cos(a) - ry * math.sin(a),
            hip[1] + rise + rx * math.sin(a) + ry * math.cos(a),
        )
        intent.feet[chain_name] = (
            world,
            rig.foot_angle[chain_name] + turn - 25.0 * amount,
        )  # toes pointed
    intent.airborne = in_air
    intent.arc = 4 * s * (1 - s) if in_air else 0.0

    # arms: back in the crouch, thrown up at take-off, down to the knees in the tuck, back to rest
    swing = _keys(
        p,
        [
            (0.0, 0.0),
            (0.18, -40.0),
            (0.33, 140.0),
            (0.5, 130.0),
            (0.65, 60.0),
            (0.8, 20.0),
            (0.9, -10.0),
            (1.0, 0.0),
        ],
    )
    elbow = _keys(p, [(0.0, 0.0), (0.33, 5.0), (0.55, 40.0), (0.8, 10.0), (1.0, 0.0)])
    for chain_name in ("arm_L", "arm_R"):
        chain = rig.chains.get(chain_name)
        if chain is not None:
            _add(intent.deltas, rig, chain.root, arms * swing)
            _add(intent.deltas, rig, chain.joint, bend_sign(chain.bend_side) * elbow)
    # the spine curls forward in the crouch and the tuck, arches back at take-off; the head
    # counters part of it
    curl = _keys(
        p,
        [
            (0.0, 0.0),
            (0.2, 18.0),
            (0.33, -10.0),
            (0.5, 25.0),
            (0.72, 15.0),
            (0.85, 12.0),
            (1.0, 0.0),
        ],
    )
    _add(intent.deltas, rig, "spine", -curl)
    _add(intent.deltas, rig, "neck" if rig.has("neck") else "head", 0.4 * curl)
    return intent


def walk(spec: AnimationSpec, rig: RigInfo, p: float) -> Intent:
    return _gait(spec, rig, p, run=False)


def run(spec: AnimationSpec, rig: RigInfo, p: float) -> Intent:
    return _gait(spec, rig, p, run=True)


WRIST_LIMIT = 70.0  # degrees a wrist may turn to keep a held item steady


def _steady_hands(template: Template) -> Template:
    """A hand holding an accessory (a sword, a staff) turns against the arm's swing, as a real
    wrist does, so the item stays aligned with the body instead of following every swing (a sword
    no longer sweeps over the head in a run or into the floor in a crouch). It still turns with
    the body, as in a flip. The wrist is capped at WRIST_LIMIT."""

    def steadied(spec: AnimationSpec, rig: RigInfo, p: float) -> Intent:
        intent = template(spec, rig, p)
        for chain in rig.chains.values():
            if chain.effector in rig.holding:
                swing = intent.deltas.get(chain.root, 0.0) + intent.deltas.get(chain.joint, 0.0)
                _add(
                    intent.deltas, rig, chain.effector, -max(-WRIST_LIMIT, min(WRIST_LIMIT, swing))
                )
        return intent

    return steadied


_PLAIN: dict[ClipType, Template] = {"idle": idle, "walk": walk, "run": run, "backflip": backflip}
TEMPLATES: dict[ClipType, Template] = {clip: _steady_hands(t) for clip, t in _PLAIN.items()}
GAITS: frozenset[ClipType] = frozenset({"walk", "run"})  # the clips that travel over the ground


@dataclass(frozen=True)
class GaitNumbers:
    duty: float  # share of the cycle a foot is on the ground
    step: float  # how far a planted foot travels back during its stance, world units
    period: float  # seconds per cycle
    speed: float  # ground speed, world units per second


def gait_numbers(spec: AnimationSpec, rig: RigInfo) -> GaitNumbers:
    run_ = spec.clip == "run"
    duty = 0.38 if run_ else 0.62
    step = spec.stride * (0.9 if run_ else 0.55) * rig.leg_length
    period = cycle_frames(spec) / spec.fps  # the real, whole-frame cycle, not the nominal one
    return GaitNumbers(duty, step, period, step / (duty * period))


def cycle_frames(spec: AnimationSpec) -> int:
    """Frame intervals per cycle: the nominal cycle length at this speed, in whole frames."""
    return max(2, round(spec.fps * CYCLE_SECONDS[spec.clip] / spec.speed))


def ground_speed(spec: AnimationSpec, rig: RigInfo) -> float:
    """World units per second the character should travel so its planted feet do not slide."""
    return gait_numbers(spec, rig).speed if spec.clip in GAITS else 0.0
