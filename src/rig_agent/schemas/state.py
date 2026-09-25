"""RigState, AttemptRecord, UnityResult, UsageTotals: the LangGraph shared state (LLD 3.7)."""

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import IssueCode, ValidationReport
from rig_agent.vocabulary.bones import View

Status = Literal["running", "success", "best_effort", "rejected", "error"]


class UsageTotals(BaseModel):
    """Model usage summed over a whole request, checked against the budgets (LLD 3.7)."""

    model_config = ConfigDict(frozen=True)

    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def plus(
        self, requests: int = 0, tool_calls: int = 0, input_tokens: int = 0, output_tokens: int = 0
    ) -> "UsageTotals":
        return UsageTotals(
            requests=self.requests + requests,
            tool_calls=self.tool_calls + tool_calls,
            input_tokens=self.input_tokens + input_tokens,
            output_tokens=self.output_tokens + output_tokens,
        )


class AttemptRecord(BaseModel):
    """One planning attempt: its spec, the validation report, a score, and the built skeleton."""

    iteration: int = Field(ge=1)
    spec: RigSpec
    report: ValidationReport
    score: float = Field(ge=0.0, le=1.0)
    skeleton: Skeleton | None = None  # None when the spec could not be built


class UnityResult(BaseModel):
    status: Literal["skipped", "unavailable", "applied", "failed"] = "skipped"
    detail: str | None = None


def score_report(report: ValidationReport) -> float:
    """How good an attempt is, from 0 to 1, used to pick the best one when repairs run out.

    An unbuildable spec scores 0. Otherwise each error costs 0.1 and each warning 0.01, so any
    attempt with fewer errors beats one with more, and a passing attempt scores 0.9 or more.
    """
    if report.has(IssueCode.UNBUILDABLE):
        return 0.0
    return max(0.0, 1.0 - 0.1 * len(report.errors) - 0.01 * len(report.warnings))


class RigState(TypedDict, total=False):
    request_id: str
    user_prompt: str
    view: View | None  # the caller's view, if given
    unity_mode: bool
    out_dir: str
    started_at: float
    guard: GuardResult | None
    rig_spec: RigSpec | None
    skeleton: Skeleton | None
    validation: ValidationReport | None
    iteration: int  # planning attempts made so far (the outer repair loop counter)
    attempts: list[AttemptRecord]
    usage: UsageTotals
    output_path: str | None  # the exported skeleton.json
    unity_result: UnityResult | None
    error: str | None
    status: Status
