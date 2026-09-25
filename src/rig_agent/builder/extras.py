"""Extra bones: chains, naming, mirrored twins, depth and layer (LLD 2.6)."""

import math
from typing import Literal

from rig_agent.builder.errors import BuildError
from rig_agent.builder.geometry import Placed, Point, mirror_angle, mirror_x
from rig_agent.builder.layout_side import far_limb_offset
from rig_agent.schemas.rig_spec import ExtraBoneSpec, RigSpec


def _side(name: str) -> str | None:
    return name[-1] if name.endswith(("_L", "_R")) else None


def _opposite(name: str) -> str:
    return name[:-1] + ("R" if name.endswith("_L") else "L")


def chain_names(base: str, segments: int, side: str | None = None) -> list[str]:
    """`extra_cape` becomes extra_cape, or extra_cape_1..N; a side goes last (LLD 2.6)."""
    names = [base] if segments == 1 else [f"{base}_{i}" for i in range(1, segments + 1)]
    return [f"{n}_{side}" for n in names] if side else names


def _anchor(parent: Placed, attach_at: str) -> Point:
    return parent.head if attach_at == "head" else parent.tail


def _chain(
    names: list[str],
    parent: str,
    start: Point,
    angle: float,
    segment_length: float,
    depth: int,
    layer: Literal["front", "behind"],
) -> list[Placed]:
    chain: list[Placed] = []
    head, previous = start, parent
    for name in names:
        bone = Placed(name, previous, head, angle, segment_length, depth, layer)
        chain.append(bone)
        head, previous = bone.tail, name
    return chain


def _require(bones: dict[str, Placed], name: str, why: str) -> Placed:
    if name not in bones:
        raise BuildError(f"{why}: '{name}' is not present in the rig")
    return bones[name]


def place_extras(spec: RigSpec, canonical: dict[str, Placed]) -> dict[str, Placed]:
    """The extra bones in creation order. A parent always comes before its children."""
    bones = dict(canonical)
    extras: dict[str, Placed] = {}
    height = spec.height_units

    for e in spec.extra_bones:
        parent = _require(bones, e.parent, f"extra bone '{e.name}' has an unknown parent")
        for chain in _chains_for(e, parent, bones, spec.view, height):
            for bone in chain:
                bones[bone.name] = bone
                extras[bone.name] = bone
    return extras


def _chains_for(
    e: ExtraBoneSpec, parent: Placed, bones: dict[str, Placed], view: str, height: float
) -> list[list[Placed]]:
    segment_length = e.length_ratio * height / e.segments
    anchor = _anchor(parent, e.attach_at)
    if not e.mirror:
        names = chain_names(e.name, e.segments)
        return [
            _chain(names, e.parent, anchor, e.direction_deg, segment_length, parent.depth, e.layer)
        ]

    parent_side = _side(e.parent)
    if parent_side:
        side = parent_side
        twin_parent_name = _opposite(e.parent)
        twin_parent = _require(
            bones, twin_parent_name, f"extra bone '{e.name}' is mirrored but its parent has no twin"
        )
    else:
        twin_parent_name, twin_parent = e.parent, parent
        toward_plus_x = math.cos(math.radians(e.direction_deg)) >= 0
        # side view: the original is the near bone, and the near side is _R (LLD 2.2)
        side = "R" if view == "side" else ("L" if toward_plus_x else "R")
    twin_side = "R" if side == "L" else "L"
    same_parent = twin_parent_name == e.parent

    original = _chain(
        chain_names(e.name, e.segments, side),
        e.parent,
        anchor,
        e.direction_deg,
        segment_length,
        parent.depth,
        e.layer,
    )

    if view == "front":
        angle = mirror_angle(e.direction_deg)
        start = mirror_x(anchor) if same_parent else _anchor(twin_parent, e.attach_at)
        depth = twin_parent.depth
    else:
        angle = e.direction_deg
        if same_parent:
            start = (anchor[0] - far_limb_offset(height), anchor[1])
            depth = parent.depth - 1
        else:
            start = _anchor(twin_parent, e.attach_at)
            depth = twin_parent.depth
    twin = _chain(
        chain_names(e.name, e.segments, twin_side),
        twin_parent_name,
        start,
        angle,
        segment_length,
        depth,
        e.layer,
    )
    return [original, twin]
