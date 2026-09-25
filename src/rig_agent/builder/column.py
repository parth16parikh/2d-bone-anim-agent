"""Layout pieces shared by both views: the torso column and limb chains (LLD 2.3, 2.7, 2.8)."""

from collections.abc import Collection

from rig_agent.builder.geometry import Placed, Point, advance
from rig_agent.builder.proportions import ResolvedProportions
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.vocabulary.bones import resolve_parent, torso_top
from rig_agent.vocabulary.poses import JAW_ATTACH_FRACTION, RestPose, rest_angle


def place_column(
    spec: RigSpec, props: ResolvedProportions, present: Collection[str]
) -> dict[str, Placed]:
    """Root, torso bones, neck, head and jaw, all on the center line at depth 0."""
    pose = spec.rest_pose
    placed: dict[str, Placed] = {}

    def add(name: str, head: Point, length: float) -> Placed:
        bone = Placed(name, resolve_parent(name, present), head, rest_angle(name, pose), length)
        placed[name] = bone
        return bone

    add("root", (0.0, 0.0), props.root)
    cursor: Point = (0.0, props.leg_length)  # the hip joint, not the root marker's tail
    for name, length in (
        ("hip", props.hip),
        ("spine", props.spine),
        ("spine_2", props.spine_2),
        ("chest", props.chest),
        ("neck", props.neck),
    ):
        if name in present:
            cursor = add(name, cursor, length).tail
    head = add("head", cursor, props.head)
    if "jaw" in present:
        pivot = advance(head.head, head.angle, JAW_ATTACH_FRACTION * head.length)
        add("jaw", pivot, props.jaw)
    return placed


def torso_top_point(placed: dict[str, Placed], present: Collection[str]) -> Point:
    """The tail of the topmost torso bone, which is the neck base on the center line."""
    return placed[torso_top(present)].tail


def place_chain(
    placed: dict[str, Placed],
    present: Collection[str],
    pose: RestPose,
    links: list[tuple[str, float]],
    start: Point,
    depth: int,
) -> None:
    """A straight chain of limb bones, each starting where the previous one ends."""
    cursor = start
    for name, length in links:
        if name not in present:
            continue
        bone = Placed(
            name, resolve_parent(name, present), cursor, rest_angle(name, pose), length, depth
        )
        placed[name] = bone
        cursor = bone.tail


def arm_links(props: ResolvedProportions, side: str) -> list[tuple[str, float]]:
    return [
        (f"upper_arm_{side}", props.upper_arm),
        (f"forearm_{side}", props.forearm),
        (f"hand_{side}", props.hand),
    ]


def leg_links(props: ResolvedProportions, side: str) -> list[tuple[str, float]]:
    return [
        (f"thigh_{side}", props.thigh),
        (f"shin_{side}", props.shin),
        (f"foot_{side}", props.foot),
        (f"toe_{side}", props.toe),
    ]
