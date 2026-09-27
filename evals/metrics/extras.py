"""Extra-bone F1 by semantic group (LLD 4.2, Q8): which accessories a rig has, compared by kind
(hair, cape, weapon, ...) rather than by exact name, since `extra_braid` and `extra_ponytail` are
both a correct answer to "a samurai with a long braid"."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

from rig_agent.schemas.rig_spec import ExtraBoneSpec

# Matched per word of the name (split on "_" and digits): a word matches a keyword when it is the
# keyword, its plural, or ends with it (greatsword, longbow). Groups are tried in this order, so
# "ponytail" is hair, not tail, and whole-word matching keeps "cape" out of headwear's "cap".
GROUPS: dict[str, tuple[str, ...]] = {
    "hair": ("hair", "ponytail", "pigtail", "braid", "bang", "fringe", "mane", "bun"),
    "headwear": ("hat", "helmet", "helm", "crown", "hood", "halo", "cap", "tiara", "plume"),
    "shield": ("shield", "buckler"),
    "held": (
        "sword", "blade", "katana", "cutlass", "saber", "sabre", "dagger", "knife", "axe",
        "hammer", "mace", "spear", "lance", "staff", "wand", "bow", "club", "scythe", "whip",
        "weapon", "gun", "rifle", "pistol", "torch", "lantern", "hook", "scepter", "sceptre",
        "trident", "halberd", "pike", "rod", "flail", "sickle",
    ),
    "gear": ("quiver", "backpack", "bag", "pack", "satchel", "scabbard", "sheath", "pouch"),
    "cloth": ("cape", "cloak", "scarf", "mantle", "coat", "robe", "skirt", "sash", "tabard"),
    "wings": ("wing",),
    "horns": ("horn", "antler"),
    "ears": ("ear",),
    "tail": ("tail",),
}  # fmt: skip
OTHER = "other"


def _matches(word: str, keyword: str) -> bool:
    return word in (keyword, keyword + "s", keyword + "es") or word.endswith(keyword)


def group_of(name: str) -> str:
    """The semantic group of an extra bone name (with or without `extra_` and side suffixes)."""
    words = [w for w in re.split(r"[_\d]+", name.removeprefix("extra_").lower()) if w]
    for group, keywords in GROUPS.items():
        if any(_matches(word, kw) for word in words for kw in keywords):
            return group
    return OTHER


def chains_by_group(extras: Iterable[ExtraBoneSpec]) -> Counter[str]:
    """Accessory chains per group. A mirrored chain is two chains (a left and a right one)."""
    counts: Counter[str] = Counter()
    for extra in extras:
        counts[group_of(extra.name)] += 2 if extra.mirror else 1
    return counts


def extras_f1(expected: Mapping[str, int], actual: Mapping[str, int]) -> float:
    """F1 over group multisets: 2 hair chains expected and 1 made scores partial credit.

    Nothing expected and nothing made is a perfect 1.0.
    """
    want, got = sum(expected.values()), sum(actual.values())
    if want == 0 and got == 0:
        return 1.0
    hits = sum(min(n, actual.get(group, 0)) for group, n in expected.items())
    if hits == 0:
        return 0.0
    precision, recall = hits / got, hits / want
    return 2 * precision * recall / (precision + recall)
