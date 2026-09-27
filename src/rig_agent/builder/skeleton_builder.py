"""Turns a RigSpec into a Skeleton: head/tail positions, local transforms, depth (LLD 3.4 #4)."""

import re
from dataclasses import asdict

import rig_agent
from rig_agent.builder.extras import place_extras
from rig_agent.builder.geometry import Placed, normalize_angle, world_to_local
from rig_agent.builder.layout_front import layout_front
from rig_agent.builder.layout_side import layout_side
from rig_agent.builder.proportions import resolve_proportions
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.skeleton import Bone, IKChainInfo, Metadata, Skeleton
from rig_agent.vocabulary.bones import BONES, present_bones
from rig_agent.vocabulary.poses import ik_chain_defs, ik_tags

DECIMALS = 6


def _r(value: float) -> float:
    return round(value, DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0


def _point(p: tuple[float, float]) -> tuple[float, float]:
    return (_r(p[0]), _r(p[1]))


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40].strip("_")
    return slug or "rig"


def _twin(name: str, bones: dict[str, Placed]) -> str | None:
    if not name.endswith(("_L", "_R")):
        return None
    twin = name[:-1] + ("R" if name.endswith("_L") else "L")
    return twin if twin in bones else None


def build_skeleton(
    spec: RigSpec,
    source_prompt: str = "",
    rig_name: str | None = None,
    model: str | None = None,
    iterations: int = 1,
) -> Skeleton:
    """Build the full skeleton for a spec. Raises BuildError if the spec cannot be built."""
    props = resolve_proportions(spec)
    canonical = layout_front(spec, props) if spec.view == "front" else layout_side(spec, props)
    present = present_bones(spec.optional_bones)
    placed = [canonical[name] for name in BONES if name in present]
    placed += place_extras(spec, canonical).values()

    by_name = {b.name: b for b in placed}
    ids = {b.name: i for i, b in enumerate(placed)}
    ik = ik_tags(present)

    bones: list[Bone] = []
    for b in placed:
        if b.parent is None:
            local_position, local_rotation = b.head, normalize_angle(b.angle)
        else:
            parent = by_name[b.parent]
            local_position, local_rotation = world_to_local(
                parent.head, parent.angle, b.head, b.angle
            )
        bones.append(
            Bone(
                id=ids[b.name],
                name=b.name,
                parent_id=ids[b.parent] if b.parent else -1,
                world_head=_point(b.head),
                world_tail=_point(b.tail),
                local_position=_point(local_position),
                local_rotation_deg=_r(local_rotation),
                length=_r(b.length),
                depth=b.depth,
                layer=b.layer,
                ik_chain=ik.get(b.name),
                mirror_of=_twin(b.name, by_name),
            )
        )

    return Skeleton(
        rig_name=rig_name or _slug(spec.character_summary),
        source_prompt=source_prompt,
        height=spec.height_units,
        view=spec.view,
        facing="right" if spec.view == "side" else None,
        rest_pose=spec.rest_pose,
        style=spec.style,
        bones=bones,
        ik_chains=[IKChainInfo(**asdict(c)) for c in ik_chain_defs(present, spec.view)],
        metadata=Metadata(
            generator=f"rig-agent/{rig_agent.__version__}",
            model=model,
            iterations=iterations,
            assumptions=list(spec.assumptions),
        ),
    )
