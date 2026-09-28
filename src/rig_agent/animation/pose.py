"""Forward kinematics: a skeleton's local transforms (optionally overridden per bone) to world
positions, with the same maths the builder uses to go the other way (builder/geometry.py)."""

from collections.abc import Mapping
from dataclasses import dataclass

from rig_agent.builder.geometry import Point, advance, local_to_world
from rig_agent.schemas.skeleton import Bone, Skeleton


@dataclass(frozen=True)
class WorldBone:
    head: Point
    angle: float  # world angle in degrees
    length: float

    @property
    def tail(self) -> Point:
        return advance(self.head, self.angle, self.length)


def forward(
    skeleton: Skeleton,
    rotations: Mapping[str, float] | None = None,
    positions: Mapping[str, Point] | None = None,
) -> dict[str, WorldBone]:
    """Every bone's world head and angle. `rotations` and `positions` replace a bone's
    local_rotation_deg and local_position; bones not named keep their rest values."""
    rotations = rotations or {}
    positions = positions or {}
    by_id = {b.id: b for b in skeleton.bones}
    world: dict[str, WorldBone] = {}

    def place(bone: Bone) -> WorldBone:
        if bone.name in world:
            return world[bone.name]
        local_position = positions.get(bone.name, bone.local_position)
        local_rotation = rotations.get(bone.name, bone.local_rotation_deg)
        parent = by_id.get(bone.parent_id)
        if parent is None:  # the root: its local transform is its world transform
            head, angle = local_position, local_rotation
        else:
            p = place(parent)
            head, angle = local_to_world(p.head, p.angle, local_position, local_rotation)
        world[bone.name] = WorldBone(head, angle, bone.length)
        return world[bone.name]

    for bone in skeleton.bones:
        place(bone)
    return world
