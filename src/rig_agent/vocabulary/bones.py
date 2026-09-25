"""Canonical bone table: names, required flags, optional tokens, view limits (LLD 2.3)."""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Literal

View = Literal["front", "side"]
ALL_VIEWS: frozenset[View] = frozenset({"front", "side"})


@dataclass(frozen=True)
class BoneDef:
    name: str
    required: bool
    token: str | None = None
    views: frozenset[View] = ALL_VIEWS


def _pair(base: str, required: bool, token: str | None = None, views: frozenset[View] = ALL_VIEWS):
    return [BoneDef(f"{base}_{side}", required, token, views) for side in ("L", "R")]


_TABLE: list[BoneDef] = [
    BoneDef("root", True),
    BoneDef("hip", True),
    BoneDef("spine", True),
    BoneDef("spine_2", False, "spine_2"),
    BoneDef("chest", False, "chest"),
    BoneDef("neck", False, "neck"),
    BoneDef("head", True),
    *_pair("shoulder", False, "shoulders", frozenset({"front"})),
    *_pair("upper_arm", True),
    *_pair("forearm", True),
    *_pair("hand", False, "hands"),
    *_pair("thigh", True),
    *_pair("shin", True),
    *_pair("foot", True),
    *_pair("toe", False, "toes", frozenset({"side"})),
    BoneDef("jaw", False, "jaw"),
]

BONES: dict[str, BoneDef] = {b.name: b for b in _TABLE}
REQUIRED_BONES: frozenset[str] = frozenset(b.name for b in _TABLE if b.required)
OPTIONAL_TOKENS: tuple[str, ...] = tuple(dict.fromkeys(b.token for b in _TABLE if b.token))
MAX_CANONICAL_BONES = len(BONES)


def expand_optional(tokens: Iterable[str]) -> list[str]:
    """Bone names added by the given optional tokens, in table order and without duplicates."""
    wanted = set(tokens)
    unknown = wanted - set(OPTIONAL_TOKENS)
    if unknown:
        raise ValueError(f"unknown optional bone token(s): {sorted(unknown)}")
    return [b.name for b in _TABLE if b.token in wanted]


def token_views(token: str) -> frozenset[View]:
    """The views in which an optional token may be used."""
    for b in _TABLE:
        if b.token == token:
            return b.views
    raise ValueError(f"unknown optional bone token: {token}")


def present_bones(optional_tokens: Iterable[str] = ()) -> frozenset[str]:
    """The canonical bones in a rig: every required bone plus those the tokens add."""
    return REQUIRED_BONES | frozenset(expand_optional(optional_tokens))


_TORSO_COLUMN = ("hip", "spine", "spine_2", "chest", "neck", "head")
_TORSO_TOP_CANDIDATES = ("chest", "spine_2", "spine")
_LIMB_PARENT = {
    "forearm": "upper_arm",
    "hand": "forearm",
    "shin": "thigh",
    "foot": "shin",
    "toe": "foot",
}


def torso_top(present: Collection[str]) -> str:
    """The topmost present torso bone among spine, spine_2 and chest (LLD 2.3)."""
    for name in _TORSO_TOP_CANDIDATES:
        if name in present:
            return name
    raise ValueError("the rig has no torso bone")


def resolve_parent(bone: str, present: Collection[str]) -> str | None:
    """The nearest present parent of a canonical bone, or None for the root (LLD 2.3)."""
    if bone not in BONES:
        raise ValueError(f"not a canonical bone: {bone}")
    if bone not in present:
        raise ValueError(f"bone is not present in the rig: {bone}")
    if bone == "root":
        return None
    if bone == "hip":
        return "root"
    if bone == "jaw":
        return "head"
    if bone in _TORSO_COLUMN:
        below = _TORSO_COLUMN[: _TORSO_COLUMN.index(bone)]
        for name in reversed(below):
            if name in present:
                return name
        raise ValueError(f"no parent for {bone}: the rig has no lower torso bone")

    base, side = bone[:-2], bone[-1]
    if base == "shoulder":
        return torso_top(present)
    if base == "upper_arm":
        shoulder = f"shoulder_{side}"
        return shoulder if shoulder in present else torso_top(present)
    if base == "thigh":
        return "hip"
    return f"{_LIMB_PARENT[base]}_{side}"
