import json

import pytest

from layout_helpers import bone, good_skeleton
from rig_agent.export.json_exporter import (
    RENDER_FILE,
    REPORT_FILE,
    SKELETON_FILE,
    NotARigFolderError,
    delete_rig,
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
    assert data["schema_version"] == "1.1"
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


# ---- delete_rig -----------------------------------------------------------------------------------


def test_deleting_a_rig_removes_both_files_and_the_now_empty_folder(tmp_path):
    folder = tmp_path / "knight"
    export(good_skeleton(), a_report(), folder)
    result = delete_rig(folder)
    assert sorted(result.removed_files) == [SKELETON_FILE, REPORT_FILE]
    assert result.folder_removed and not folder.exists()


def test_a_folder_the_agent_never_wrote_to_is_refused(tmp_path):
    folder = tmp_path / "not_a_rig"
    folder.mkdir()
    (folder / "notes.txt").write_text("hello")
    with pytest.raises(NotARigFolderError, match="neither"):
        delete_rig(folder)
    assert (folder / "notes.txt").is_file()  # nothing was touched


def test_a_missing_folder_is_refused_the_same_way(tmp_path):
    with pytest.raises(NotARigFolderError):
        delete_rig(tmp_path / "nope")


def test_extra_files_in_the_folder_are_left_alone_and_so_is_the_folder(tmp_path):
    folder = tmp_path / "knight"
    export(good_skeleton(), a_report(), folder)
    (folder / "spec.json").write_text("{}")
    result = delete_rig(folder)
    assert sorted(result.removed_files) == [SKELETON_FILE, REPORT_FILE]
    assert not result.folder_removed
    assert folder.is_dir() and (folder / "spec.json").is_file()
    assert not (folder / SKELETON_FILE).exists() and not (folder / REPORT_FILE).exists()


def test_a_rig_missing_its_report_can_still_be_deleted(tmp_path):
    folder = tmp_path / "knight"
    export(good_skeleton(), a_report(), folder)
    (folder / REPORT_FILE).unlink()
    result = delete_rig(folder)
    assert result.removed_files == [SKELETON_FILE]
    assert result.folder_removed and not folder.exists()


def test_a_render_is_deleted_with_its_rig(tmp_path):
    folder = tmp_path / "knight"
    export(good_skeleton(), a_report(), folder)
    (folder / RENDER_FILE).write_bytes(b"png")
    result = delete_rig(folder)
    assert sorted(result.removed_files) == sorted([SKELETON_FILE, REPORT_FILE, RENDER_FILE])
    assert result.folder_removed and not folder.exists()


def test_a_render_alone_is_not_a_rig_folder(tmp_path):
    folder = tmp_path / "knight"
    folder.mkdir()
    (folder / RENDER_FILE).write_bytes(b"png")
    with pytest.raises(NotARigFolderError):
        delete_rig(folder)
    assert (folder / RENDER_FILE).is_file()
