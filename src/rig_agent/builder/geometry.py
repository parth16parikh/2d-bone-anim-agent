"""Vector maths: angles, mirroring, world/local conversion, and the Placed bone (LLD 3.4 #4)."""

import math
from dataclasses import dataclass
from typing import Literal

Point = tuple[float, float]


def normalize_angle(deg: float) -> float:
    """Wrap an angle into (-180, 180]."""
    wrapped = math.fmod(deg, 360.0)
    if wrapped <= -180.0:
        wrapped += 360.0
    elif wrapped > 180.0:
        wrapped -= 360.0
    return wrapped


def advance(head: Point, deg: float, length: float) -> Point:
    """The point `length` away from `head` along the world angle `deg`."""
    rad = math.radians(deg)
    return (head[0] + length * math.cos(rad), head[1] + length * math.sin(rad))


def mirror_x(point: Point) -> Point:
    """Reflect a point across the Y axis."""
    return (-point[0], point[1])


def mirror_angle(deg: float) -> float:
    """Reflect a world angle across the Y axis: 180° − θ."""
    return normalize_angle(180.0 - deg)


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def world_to_local(
    parent_head: Point, parent_deg: float, child_head: Point, child_deg: float
) -> tuple[Point, float]:
    """A child's position and rotation in its parent's frame (the parent's head is the origin)."""
    dx, dy = child_head[0] - parent_head[0], child_head[1] - parent_head[1]
    rad = math.radians(-parent_deg)
    local = (dx * math.cos(rad) - dy * math.sin(rad), dx * math.sin(rad) + dy * math.cos(rad))
    return local, normalize_angle(child_deg - parent_deg)


def local_to_world(
    parent_head: Point, parent_deg: float, local_position: Point, local_deg: float
) -> tuple[Point, float]:
    """The inverse of world_to_local."""
    rad = math.radians(parent_deg)
    x, y = local_position
    head = (
        parent_head[0] + x * math.cos(rad) - y * math.sin(rad),
        parent_head[1] + x * math.sin(rad) + y * math.cos(rad),
    )
    return head, normalize_angle(parent_deg + local_deg)


@dataclass(frozen=True)
class Placed:
    """A bone with its world-space geometry, before ids and local transforms are assigned."""

    name: str
    parent: str | None
    head: Point
    angle: float  # world angle in degrees
    length: float
    depth: int = 0
    layer: Literal["front", "behind"] | None = None  # extra bones only

    @property
    def tail(self) -> Point:
        return advance(self.head, self.angle, self.length)
