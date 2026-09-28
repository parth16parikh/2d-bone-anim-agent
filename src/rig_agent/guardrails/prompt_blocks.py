"""Loads rules.yaml and renders it into prompt guardrail blocks (LLD 3.8.1)."""

import importlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml

Area = Literal["input", "planner", "repair", "anim_input", "anim_planner"]
RULES_FILE = Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True)
class Rule:
    id: str
    area: Area
    title: str
    prompt: str | None
    enforced_by: tuple[str, ...]


@cache
def load_rules() -> tuple[Rule, ...]:
    data = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    return tuple(
        Rule(
            id=r["id"],
            area=r["area"],
            title=r["title"],
            prompt=" ".join(r["prompt"].split()) if r.get("prompt") else None,
            enforced_by=tuple(r.get("enforced_by") or ()),
        )
        for r in data["rules"]
    )


def rules_for(area: Area) -> list[Rule]:
    return [r for r in load_rules() if r.area == area]


def _render(area: Area) -> str:
    return "\n".join(f"- **{r.title}.** {r.prompt}" for r in rules_for(area) if r.prompt)


def render_planner_guardrails() -> str:
    """The guardrail block of the planner system prompt (LLD 3.8.1b)."""
    return _render("planner")


def render_repair_guardrails() -> str:
    """The guardrail block added to the prompt on outer-loop retries (LLD 3.8.1c)."""
    return _render("repair")


def render_input_guard_rules() -> str:
    """The rule list of the input classifier prompt (LLD 3.8.1a)."""
    return _render("input")


def render_anim_input_rules() -> str:
    """The rule list of the animation request classifier (Goal 2, A3)."""
    return _render("anim_input")


def render_anim_planner_guardrails() -> str:
    """The guardrail block of the animation planner's system prompt (Goal 2, A3)."""
    return _render("anim_planner")


def resolve_check(path: str) -> Any:
    """Import the code check named as `module:qualified.name`."""
    module_name, _, qualname = path.partition(":")
    target: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    return target
