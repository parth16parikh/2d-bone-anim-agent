"""The Unity side of animation clips (Goal 2, A2): the request Python writes for the importer, and
the check of what Unity reports back.

The request is the clip as flat lists of tracks, because Unity's JsonUtility cannot read the
dictionaries in animation.json. The check compares Unity's samples with our own forward
kinematics twice: the bones as the clip's rotation curves pose them, and the bones after Unity's
IK solvers re-solved from the clip's target curves. The second one is what makes the design safe:
in Play mode the solvers run every frame, so the targets must reproduce the rotation curves.
"""

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rig_agent.animation.pose import forward
from rig_agent.schemas.animation import AnimationClip
from rig_agent.schemas.skeleton import Skeleton

TOLERANCE = 1e-3  # world units, as for the skeleton import
SOLVED_TOLERANCE = 2e-3  # after Unity's solver: its own float maths on top
CHECK_COUNT = 4


def rig_object_names(skeleton: Skeleton, rig_folder: str | Path) -> list[str]:
    """The names a rig can have in the scene: its rig_name (unity-apply, run --unity) or its
    folder name (unity-apply-all names each rig after its folder)."""
    return list(dict.fromkeys([skeleton.rig_name, Path(rig_folder).resolve().name]))


def check_frames(clip: AnimationClip, count: int = CHECK_COUNT) -> list[int]:
    """Frames to sample in Unity: spread evenly over the loop (the closing frame repeats frame 0)."""
    cycle = clip.frame_count - 1 if clip.loop else clip.frame_count
    return sorted({round(i * cycle / count) % max(cycle, 1) for i in range(count)})


def animation_request(
    clip: AnimationClip, rig_names: Sequence[str], asset_folder: str = ""
) -> dict[str, Any]:
    return {
        "rig_names": list(rig_names),
        "name": clip.name,
        "clip": clip.clip,
        "fps": clip.fps,
        "frame_count": clip.frame_count,
        "loop": clip.loop,
        "ground_speed": clip.ground_speed,
        "asset_folder": asset_folder,
        "rotations": [{"bone": b, "values": v} for b, v in clip.rotations.items()],
        "positions": [
            {"bone": b, "x": [p[0] for p in pts], "y": [p[1] for p in pts]}
            for b, pts in clip.positions.items()
        ],
        "targets": [
            {
                "chain": t.chain,
                "target": t.target,
                "x": [p[0] for p in t.positions],
                "y": [p[1] for p in t.positions],
                "rot": t.rotations_deg,
            }
            for t in clip.ik_targets
        ],
        "check_frames": check_frames(clip),
    }


def _expected(
    clip: AnimationClip, skeleton: Skeleton, frame: int
) -> dict[str, tuple[float, float]]:
    """Every bone's head at this frame, by our own forward kinematics."""
    world = forward(
        skeleton,
        {b: v[frame] for b, v in clip.rotations.items()},
        {b: p[frame] for b, p in clip.positions.items()},
    )
    return {name: w.head for name, w in world.items()}


def _worst(
    points: list[dict[str, Any]], expected: dict[str, tuple[float, float]]
) -> tuple[float, str]:
    worst, where = 0.0, ""
    for point in points:
        want = expected.get(point.get("name", ""))
        head = point.get("head")
        if want is None or not head:
            continue
        error = math.dist(head, want)
        if error > worst:
            worst, where = error, point["name"]
    return worst, where


def compare_animation(clip: AnimationClip, skeleton: Skeleton, report: dict[str, Any]) -> list[str]:
    """Problems with the imported clip; an empty list means it matches."""
    problems = [str(e) for e in report.get("errors") or []]
    if problems and not report.get("rig_object"):
        return problems  # the rig was not found: nothing else in the report means anything
    missing = report.get("missing") or []
    if missing:
        problems.append(f"the rig in Unity has no {', '.join(missing)} to animate")
    expected_curves = {
        "rotation_curves": len(clip.rotations),
        "position_curves": len(clip.positions),
        "target_curves": len(clip.ik_targets),
    }
    for key, count in expected_curves.items():
        if report.get(key) != count and not missing:
            problems.append(
                f"Unity made {report.get(key)} {key.replace('_', ' ')}, expected {count}"
            )
    if not report.get("animator"):
        problems.append("the rig has no Animator to play the clip")

    samples = report.get("samples") or []
    if not samples and not problems:
        problems.append("Unity reported no sampled frames")
    for sample in samples:
        frame = sample.get("frame", -1)
        if not 0 <= frame < clip.frame_count:
            problems.append(f"Unity sampled frame {frame}, which the clip does not have")
            continue
        expected = _expected(clip, skeleton, frame)
        error, bone = _worst(sample.get("bones") or [], expected)
        if error > TOLERANCE:
            problems.append(f"frame {frame}: {bone} is {error:.4f} from the clip's pose")
        if sample.get("solved"):
            error, bone = _worst(sample["solved"], expected)
            if error > SOLVED_TOLERANCE:
                problems.append(
                    f"frame {frame}: after Unity's IK re-solved from the targets, {bone} is "
                    f"{error:.4f} from the clip's pose (the targets and the rotations disagree)"
                )
    return problems


def max_errors(
    clip: AnimationClip, skeleton: Skeleton, report: dict[str, Any]
) -> tuple[float, float]:
    """The largest bone error by the curves, and after Unity's IK, over all samples (for display)."""
    by_curves = by_solver = 0.0
    for sample in report.get("samples") or []:
        frame = sample.get("frame", 0)
        if not 0 <= frame < clip.frame_count:
            continue
        expected = _expected(clip, skeleton, frame)
        by_curves = max(by_curves, _worst(sample.get("bones") or [], expected)[0])
        by_solver = max(by_solver, _worst(sample.get("solved") or [], expected)[0])
    return by_curves, by_solver
