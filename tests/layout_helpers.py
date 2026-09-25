"""Shared helpers for the layout, builder and validator tests."""

from rig_agent.builder.geometry import Placed, distance
from rig_agent.builder.layout_front import layout_front
from rig_agent.builder.layout_side import layout_side
from rig_agent.builder.proportions import resolve_proportions
from rig_agent.schemas.rig_spec import RigSpec

EXEMPT_FROM_PARENT_TAIL = ("hip", "jaw")


def make_spec(**kw):
    data = {"character_summary": "c", "style": "s", "view": "front", "rest_pose": "A_pose"}
    data.update(kw)
    return RigSpec.model_validate(data)


def layout(spec: RigSpec):
    props = resolve_proportions(spec)
    placed = layout_front(spec, props) if spec.view == "front" else layout_side(spec, props)
    return placed, props


def is_limb_root(name: str, placed: dict[str, Placed]) -> bool:
    if name.startswith("thigh_"):
        return True
    return name.startswith("upper_arm_") and not placed[name].parent.startswith("shoulder_")


def parent_tail_gap(name: str, placed: dict[str, Placed]) -> float:
    bone = placed[name]
    return distance(bone.head, placed[bone.parent].tail)


def good_skeleton(**kw):
    """A valid skeleton built from a spec, as a deep copy that tests may break."""
    from rig_agent.builder.skeleton_builder import build_skeleton

    return build_skeleton(make_spec(**kw)).model_copy(deep=True)


def bone(skeleton, name):
    return next(b for b in skeleton.bones if b.name == name)


def validated(mutate=None, **kw):
    """Build a skeleton from a spec, optionally break it, and validate it against the spec."""
    from rig_agent.builder.skeleton_builder import build_skeleton
    from rig_agent.validator.report import validate

    spec = make_spec(**kw)
    skeleton = build_skeleton(spec).model_copy(deep=True)
    if mutate:
        mutate(skeleton)
    return validate(skeleton, spec)
