"""Writes the versioned skeleton.json and validation_report.json (LLD 3.4 #6, 3.5b)."""

from dataclasses import dataclass
from pathlib import Path

from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import ValidationReport

SKELETON_FILE = "skeleton.json"
REPORT_FILE = "validation_report.json"


@dataclass(frozen=True)
class ExportResult:
    skeleton_path: Path
    report_path: Path


def export(skeleton: Skeleton, report: ValidationReport, out_dir: str | Path) -> ExportResult:
    """Write both files into out_dir, creating it if needed and replacing earlier files."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    skeleton_path = directory / SKELETON_FILE
    report_path = directory / REPORT_FILE
    skeleton_path.write_text(skeleton.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return ExportResult(skeleton_path, report_path)


def load_skeleton(path: str | Path) -> Skeleton:
    return Skeleton.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_report(path: str | Path) -> ValidationReport:
    return ValidationReport.model_validate_json(Path(path).read_text(encoding="utf-8"))
