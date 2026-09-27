"""Compares what Unity created with the skeleton.json it was given (LLD 3.11b step 3, Q13)."""

import math
from typing import Any

from rig_agent.schemas.skeleton import Skeleton
from rig_agent.unity.contract import OUTPUT_ROOT

POSITION_TOLERANCE = 1e-3  # world units, as in the LLD (Q13)


def _distance(a: list[float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def compare_import(
    skeleton: Skeleton,
    report: dict[str, Any],
    tolerance: float = POSITION_TOLERANCE,
    *,
    expect_ik: bool = True,
) -> list[str]:
    """Problems found, or an empty list when Unity's hierarchy matches the JSON.

    Checks the importer's own verdict, the bone count, every bone's name, parent, depth and
    layer, the world position of every head and tail, and that every object was created under
    the RigAgent_Output root (nothing outside it). It also checks the placeholder sprite and
    SpriteSkin, and (unless expect_ik is False) one Limb solver per IK chain that has an effector.
    """
    problems: list[str] = []
    if not report.get("ok"):
        problems.append("Unity's importer reported failure")
    problems += [f"importer: {message}" for message in report.get("errors") or []]

    if report.get("rig_name") != skeleton.rig_name:
        problems.append(f"rig name is '{report.get('rig_name')}', expected '{skeleton.rig_name}'")
    if report.get("bone_count") != len(skeleton.bones):
        problems.append(
            f"Unity created {report.get('bone_count')} bones, expected {len(skeleton.bones)}"
        )

    created = {b["name"]: b for b in report.get("bones") or []}
    by_id = {b.id: b for b in skeleton.bones}
    for bone in skeleton.bones:
        actual = created.get(bone.name)
        if actual is None:
            problems.append(f"bone '{bone.name}' is missing in Unity")
            continue
        expected_parent = by_id[bone.parent_id].name if bone.parent_id >= 0 else ""
        if actual.get("parent") != expected_parent:
            problems.append(
                f"'{bone.name}' hangs from '{actual.get('parent')}', expected '{expected_parent}'"
            )
        if actual.get("depth") != bone.depth:
            problems.append(f"'{bone.name}' has depth {actual.get('depth')}, expected {bone.depth}")
        if (actual.get("layer") or "") != (bone.layer or ""):
            problems.append(
                f"'{bone.name}' has layer '{actual.get('layer')}', expected '{bone.layer or ''}'"
            )
        for label, got, want in (
            ("head", actual.get("world_head"), bone.world_head),
            ("tail", actual.get("world_tail"), bone.world_tail),
        ):
            if not got or len(got) != 2:
                problems.append(f"'{bone.name}' has no {label} position in the report")
            elif (error := _distance(got, want)) > tolerance:
                problems.append(
                    f"'{bone.name}' {label} is {error:.4f} units off (limit {tolerance})"
                )
        if not str(actual.get("path", "")).startswith(OUTPUT_ROOT + "/"):
            problems.append(
                f"'{bone.name}' was created outside {OUTPUT_ROOT}: '{actual.get('path')}'"
            )

    extra = sorted(set(created) - {b.name for b in skeleton.bones})
    if extra:
        problems.append(f"Unity has bones that are not in the JSON: {extra}")
    problems += _check_skin(skeleton, report.get("skin"))
    if expect_ik:
        problems += _check_ik(skeleton, report.get("ik"))
    return problems


def _check_skin(skeleton: Skeleton, skin: dict[str, Any] | None) -> list[str]:
    """The placeholder sprite and SpriteSkin: what lets Unity's own bone display draw the rig."""
    if not skin or not skin.get("sprite_path"):
        return ["the importer report has no sprite data (is the installed importer outdated?)"]
    problems = []
    count = len(skeleton.bones)
    if skin.get("state") != "Ready":
        problems.append(f"Unity's SpriteSkin is not ready (state '{skin.get('state')}')")
    if skin.get("sprite_bones") != count:
        problems.append(f"the sprite holds {skin.get('sprite_bones')} bones, expected {count}")
    if skin.get("bind_poses") != count:
        problems.append(f"the sprite has {skin.get('bind_poses')} bind poses, expected {count}")
    if not skin.get("has_weights"):
        problems.append("the sprite has no bone weights")
    if not skin.get("skeleton_path"):
        problems.append("no skeleton asset was written")
    return problems


def _check_ik(skeleton: Skeleton, ik: dict[str, Any] | None) -> list[str]:
    """One valid Limb solver per chain that has an effector, bending to the side the JSON says."""
    wanted = {c.name: c for c in skeleton.ik_chains if c.effector}
    if not wanted:
        return []
    if not ik or not ik.get("enabled"):
        return [
            "IK was expected but the importer reports it off (is the installed importer outdated?)"
        ]
    problems = []
    solvers = {s.get("chain"): s for s in ik.get("solvers") or []}
    for name, chain in wanted.items():
        solver = solvers.get(name)
        if solver is None:
            problems.append(f"IK chain '{name}' has no solver in Unity")
            continue
        if solver.get("effector") != chain.effector:
            problems.append(
                f"IK chain '{name}' reaches with '{solver.get('effector')}', expected '{chain.effector}'"
            )
        if not solver.get("valid"):
            problems.append(f"the IK chain '{name}' is not valid in Unity")
        if solver.get("flip") != (chain.bend_side == "right"):
            problems.append(
                f"IK chain '{name}' bends to the wrong side (bend_side '{chain.bend_side}', "
                f"flip {solver.get('flip')})"
            )
    for name in sorted(set(solvers) - set(wanted)):
        problems.append(f"Unity has an IK solver '{name}' that is not in the JSON")
    return problems
