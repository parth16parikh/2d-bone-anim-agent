import json

import pytest
from pydantic import ValidationError

from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport


def issue(code=IssueCode.DISCONNECTED_JOINT, severity="error", bones=None):
    return ValidationIssue(code=code, severity=severity, message="m", bones=bones or [])


def test_empty_report_passes():
    report = ValidationReport()
    assert report.passed
    assert report.errors == [] and report.warnings == []


def test_an_error_fails_the_report():
    report = ValidationReport(issues=[issue()])
    assert not report.passed
    assert len(report.errors) == 1


def test_warnings_do_not_fail_the_report():
    report = ValidationReport(issues=[issue(severity="warning")])
    assert report.passed
    assert len(report.warnings) == 1 and report.errors == []


def test_has_checks_codes():
    report = ValidationReport(issues=[issue(IssueCode.MIRROR_COINCIDENT)])
    assert report.has(IssueCode.MIRROR_COINCIDENT)
    assert not report.has(IssueCode.CYCLE)


def test_report_serialises_with_passed_and_codes_as_text():
    report = ValidationReport(
        issues=[issue(IssueCode.ORPHAN_BONE, bones=["extra_cape_1"])],
        metrics={"joint_connectivity": 0.97},
    )
    data = json.loads(report.model_dump_json())
    assert data["passed"] is False
    assert data["issues"][0]["code"] == "orphan_bone"
    assert data["issues"][0]["bones"] == ["extra_cape_1"]
    assert data["metrics"] == {"joint_connectivity": 0.97}


def test_report_round_trips_through_json():
    report = ValidationReport(issues=[issue(), issue(severity="warning")], metrics={"a": 1.0})
    assert ValidationReport.model_validate_json(report.model_dump_json()) == report


def test_issue_codes_are_unique_snake_case_strings():
    values = [c.value for c in IssueCode]
    assert len(values) == len(set(values))
    assert all(v == v.lower() and " " not in v for v in values)
    assert IssueCode("mirror_coincident") is IssueCode.MIRROR_COINCIDENT


def test_unknown_issue_code_is_rejected():
    with pytest.raises(ValidationError):
        ValidationIssue(code="whatever", message="m")


def test_accepted_guard_result():
    result = GuardResult(accepted=True, category="ok", reason="A humanoid rig request.")
    assert result.suggestion is None


def test_rejected_guard_result_with_a_suggestion():
    result = GuardResult(
        accepted=False,
        category="non_humanoid",
        reason="A horse is not a bipedal humanoid.",
        suggestion="Describe a humanoid character, for example a centaur-like warrior on two legs.",
    )
    assert not result.accepted


@pytest.mark.parametrize(
    "category",
    [
        "non_humanoid",
        "off_topic",
        "unsupported_view",
        "manipulation",
        "unsafe",
        "too_long",
        "ambiguous",
    ],
)
def test_every_rejection_category_is_not_accepted(category):
    assert not GuardResult(accepted=False, category=category, reason="r").accepted
    with pytest.raises(ValidationError, match="accepted must be true"):
        GuardResult(accepted=True, category=category, reason="r")


def test_ok_category_cannot_be_rejected():
    with pytest.raises(ValidationError, match="accepted must be true"):
        GuardResult(accepted=False, category="ok", reason="r")


def test_guard_result_needs_a_reason_and_no_extra_fields():
    with pytest.raises(ValidationError):
        GuardResult(accepted=True, category="ok", reason="")
    with pytest.raises(ValidationError):
        GuardResult(accepted=True, category="ok", reason="r", extra=1)
    with pytest.raises(ValidationError):
        GuardResult(accepted=True, category="maybe", reason="r")
