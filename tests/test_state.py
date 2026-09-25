import pytest
from pydantic import ValidationError

from layout_helpers import good_skeleton, make_spec
from rig_agent.schemas.state import (
    AttemptRecord,
    RigState,
    UnityResult,
    UsageTotals,
    score_report,
)
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport


def report(errors=0, warnings=0, unbuildable=False):
    issues = [ValidationIssue(code=IssueCode.OUT_OF_BOUNDS, message="e")] * errors
    issues += [
        ValidationIssue(code=IssueCode.OUT_OF_BOUNDS, message="w", severity="warning")
    ] * warnings
    if unbuildable:
        issues.append(ValidationIssue(code=IssueCode.UNBUILDABLE, message="no"))
    return ValidationReport(issues=issues)


def test_a_clean_report_scores_one():
    assert score_report(report()) == 1.0


def test_each_error_costs_more_than_any_number_of_realistic_warnings():
    assert score_report(report(errors=1)) == pytest.approx(0.9)
    assert score_report(report(errors=3)) == pytest.approx(0.7)
    assert score_report(report(warnings=5)) == pytest.approx(0.95)
    assert score_report(report(errors=1)) < score_report(report(warnings=9))


def test_fewer_errors_always_score_higher():
    scores = [score_report(report(errors=n)) for n in range(6)]
    assert scores == sorted(scores, reverse=True)


def test_a_passing_attempt_scores_at_least_point_nine():
    assert score_report(report(warnings=9)) >= 0.9 and report(warnings=9).passed


def test_an_unbuildable_spec_scores_zero():
    assert score_report(report(unbuildable=True)) == 0.0


def test_the_score_never_goes_below_zero():
    assert score_report(report(errors=40)) == 0.0


def test_usage_totals_add_up_without_mutating():
    base = UsageTotals()
    total = base.plus(requests=2, tool_calls=1, input_tokens=100, output_tokens=20).plus(
        requests=1, input_tokens=50
    )
    assert (total.requests, total.tool_calls, total.input_tokens, total.output_tokens) == (
        3,
        1,
        150,
        20,
    )
    assert total.total_tokens == 170 and base.requests == 0


def test_usage_totals_are_frozen():
    with pytest.raises(ValidationError):
        UsageTotals().requests = 5


def test_attempt_record_holds_the_spec_report_score_and_skeleton():
    spec = make_spec()
    attempt = AttemptRecord(
        iteration=1, spec=spec, report=report(), score=1.0, skeleton=good_skeleton()
    )
    assert attempt.spec == spec and attempt.skeleton is not None
    assert (
        AttemptRecord(iteration=2, spec=spec, report=report(unbuildable=True), score=0.0).skeleton
        is None
    )


def test_attempt_record_validates_its_fields():
    with pytest.raises(ValidationError):
        AttemptRecord(iteration=0, spec=make_spec(), report=report(), score=1.0)
    with pytest.raises(ValidationError):
        AttemptRecord(iteration=1, spec=make_spec(), report=report(), score=1.5)


def test_unity_result_defaults_to_skipped():
    assert UnityResult().status == "skipped"
    assert UnityResult(status="unavailable", detail="not built").detail == "not built"
    with pytest.raises(ValidationError):
        UnityResult(status="maybe")


def test_rig_state_is_a_partial_typed_dict():
    state: RigState = {"user_prompt": "a knight", "iteration": 0}
    assert set(RigState.__annotations__) >= {
        "request_id", "user_prompt", "unity_mode", "guard", "rig_spec", "skeleton", "validation",
        "iteration", "attempts", "output_path", "unity_result", "status",
    }  # fmt: skip
    assert state["user_prompt"] == "a knight"
