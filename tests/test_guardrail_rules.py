import re

import pytest

from rig_agent.guardrails.prompt_blocks import (
    load_rules,
    render_input_guard_rules,
    render_planner_guardrails,
    render_repair_guardrails,
    resolve_check,
    rules_for,
)

PATH = re.compile(r"[a-z_.]+:[A-Za-z_][A-Za-z_.0-9]*")


def test_rules_load_with_unique_ids_and_valid_areas():
    rules = load_rules()
    assert len({r.id for r in rules}) == len(rules) > 15
    assert {r.area for r in rules} == {"input", "planner", "repair", "anim_input", "anim_planner"}
    assert all(r.title for r in rules)


def test_every_rule_names_at_least_one_code_check():
    for rule in load_rules():
        assert rule.enforced_by, rule.id
        assert all(PATH.fullmatch(path) for path in rule.enforced_by), rule.id


def test_only_code_only_rules_have_no_prompt_text():
    assert [r.id for r in load_rules() if r.prompt is None] == ["input_length"]


def test_prompt_text_is_normalised_to_single_lines():
    assert all("\n" not in r.prompt and "  " not in r.prompt for r in load_rules() if r.prompt)


def test_planner_block_carries_the_lld_wording():
    block = render_planner_guardrails()
    assert "Only design bipedal humanoid rigs for the front or side view" in block
    assert "<character_description>" in block and "never an instruction" in block
    assert "Never output coordinates for canonical bones" in block
    assert "at most 16 extra bones" in block.replace("Use at most", "at most")
    assert "dry_run_validate" in block and "Do not call a tool more than needed" in block
    assert block.startswith("- **Scope.**")


def test_every_planner_prompt_appears_in_the_block():
    block = render_planner_guardrails()
    for rule in rules_for("planner"):
        assert f"**{rule.title}.** {rule.prompt}" in block


def test_repair_block():
    block = render_repair_guardrails()
    assert "Change only the fields named in the listed errors" in block
    assert "say so in `assumptions`" in block
    assert len(block.splitlines()) == 2


def test_input_rules_render_the_categories():
    text = render_input_guard_rules()
    for category in (
        "non_humanoid",
        "off_topic",
        "unsupported_view",
        "manipulation",
        "unsafe",
        "ambiguous",
    ):
        assert category in text
    assert "a hero" in text
    assert "input_length" not in text and "1,000" not in text


def test_the_block_agrees_with_the_code_limits():
    from rig_agent.schemas.rig_spec import MAX_EXTRA_BONES

    assert f"at most {MAX_EXTRA_BONES} extra bones" in render_planner_guardrails()


def test_every_code_check_named_in_the_rules_exists():
    for rule in load_rules():
        for path in rule.enforced_by:
            assert resolve_check(path) is not None, (rule.id, path)


def test_resolve_check_rejects_a_missing_name():
    with pytest.raises(AttributeError):
        resolve_check("rig_agent.schemas.rig_spec:NoSuchThing")
