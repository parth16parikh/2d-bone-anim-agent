"""ValidationReport: machine-readable structure/geometry errors from the Validator (LLD 3.4 #5)."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class IssueCode(StrEnum):
    # the spec could not be built into a skeleton at all
    UNBUILDABLE = "unbuildable"
    # structure (LLD 3.8.2)
    NO_ROOT = "no_root"
    MULTIPLE_ROOTS = "multiple_roots"
    CYCLE = "cycle"
    ORPHAN_BONE = "orphan_bone"
    DUPLICATE_NAME = "duplicate_name"
    MISSING_REQUIRED_BONE = "missing_required_bone"
    UNKNOWN_BONE = "unknown_bone"
    WRONG_PARENT = "wrong_parent"
    TOO_MANY_BONES = "too_many_bones"
    TOO_MANY_EXTRA_BONES = "too_many_extra_bones"
    # geometry (LLD 3.8.2, 2.4.4, 2.6, 2.7)
    NON_POSITIVE_LENGTH = "non_positive_length"
    DISCONNECTED_JOINT = "disconnected_joint"
    HIP_MISPLACED = "hip_misplaced"
    LIMB_ROOT_MISPLACED = "limb_root_misplaced"
    JAW_MISPLACED = "jaw_misplaced"
    ASYMMETRIC_PAIR = "asymmetric_pair"
    DEPTH_ORDER = "depth_order"
    OUT_OF_BOUNDS = "out_of_bounds"
    SEGMENT_TOO_SHORT = "segment_too_short"
    PROPORTION_OUT_OF_BAND = "proportion_out_of_band"
    MIRROR_COINCIDENT = "mirror_coincident"


class ValidationIssue(BaseModel):
    code: IssueCode
    severity: Literal["error", "warning"] = "error"
    message: str
    bones: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    issues: list[ValidationIssue] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)  # measured values for the evals

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return not self.errors

    def has(self, code: IssueCode) -> bool:
        return any(i.code == code for i in self.issues)
