"""Structural checks: single root, acyclic, no orphans, unique names, required bones, caps (LLD 3.8.2)."""

import re
from collections import Counter

from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import IssueCode, ValidationIssue
from rig_agent.vocabulary.bones import BONES, REQUIRED_BONES, resolve_parent

MAX_BONES = 40
MAX_EXTRA_BONES = 16
_EXTRA_NAME = re.compile(r"extra_[a-z0-9_]+(_[LR])?")

# Codes after which the geometry checks cannot run safely.
FATAL = {
    IssueCode.NO_ROOT,
    IssueCode.MULTIPLE_ROOTS,
    IssueCode.CYCLE,
    IssueCode.ORPHAN_BONE,
    IssueCode.DUPLICATE_NAME,
}


def _issue(code: IssueCode, message: str, bones: list[str] | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, message=message, bones=bones or [])


def is_extra(name: str) -> bool:
    return name.startswith("extra_")


def check_structure(skeleton: Skeleton) -> list[ValidationIssue]:
    bones = skeleton.bones
    issues: list[ValidationIssue] = []

    for bone_id, count in Counter(b.id for b in bones).items():
        if count > 1:
            owners = [b.name for b in bones if b.id == bone_id]
            issues.append(
                _issue(IssueCode.DUPLICATE_NAME, f"bone id {bone_id} is used {count} times", owners)
            )
    for name, count in Counter(b.name for b in bones).items():
        if count > 1:
            issues.append(
                _issue(
                    IssueCode.DUPLICATE_NAME, f"bone name '{name}' is used {count} times", [name]
                )
            )

    ids = {b.id for b in bones}
    roots = [b.name for b in bones if b.parent_id == -1]
    if not roots:
        issues.append(_issue(IssueCode.NO_ROOT, "the skeleton has no root bone"))
    elif len(roots) > 1:
        issues.append(
            _issue(IssueCode.MULTIPLE_ROOTS, "the skeleton has more than one root", roots)
        )

    for b in bones:
        if b.parent_id != -1 and b.parent_id not in ids:
            issues.append(
                _issue(
                    IssueCode.ORPHAN_BONE,
                    f"'{b.name}' has unknown parent id {b.parent_id}",
                    [b.name],
                )
            )

    parent_of = {b.id: b.parent_id for b in bones}
    in_cycle = []
    for b in bones:
        seen, cursor = set(), b.id
        while cursor != -1 and cursor in parent_of:
            if cursor in seen:
                in_cycle.append(b.name)
                break
            seen.add(cursor)
            cursor = parent_of[cursor]
    if in_cycle:
        issues.append(_issue(IssueCode.CYCLE, "the hierarchy contains a cycle", in_cycle))

    names = {b.name for b in bones}
    for missing in sorted(REQUIRED_BONES - names):
        issues.append(
            _issue(
                IssueCode.MISSING_REQUIRED_BONE, f"required bone '{missing}' is missing", [missing]
            )
        )

    for b in bones:
        if b.name not in BONES and not _EXTRA_NAME.fullmatch(b.name):
            issues.append(
                _issue(
                    IssueCode.UNKNOWN_BONE,
                    f"'{b.name}' is neither a canonical bone nor an extra_ bone",
                    [b.name],
                )
            )

    if len(bones) > MAX_BONES:
        issues.append(
            _issue(IssueCode.TOO_MANY_BONES, f"{len(bones)} bones; the limit is {MAX_BONES}")
        )
    extras = [b.name for b in bones if is_extra(b.name)]
    if len(extras) > MAX_EXTRA_BONES:
        issues.append(
            _issue(
                IssueCode.TOO_MANY_EXTRA_BONES,
                f"{len(extras)} extra bones; the limit is {MAX_EXTRA_BONES}",
                extras,
            )
        )

    if not {i.code for i in issues} & (FATAL | {IssueCode.MISSING_REQUIRED_BONE}):
        issues += _check_parents(skeleton)
    return issues


def _check_parents(skeleton: Skeleton) -> list[ValidationIssue]:
    """Each canonical bone must hang from the parent the vocabulary resolves for this rig."""
    by_id = {b.id: b for b in skeleton.bones}
    canonical = {b.name for b in skeleton.bones if b.name in BONES}
    issues = []
    for b in skeleton.bones:
        if b.name not in BONES:
            continue
        expected = resolve_parent(b.name, canonical)
        actual = None if b.parent_id == -1 else by_id[b.parent_id].name
        if actual != expected:
            issues.append(
                _issue(
                    IssueCode.WRONG_PARENT,
                    f"'{b.name}' hangs from '{actual}' but should hang from '{expected}'",
                    [b.name],
                )
            )
    return issues
