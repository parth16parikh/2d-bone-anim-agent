"""Finds every rig in the out/ folder so all of them can be built in Unity at once (LLD 3.11a).

Each rig is named after its folder (out/knight2/ becomes the object 'knight2'), because several
runs of the same prompt produce the same rig_name and would replace each other in the scene.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from rig_agent.export.json_exporter import REPORT_FILE, SKELETON_FILE, load_report, load_skeleton
from rig_agent.schemas.skeleton import Skeleton

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class BatchRig:
    name: str  # the object and prefab name, also the file name inside Assets/Rigs/Batch
    skeleton: Skeleton  # with rig_name set to name
    source: Path  # the skeleton.json it came from
    passed: bool | None  # what validation_report.json says; None when there is no report


@dataclass(frozen=True)
class SkippedRig:
    source: Path
    reason: str


def safe_name(text: str) -> str:
    """A name that is safe as a file name and an object name."""
    return _UNSAFE.sub("_", text).strip("._") or "rig"


def collect_rigs(out_dir: str | Path) -> tuple[list[BatchRig], list[SkippedRig]]:
    """Every rig under out_dir (one folder each, or a skeleton.json directly in it), by name.

    Folders that hold no skeleton.json are ignored. A skeleton.json that cannot be read is
    reported as skipped rather than stopping the others.
    """
    root = Path(out_dir)
    if not root.is_dir():
        return [], []
    sources = [root / SKELETON_FILE] + [p / SKELETON_FILE for p in sorted(root.iterdir())]
    rigs: list[BatchRig] = []
    skipped: list[SkippedRig] = []
    taken: set[str] = set()
    for source in sources:
        if not source.is_file():
            continue
        try:
            skeleton = load_skeleton(source)
        except (OSError, ValidationError, ValueError) as error:
            skipped.append(SkippedRig(source, f"not a valid skeleton.json ({_first_line(error)})"))
            continue
        name = safe_name(skeleton.rig_name if source.parent == root else source.parent.name)
        unique, n = name, 2
        while unique in taken:
            unique, n = f"{name}_{n}", n + 1
        taken.add(unique)
        rigs.append(
            BatchRig(
                unique,
                skeleton.model_copy(update={"rig_name": unique}),
                source,
                _passed(source.with_name(REPORT_FILE)),
            )
        )
    return sorted(rigs, key=lambda r: r.name), skipped


def _passed(report_path: Path) -> bool | None:
    if not report_path.is_file():
        return None
    try:
        return load_report(report_path).passed
    except (OSError, ValidationError, ValueError):
        return None


def _first_line(error: Exception) -> str:
    return (str(error).strip().splitlines() or ["unreadable"])[0][:120]
