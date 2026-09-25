import json

import pytest

from layout_helpers import bone, good_skeleton
from rig_agent.export.json_exporter import (
    REPORT_FILE,
    SKELETON_FILE,
    export,
    load_report,
    load_skeleton,
)
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport


def a_report():
    return ValidationReport(
        issues=[ValidationIssue(code=IssueCode.MIRROR_COINCIDENT, message="m", bones=["extra_a"])],
        metrics={"joint_connectivity": 1.0},
    )


def test_writes_both_files_and_they_reload_equal(tmp_path):
    skeleton, report = good_skeleton(optional_bones=["hands"]), a_report()
    result = export(skeleton, report, tmp_path)
    assert result.skeleton_path == tmp_path / "skeleton.json"
    assert result.report_path == tmp_path / "validation_report.json"
    assert (SKELETON_FILE, REPORT_FILE) == ("skeleton.json", "validation_report.json")
    assert load_skeleton(result.skeleton_path) == skeleton
    assert load_report(result.report_path) == report


def test_creates_missing_directories(tmp_path):
    result = export(good_skeleton(), ValidationReport(), tmp_path / "a" / "b")
    assert result.skeleton_path.exists() and result.report_path.exists()


def test_files_are_indented_json_with_a_trailing_newline(tmp_path):
    result = export(good_skeleton(), ValidationReport(), tmp_path)
    text = result.skeleton_path.read_text(encoding="utf-8")
    assert text.endswith("}\n") and "\n  " in text
    data = json.loads(text)
    assert data["schema_version"] == "1.0"
    assert data["bones"][0]["name"] == "root"


def test_the_report_file_includes_the_passed_flag(tmp_path):
    result = export(good_skeleton(), a_report(), tmp_path)
    data = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert data["passed"] is False and data["issues"][0]["code"] == "mirror_coincident"


def test_non_ascii_text_is_kept_readable(tmp_path):
    skeleton = good_skeleton(assumptions=["'lanky' → arm scale 1.15"])
    result = export(skeleton, ValidationReport(), tmp_path)
    assert "→" in result.skeleton_path.read_text(encoding="utf-8")


def test_an_existing_export_is_replaced(tmp_path):
    export(good_skeleton(), ValidationReport(), tmp_path)
    changed = good_skeleton()
    bone(changed, "head").depth = 5
    export(changed, ValidationReport(), tmp_path)
    assert bone(load_skeleton(tmp_path / "skeleton.json"), "head").depth == 5


def test_a_string_path_works(tmp_path):
    assert export(good_skeleton(), ValidationReport(), str(tmp_path)).skeleton_path.exists()


def test_loading_a_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_skeleton(tmp_path / "nope.json")
