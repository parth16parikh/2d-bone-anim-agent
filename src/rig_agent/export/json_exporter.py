"""Writes the versioned skeleton.json and validation_report.json (LLD 3.4 #6, 3.5b)."""

from dataclasses import dataclass
from pathlib import Path

from rig_agent.export.animation_exporter import ANIMATIONS_DIR
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import ValidationReport

SKELETON_FILE = "skeleton.json"
REPORT_FILE = "validation_report.json"
RENDER_FILE = "skeleton.png"  # written by evals/render_skeleton.py; deleted with the rig


@dataclass(frozen=True)
class ExportResult:
    skeleton_path: Path
    report_path: Path


@dataclass(frozen=True)
class DeleteResult:
    folder: Path
    removed_files: list[str]  # the rig files that existed, animations/ clips as animations/<file>
    folder_removed: bool  # true if the folder was empty afterwards and was removed too


class NotARigFolderError(ValueError):
    """The folder has neither skeleton.json nor validation_report.json."""


def export(skeleton: Skeleton, report: ValidationReport, out_dir: str | Path) -> ExportResult:
    """Write both files into out_dir, creating it if needed and replacing earlier files."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    skeleton_path = directory / SKELETON_FILE
    report_path = directory / REPORT_FILE
    skeleton_path.write_text(skeleton.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return ExportResult(skeleton_path, report_path)


def delete_rig(folder: str | Path) -> DeleteResult:
    """Remove a rig's skeleton.json and validation_report.json from folder, its skeleton.png
    render, and the clips baked for it in animations/ (*.json: each clip and its report). The
    render and the clips are made from skeleton.json, so they would be stale on their own.

    Only those files are ever removed (and animations/ itself, if that leaves it empty). The
    folder itself is removed too, but only if that leaves it empty; anything else you put there
    (notes, a spec.json copy) is left untouched and so is the folder. Raises NotARigFolderError if the folder has neither file, so a typo or an
    unrelated folder is never silently a no-op.
    """
    directory = Path(folder)
    present = [name for name in (SKELETON_FILE, REPORT_FILE) if (directory / name).is_file()]
    if not present:
        raise NotARigFolderError(
            f"'{directory}' has neither {SKELETON_FILE} nor {REPORT_FILE}; nothing to delete"
        )
    if (directory / RENDER_FILE).is_file():
        present.append(RENDER_FILE)
    clips = directory / ANIMATIONS_DIR
    if clips.is_dir():
        present += [f"{ANIMATIONS_DIR}/{f.name}" for f in sorted(clips.glob("*.json"))]
    for name in present:
        (directory / name).unlink()
    if clips.is_dir() and not any(clips.iterdir()):
        clips.rmdir()
    removed = directory.is_dir() and not any(directory.iterdir())
    if removed:
        directory.rmdir()
    return DeleteResult(directory, present, removed)


def load_skeleton(path: str | Path) -> Skeleton:
    return Skeleton.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_report(path: str | Path) -> ValidationReport:
    return ValidationReport.model_validate_json(Path(path).read_text(encoding="utf-8"))
