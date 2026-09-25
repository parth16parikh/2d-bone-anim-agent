"""RigSpec: the Planner Agent's semantic, coordinate-free output (LLD 3.5a)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rig_agent.vocabulary.bones import View, token_views
from rig_agent.vocabulary.poses import RestPose
from rig_agent.vocabulary.presets import BANDS, Preset

OptionalBone = Literal["chest", "neck", "spine_2", "hands", "shoulders", "toes", "jaw"]
MAX_EXTRA_BONES = 16


def _base_field(name: str) -> Any:
    low, high = BANDS[name]
    return Field(None, ge=low, le=high)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaseProportions(_Strict):
    """Absolute values. Any left as None come from the preset (LLD 2.4.1)."""

    heads_tall: float | None = _base_field("heads_tall")
    shoulder_width_hu: float | None = _base_field("shoulder_width_hu")  # front only
    hip_spacing_hu: float | None = _base_field("hip_spacing_hu")
    leg_ratio: float | None = _base_field("leg_ratio")  # fraction of H
    arm_ratio: float | None = _base_field("arm_ratio")  # fraction of H


class ProportionOverrides(_Strict):
    """Bounded multipliers applied on top of the preset and base values (LLD 2.4.3)."""

    head_scale: float = Field(1.0, ge=0.5, le=1.5)
    torso_scale: float = Field(1.0, ge=0.5, le=1.5)
    arm_scale: float = Field(1.0, ge=0.5, le=1.5)
    leg_scale: float = Field(1.0, ge=0.5, le=1.5)
    shoulder_width_scale: float = Field(1.0, ge=0.5, le=1.5)  # front view only
    thigh_shin_bias: float = Field(1.0, ge=0.7, le=1.3)
    upper_forearm_bias: float = Field(1.0, ge=0.7, le=1.3)
    hand_size: float = Field(1.0, ge=0.5, le=1.5)
    foot_size: float = Field(1.0, ge=0.5, le=1.5)
    neck_scale: float = Field(1.0, ge=0.5, le=1.5)
    chest_bias: float = Field(1.0, ge=0.7, le=1.3)


class ExtraBoneSpec(_Strict):
    """One accessory chain: hair, cape, weapon, ears (LLD 2.6)."""

    name: str = Field(pattern=r"^extra_[a-z0-9_]+$")
    parent: str  # must be present in the rig
    attach_at: Literal["head", "tail"] = "tail"  # which end of the parent it attaches to
    direction_deg: float = Field(ge=-180, le=180)  # world angle, 0 = +X, -90 = down
    length_ratio: float = Field(ge=0.01, le=0.6)  # TOTAL chain length, fraction of height
    segments: int = Field(1, ge=1, le=4)  # split the total into N equal, straight bones
    layer: Literal["front", "behind"] = "front"  # draw side relative to the parent bone
    mirror: bool = False  # also create the twin


def extra_bone_count(extra_bones: list[ExtraBoneSpec]) -> int:
    """Bones the extras create: every chain segment and every mirrored twin counts."""
    return sum(e.segments * (2 if e.mirror else 1) for e in extra_bones)


class RigSpec(_Strict):
    character_summary: str = Field(max_length=200)
    style: str = Field(min_length=1, max_length=40)  # free label, e.g. "chibi", "gaunt"
    preset: Preset = "realistic"  # starting point for the proportions
    view: View
    rest_pose: RestPose  # A_pose or T_pose for front, side_neutral for side
    height_units: float = Field(2.0, gt=0.2, le=10)  # Unity world units
    base: BaseProportions = BaseProportions()
    overrides: ProportionOverrides = ProportionOverrides()
    optional_bones: list[OptionalBone] = Field(default_factory=list)
    extra_bones: list[ExtraBoneSpec] = Field(default_factory=list, max_length=MAX_EXTRA_BONES)
    assumptions: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def pose_matches_view(self):
        if (self.view == "side") != (self.rest_pose == "side_neutral"):
            raise ValueError("side view needs side_neutral; front view needs A_pose or T_pose")
        return self

    @model_validator(mode="after")
    def view_limits(self):
        if self.view == "side" and (
            self.overrides.shoulder_width_scale != 1.0 or self.base.shoulder_width_hu is not None
        ):
            raise ValueError("shoulder width applies to the front view only")
        for token in self.optional_bones:
            if self.view not in token_views(token):
                raise ValueError(
                    f"optional bone '{token}' is not available in the {self.view} view"
                )
        return self

    @model_validator(mode="after")
    def extra_bone_budget(self):
        total = extra_bone_count(self.extra_bones)
        if total > MAX_EXTRA_BONES:
            raise ValueError(
                f"extra bones (segments and mirrors included) total {total}; "
                f"the limit is {MAX_EXTRA_BONES}"
            )
        return self
