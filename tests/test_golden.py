"""evals/golden.yaml and its loader (Phase H3): the set matches LLD 4.1 and every case is usable."""

from collections import Counter

import pytest
from pydantic import ValidationError

from evals.golden import CATEGORIES, Expected, GoldenCase, in_range, load_golden, select
from rig_agent.guardrails.input_guard import check_prompt_text
from rig_agent.schemas.guardrail import GuardCategory

LLD_COUNTS = {
    "standard": 10,
    "view_selection": 8,
    "stylized": 10,
    "modifier": 8,
    "accessory": 10,
    "ambiguous": 5,
    "adversarial": 7,
}
GOLDEN = load_golden()


def test_the_category_counts_match_the_lld_table():
    assert Counter(c.category for c in GOLDEN.cases) == LLD_COUNTS
    assert len(GOLDEN.cases) == 58


def test_each_category_with_a_fixed_view_is_split_evenly_between_front_and_side():
    """LLD 4.1: apart from view selection and adversarial (and the view-free vague prompts)."""
    for category in ("standard", "stylized", "modifier", "accessory"):
        views = Counter(c.view for c in GOLDEN.cases if c.category == category)
        assert views["front"] == views["side"], (category, views)


def test_a_given_view_is_also_the_expected_one():
    for case in GOLDEN.cases:
        if case.view is not None:
            assert case.expect.view == case.view, case.id


def test_view_selection_mostly_leaves_the_choice_to_the_agent():
    chosen_by_agent = [c for c in GOLDEN.cases if c.category == "view_selection" and c.view is None]
    assert len(chosen_by_agent) >= 6
    assert all(c.expect.view for c in GOLDEN.cases if c.category == "view_selection")


def test_only_adversarial_cases_expect_a_rejection():
    for case in GOLDEN.cases:
        assert (case.expect.outcome != "accept") == (case.category == "adversarial"), case.id


def test_rejection_categories_are_real_guard_categories():
    allowed = set(GuardCategory.__args__)
    for case in GOLDEN.cases:
        assert set(case.expect.categories) <= allowed, case.id


def test_shoulder_expectations_are_only_on_front_view_cases():
    for case in GOLDEN.cases:
        if "shoulder_width_hu" in case.expect.proportions:
            assert case.expect.view == "front", case.id


def test_every_accessory_case_names_the_groups_it_expects():
    for case in GOLDEN.cases:
        if case.category == "accessory":
            assert case.expect.extras, case.id


def test_vague_prompts_expect_an_assumption_and_pass_the_deterministic_guard():
    for case in GOLDEN.cases:
        if case.category == "ambiguous":
            assert case.expect.assumption
            assert check_prompt_text(case.prompt) is None  # left to the classifier, not blocked


def test_ids_are_unique_and_stable_looking():
    ids = [c.id for c in GOLDEN.cases]
    assert len(ids) == len(set(ids))


# ---- the loader rejects mistakes ----------------------------------------------------------------


def test_an_unknown_proportion_name_is_refused():
    with pytest.raises(ValidationError, match="unknown proportion"):
        Expected(proportions={"head_ratio": (None, 1.0)})


def test_an_unknown_extra_group_is_refused():
    with pytest.raises(ValidationError, match="unknown extra group"):
        Expected(extras={"hats": 1})


def test_a_rejected_case_cannot_also_expect_a_rig():
    with pytest.raises(ValidationError, match="no rig"):
        Expected(outcome="reject", view="side")


def test_categories_only_go_with_a_rejection():
    with pytest.raises(ValidationError, match="categories"):
        Expected(categories=("non_humanoid",))


def test_duplicate_ids_are_refused(tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text(
        "version: 1\ncases:\n"
        "  - {id: a, category: standard, prompt: x}\n"
        "  - {id: a, category: standard, prompt: y}\n"
    )
    with pytest.raises(ValidationError, match="duplicate"):
        load_golden(path)


def test_in_range_with_open_ends():
    assert in_range(5, (None, 5)) and in_range(5, (5, None)) and in_range(5, (None, None))
    assert not in_range(5.1, (None, 5)) and not in_range(4.9, (5, None))


# ---- select() ----------------------------------------------------------------------------------


def test_select_by_category_and_limit():
    chosen = select(GOLDEN.cases, categories=["accessory"], limit=3)
    assert len(chosen) == 3 and {c.category for c in chosen} == {"accessory"}


def test_select_by_id_keeps_the_golden_order():
    chosen = select(GOLDEN.cases, ids=["adv_horse", "std_villager"])
    assert [c.id for c in chosen] == ["std_villager", "adv_horse"]


def test_select_an_unknown_id_is_an_error():
    with pytest.raises(ValueError, match="no such case"):
        select(GOLDEN.cases, ids=["nope"])


def test_categories_constant_matches_the_schema():
    assert set(CATEGORIES) == set(LLD_COUNTS)
    assert GoldenCase(id="x", category="standard", prompt="p").expect.outcome == "accept"
