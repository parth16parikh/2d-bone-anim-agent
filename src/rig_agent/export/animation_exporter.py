"""Writes and reads animation clips: <rig folder>/animations/<name>.json and <name>.report.json,
next to the skeleton.json they were baked for."""

from dataclasses import dataclass
from pathlib import Path

from rig_agent.schemas.animation import AnimationClip
from rig_agent.schemas.validation import ValidationReport

ANIMATIONS_DIR = "animations"
REPORT_SUFFIX = ".report.json"


@dataclass(frozen=True)
class AnimationExport:
    clip_path: Path
    report_path: Path


def animation_paths(rig_folder: str | Path, name: str) -> AnimationExport:
    directory = Path(rig_folder) / ANIMATIONS_DIR
    return AnimationExport(directory / f"{name}.json", directory / f"{name}{REPORT_SUFFIX}")


def export_animation(
    clip: AnimationClip, report: ValidationReport, rig_folder: str | Path
) -> AnimationExport:
    """Write the clip and its report, replacing an earlier clip of the same name."""
    paths = animation_paths(rig_folder, clip.name)
    paths.clip_path.parent.mkdir(parents=True, exist_ok=True)
    paths.clip_path.write_text(clip.model_dump_json(indent=2) + "\n", encoding="utf-8")
    paths.report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return paths


def load_animation(path: str | Path) -> AnimationClip:
    return AnimationClip.model_validate_json(Path(path).read_text(encoding="utf-8"))
