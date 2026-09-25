"""Tests that call the real OpenAI API. They cost a few cents and are opt-in:

    uv run pytest -m live

They need OPENAI_API_KEY in .env (or the environment) and are skipped without it.
"""

import pytest

from rig_agent.agent.planner import plan
from rig_agent.agent.tools import dry_run_validate
from rig_agent.config import settings
from rig_agent.guardrails.input_guard import build_guard_agent, check_input

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not settings.openai_api_key, reason="OPENAI_API_KEY is not set"),
]


def test_the_classifier_accepts_a_humanoid_and_rejects_a_horse():
    guard = build_guard_agent()
    assert check_input("chibi knight with a big sword", guard).accepted
    horse = check_input("rig a horse", guard)
    assert not horse.accepted and horse.category == "non_humanoid"


def test_the_planner_returns_a_buildable_rigspec():
    result = plan("chibi knight with a big sword")
    assert result.spec.character_summary
    assert result.requests >= 1
    report = dry_run_validate(result.spec)
    print(f"\nspec: {result.spec.model_dump_json(exclude_defaults=True)}")
    print(f"requests={result.requests} tools={result.tool_calls} report={report.model_dump_json()}")


def test_an_explicit_view_is_respected():
    assert plan("a ninja", "side").spec.view == "side"
    assert plan("a ninja", "front").spec.view == "front"
