"""Skeleton: the fully computed artifact serialized to skeleton.json (LLD 3.5b)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_agent.vocabulary.bones import View
from rig_agent.vocabulary.poses import RestPose

SCHEMA_VERSION: Literal["1.0"] = "1.0"

Point = tuple[float, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Bone(_Strict):
    id: int = Field(ge=0)
    name: str
    parent_id: int = Field(ge=-1)  # -1 for the root
    world_head: Point
    world_tail: Point
    local_position: Point
    local_rotation_deg: float
    length: float
    depth: int  # positive toward the camera, negative away from it, 0 = torso plane
    layer: Literal["front", "behind"] | None = None  # extra bones only
    rotation_limits_deg: tuple[float, float] | None = None
    ik_chain: str | None = None
    mirror_of: str | None = None


class Metadata(_Strict):
    generator: str
    model: str | None = None
    iterations: int = Field(1, ge=1)
    assumptions: list[str] = Field(default_factory=list)


class Skeleton(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    rig_name: str
    source_prompt: str
    units: Literal["unity_world"] = "unity_world"
    pixels_per_unit: int = Field(100, gt=0)
    height: float = Field(gt=0)
    view: View
    facing: Literal["right"] | None = None  # side view only
    rest_pose: RestPose
    style: str
    bones: list[Bone]
    metadata: Metadata
