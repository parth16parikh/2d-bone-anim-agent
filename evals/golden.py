"""The golden eval set (LLD 4.1, Phase H3): loads and validates evals/golden.yaml."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evals.metrics.extras import GROUPS
from rig_agent.vocabulary.bones import View

GOLDEN_PATH = Path(__file__).with_name("golden.yaml")

Category = Literal[
    "standard", "view_selection", "stylized", "modifier", "accessory", "ambiguous", "adversarial"
]
CATEGORIES: tuple[Category, ...] = (
    "standard",
    "view_selection",
    "stylized",
    "modifier",
    "accessory",
    "ambiguous",
    "adversarial",
)
Outcome = Literal["accept", "reject", "reject_or_clamp"]
PROPORTION_NAMES = ("heads_tall", "leg_ratio", "arm_ratio", "shoulder_width_hu")

Range = tuple[float | None, float | None]


def in_range(value: float, bounds: Range) -> bool:
    low, high = bounds
    return (low is None or value >= low) and (high is None or value <= high)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expected(_Strict):
    outcome: Outcome = "accept"
    categories: tuple[str, ...] = ()  # guard categories that count as a correct rejection
    view: View | None = None
    proportions: dict[str, Range] = Field(default_factory=dict)
    bones: Range | None = None
    extras: dict[str, int] | None = None  # None: not checked; {}: expect no accessories
    assumption: bool = False

    @field_validator("proportions")
    @classmethod
    def known_proportions(cls, value: dict[str, Range]) -> dict[str, Range]:
        unknown = set(value) - set(PROPORTION_NAMES)
        if unknown:
            raise ValueError(f"unknown proportion(s) {sorted(unknown)}; use {PROPORTION_NAMES}")
        return value

    @field_validator("extras")
    @classmethod
    def known_groups(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        unknown = set(value or {}) - set(GROUPS)
        if unknown:
            raise ValueError(f"unknown extra group(s) {sorted(unknown)}; use {sorted(GROUPS)}")
        return value

    @model_validator(mode="after")
    def categories_only_for_rejections(self) -> Expected:
        if self.categories and self.outcome != "reject":
            raise ValueError("categories only apply to outcome: reject")
        if self.outcome != "accept" and (self.view or self.proportions or self.extras):
            raise ValueError("a rejected case has no rig to check views, proportions or extras on")
        return self


class GoldenCase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    category: Category
    prompt: str = Field(min_length=1)
    view: View | None = None  # passed to the agent, like `run --view`
    expect: Expected = Expected()


class GoldenSet(_Strict):
    version: int
    cases: tuple[GoldenCase, ...]

    @model_validator(mode="after")
    def unique_ids(self) -> GoldenSet:
        counts = Counter(c.id for c in self.cases)
        dupes = sorted(i for i, n in counts.items() if n > 1)
        if dupes:
            raise ValueError(f"duplicate case ids: {dupes}")
        return self

    def by_id(self) -> dict[str, GoldenCase]:
        return {c.id: c for c in self.cases}


def load_golden(path: str | Path = GOLDEN_PATH) -> GoldenSet:
    return GoldenSet.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def select(
    cases: tuple[GoldenCase, ...],
    *,
    ids: list[str] | None = None,
    categories: list[str] | None = None,
    limit: int | None = None,
) -> list[GoldenCase]:
    """A subset: by id and/or category (both filters apply), then the first `limit`."""
    chosen = [
        c
        for c in cases
        if (not ids or c.id in ids) and (not categories or c.category in categories)
    ]
    if ids:
        missing = sorted(set(ids) - {c.id for c in cases})
        if missing:
            raise ValueError(f"no such case id(s): {missing}")
    return chosen[:limit] if limit else chosen
