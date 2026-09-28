"""AnimationSpec (what the planner chooses) and AnimationClip (the baked animation.json).

Same split as RigSpec/Skeleton: the spec is small, semantic and bounded; the clip is every frame,
computed by code (animation/baker.py) and checked by code (animation/validator.py).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rig_agent.vocabulary.bones import View

ANIMATION_SCHEMA_VERSION: Literal["1.0"] = "1.0"

ClipType = Literal["idle", "walk", "run", "backflip"]
CLIP_TYPES: tuple[ClipType, ...] = ("idle", "walk", "run", "backflip")
CLIP_VIEWS: dict[ClipType, tuple[View, ...]] = {
    "idle": ("front", "side"),
    "walk": ("side",),  # a front-view walk would be a march on the spot; not in v1
    "run": ("side",),
    "backflip": ("side",),  # a flip turns about the axis the camera looks along: side view only
}
# Cycles loop; a backflip plays once (it starts and ends in the rest pose, so it can be looped too).
LOOPING_CLIPS: frozenset[ClipType] = frozenset({"idle", "walk", "run"})

Point = tuple[float, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnimationSpec(_Strict):
    """One in-place clip. Every knob is bounded, and 1.0 (or 0 for lean) is neutral.

    For a backflip the knobs mean: speed = how fast, bounce = jump height, knee_lift = how tight
    the tuck, arm_swing = how hard the arms throw; stride and lean_deg have no effect."""

    clip: ClipType
    style: str = Field(min_length=1, max_length=40)  # free label, e.g. "heavy, tired"
    speed: float = Field(1.0, ge=0.5, le=2.0)  # cycles per second, relative to the clip's default
    stride: float = Field(1.0, ge=0.5, le=1.5)  # step length (walk, run)
    bounce: float = Field(1.0, ge=0.0, le=2.0)  # vertical hip motion
    arm_swing: float = Field(1.0, ge=0.0, le=2.0)
    knee_lift: float = Field(1.0, ge=0.5, le=1.5)  # how high the swinging foot rises (walk, run)
    lean_deg: float = Field(0.0, ge=-10.0, le=25.0)  # torso lean; positive = forward (side view)
    fps: int = Field(24, ge=12, le=60)
    assumptions: list[str] = Field(default_factory=list, max_length=5)


class IKTargetTrack(_Strict):
    """Where one IK target sits on every frame, in the rig root's space (the space of
    skeleton.json's world coordinates). Unity's IK/<chain>/target_<effector> follows it."""

    chain: str  # arm_L, arm_R, leg_L or leg_R
    target: str  # the target object's name, e.g. target_foot_R
    positions: list[Point]
    rotations_deg: list[float]  # the effector's world angle (the solver copies it)


class AnimationClip(_Strict):
    """Every frame of one clip, keyed at t = i / fps for i in 0..frame_count-1. In a looping clip
    the last frame is the same pose as the first (the closing key), so the clip plays for
    (frame_count - 1) / fps seconds and then starts over without a jump."""

    schema_version: Literal["1.0"] = ANIMATION_SCHEMA_VERSION
    rig_name: str
    name: str  # usually the clip type, e.g. "walk"
    clip: ClipType
    view: View
    fps: int = Field(gt=0)
    frame_count: int = Field(ge=2)
    loop: bool = True
    # in-place cycles: the speed (world units per second) the game should move the character at
    # so the planted feet do not slide; 0 for idle
    ground_speed: float = Field(ge=0.0)
    # animated bones only; any other bone keeps its skeleton.json rest transform
    rotations: dict[str, list[float]]  # local_rotation_deg per frame
    positions: dict[str, list[Point]]  # local_position per frame
    ik_targets: list[IKTargetTrack] = Field(default_factory=list)
    spec: AnimationSpec
    generator: str

    @property
    def duration_s(self) -> float:
        return (self.frame_count - 1) / self.fps

    @model_validator(mode="after")
    def every_track_has_every_frame(self):
        lengths = {len(v) for v in self.rotations.values()}
        lengths |= {len(v) for v in self.positions.values()}
        for track in self.ik_targets:
            lengths |= {len(track.positions), len(track.rotations_deg)}
        wrong = lengths - {self.frame_count}
        if wrong:
            raise ValueError(f"every track needs {self.frame_count} frames, found {sorted(wrong)}")
        return self
