"""The animation golden set (Goal 2, M4): loads and validates evals/anim/golden.yaml, and builds its
fixed test rigs from example specs (no model involved)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.schemas.animation import AnimationSpec, ClipType
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.vocabulary.presets import Preset

ANIM_GOLDEN_PATH = Path(__file__).with_name("golden.yaml")
REPO_ROOT = Path(__file__).resolve().parents[2]

AnimCategory = Literal[
    "neutral", "mood", "modifier", "backflip", "view_rule", "unsupported", "adversarial"
]
ANIM_CATEGORIES: tuple[AnimCategory, ...] = (
    "neutral", "mood", "modifier", "backflip", "view_rule", "unsupported", "adversarial"
)  # fmt: skip
Outcome = Literal["accept", "reject", "wrong_view"]
Direction = Literal["up", "down", "same"]
SETTINGS = ("speed", "stride", "bounce", "arm_swing", "knee_lift", "lean_deg")
NEUTRAL = {name: float(AnimationSpec.model_fields[name].default) for name in SETTINGS}
MOVED = 0.05  # how far from neutral counts as up or down (lean_deg: LEAN_MOVED degrees)
LEAN_MOVED = 2.0
SAME = 0.15  # how close to neutral counts as the same (lean_deg: LEAN_SAME degrees)
LEAN_SAME = 3.0


def direction_ok(setting: str, value: float, wanted: Direction) -> bool:
    """Whether a planned setting moved the way the case expects, relative to neutral."""
    delta = value - NEUTRAL[setting]
    moved, same = (LEAN_MOVED, LEAN_SAME) if setting == "lean_deg" else (MOVED, SAME)
    if wanted == "up":
        return delta > moved
    if wanted == "down":
        return delta < -moved
    return abs(delta) <= same


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnimExpected(_Strict):
    outcome: Outcome = "accept"
    categories: tuple[str, ...] = ()
    clip: ClipType | None = None
    directions: dict[str, Direction] = Field(default_factory=dict)

    @field_validator("directions")
    @classmethod
    def known_settings(cls, value: dict[str, Direction]) -> dict[str, Direction]:
        unknown = set(value) - set(SETTINGS)
        if unknown:
            raise ValueError(f"unknown setting(s) {sorted(unknown)}; use {SETTINGS}")
        return value

    @model_validator(mode="after")
    def consistent(self) -> AnimExpected:
        if self.outcome == "reject" and (self.clip or self.directions):
            raise ValueError("a rejected case has no clip or settings to check")
        if self.categories and self.outcome != "reject":
            raise ValueError("categories only apply to outcome: reject")
        if self.outcome == "wrong_view" and not self.clip:
            raise ValueError("a wrong_view case names the clip that needs the side view")
        if self.outcome != "reject" and self.clip is None:
            raise ValueError("every accepted case names the clip it expects")
        return self


class RigRef(_Strict):
    spec: str  # path to a RigSpec, relative to the repository root
    preset: Preset | None = None  # replace the spec's preset (e.g. a chibi version of the knight)


class AnimCase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    category: AnimCategory
    rig: str
    prompt: str = Field(min_length=1)
    expect: AnimExpected


class AnimGoldenSet(_Strict):
    version: int
    rigs: dict[str, RigRef]
    cases: tuple[AnimCase, ...]

    @model_validator(mode="after")
    def references_hold(self) -> AnimGoldenSet:
        dupes = sorted(i for i, n in Counter(c.id for c in self.cases).items() if n > 1)
        if dupes:
            raise ValueError(f"duplicate case ids: {dupes}")
        unknown = sorted({c.rig for c in self.cases} - set(self.rigs))
        if unknown:
            raise ValueError(f"cases use unknown rigs: {unknown}")
        return self

    def by_id(self) -> dict[str, AnimCase]:
        return {c.id: c for c in self.cases}

    def build_rigs(self) -> dict[str, Skeleton]:
        """Every test rig, built with no model (deterministic: the same rig every run)."""
        built = {}
        for name, ref in self.rigs.items():
            spec = RigSpec.model_validate_json((REPO_ROOT / ref.spec).read_text(encoding="utf-8"))
            if ref.preset:
                spec = spec.model_copy(update={"preset": ref.preset})
            built[name] = build_skeleton(spec, rig_name=name)
        return built


def load_anim_golden(path: str | Path = ANIM_GOLDEN_PATH) -> AnimGoldenSet:
    return AnimGoldenSet.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def select_cases(
    cases: tuple[AnimCase, ...],
    *,
    ids: list[str] | None = None,
    categories: list[str] | None = None,
    limit: int | None = None,
) -> list[AnimCase]:
    if ids:
        missing = sorted(set(ids) - {c.id for c in cases})
        if missing:
            raise ValueError(f"no such case id(s): {missing}")
    chosen = [
        c
        for c in cases
        if (not ids or c.id in ids) and (not categories or c.category in categories)
    ]
    return chosen[:limit] if limit else chosen
