"""validate(): runs every check and assembles the ValidationReport (LLD 3.4 #5)."""

from rig_agent.builder.errors import BuildError
from rig_agent.builder.proportions import resolve_proportions
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport
from rig_agent.validator.geometry_checks import (
    check_bands,
    check_geometry,
    check_mirror_coincident,
)
from rig_agent.validator.structure import FATAL, check_structure
from rig_agent.vocabulary.bones import REQUIRED_BONES


def validate(skeleton: Skeleton, spec: RigSpec) -> ValidationReport:
    """Check a skeleton against the spec it was built from."""
    issues = check_structure(skeleton)
    present = {b.name for b in skeleton.bones}
    metrics = {"required_bone_coverage": len(REQUIRED_BONES & present) / len(REQUIRED_BONES)}

    issues += check_mirror_coincident(spec)
    try:
        props = resolve_proportions(spec)
    except BuildError as error:
        issues.append(ValidationIssue(code=IssueCode.UNBUILDABLE, message=str(error)))
        return ValidationReport(issues=issues, metrics=metrics)

    issues += check_bands(props, spec.view)
    codes = {i.code for i in issues}
    if not codes & (FATAL | {IssueCode.MISSING_REQUIRED_BONE}):
        geometry = check_geometry(skeleton, spec, props)
        issues += geometry.issues
        metrics.update(geometry.metrics)
    return ValidationReport(issues=issues, metrics=metrics)
