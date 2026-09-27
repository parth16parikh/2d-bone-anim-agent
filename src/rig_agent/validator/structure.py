"""Structural checks: single root, acyclic, no orphans, unique names, required bones, caps (LLD 3.8.2)."""

import re
from collections import Counter
from itertools import pairwise

from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import IssueCode, ValidationIssue
from rig_agent.vocabulary.bones import BONES, REQUIRED_BONES, resolve_parent
from rig_agent.vocabulary.poses import ik_chain_defs, ik_tags

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
        issues += _check_ik_chains(skeleton)
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


def _check_ik_chains(skeleton: Skeleton) -> list[ValidationIssue]:
    """ik_chains (schema 1.1) must list exactly the chains this rig has, with the vocabulary's
    roles and bend sides, and the bone tags must agree with them (LLD 2.9)."""
    if skeleton.schema_version == "1.0":
        return []  # 1.0 files have no ik_chains
    names = {b.name for b in skeleton.bones}
    by_id = {b.id: b for b in skeleton.bones}
    by_name = {b.name: b for b in skeleton.bones}
    expected = {c.name: c for c in ik_chain_defs(names, skeleton.view)}
    actual = {c.name: c for c in skeleton.ik_chains}
    issues = []

    if len(actual) != len(skeleton.ik_chains):
        issues.append(_issue(IssueCode.INVALID_IK_CHAIN, "an IK chain is listed twice"))
    for name in sorted(set(expected) - set(actual)):
        issues.append(_issue(IssueCode.INVALID_IK_CHAIN, f"IK chain '{name}' is missing"))
    for name in sorted(set(actual) - set(expected)):
        issues.append(
            _issue(IssueCode.INVALID_IK_CHAIN, f"'{name}' is not an IK chain of this rig")
        )

    for name in sorted(set(actual) & set(expected)):
        chain, want = actual[name], expected[name]
        roles = (chain.root, chain.joint, chain.effector)
        if roles != (want.root, want.joint, want.effector):
            issues.append(
                _issue(
                    IssueCode.INVALID_IK_CHAIN,
                    f"IK chain '{name}' has bones {roles}, expected "
                    f"{(want.root, want.joint, want.effector)}",
                )
            )
            continue
        bones = [b for b in roles if b is not None]
        for parent, child in pairwise(bones):
            if by_id.get(by_name[child].parent_id) is not by_name[parent]:
                issues.append(
                    _issue(
                        IssueCode.INVALID_IK_CHAIN,
                        f"IK chain '{name}': '{child}' does not hang from '{parent}'",
                        [parent, child],
                    )
                )
        if chain.bend_side != want.bend_side:
            issues.append(
                _issue(
                    IssueCode.INVALID_IK_CHAIN,
                    f"IK chain '{name}': bend_side '{chain.bend_side}' should be "
                    f"'{want.bend_side}' in the {skeleton.view} view",
                )
            )

    tags = ik_tags(names)
    for b in skeleton.bones:
        if b.ik_chain != tags.get(b.name):
            issues.append(
                _issue(
                    IssueCode.INVALID_IK_CHAIN,
                    f"'{b.name}' is tagged '{b.ik_chain}' but belongs to '{tags.get(b.name)}'",
                    [b.name],
                )
            )
    return issues
