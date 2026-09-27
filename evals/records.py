"""What one eval run leaves behind (Phase H4): everything the metrics need, saved as one JSON line
per run in records.jsonl, so a finished (and paid-for) run can be re-scored without calling any
model again (`python -m evals.run --rescore DIR`)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rig_agent.builder.errors import BuildError
from rig_agent.builder.proportions import resolve_proportions
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.vocabulary.bones import View

RECORDS_FILE = "records.jsonl"


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttemptRec(_Record):
    """One planning attempt of a run, as the validator saw it."""

    iteration: int
    spec: RigSpec
    passed: bool
    issue_codes: list[str]  # error and warning codes, in report order
    error_codes: list[str]
    metrics: dict[str, float]  # the validator's measured values (coverage, symmetry, ...)
    bone_count: int | None  # None when the spec could not be built
    # why each RigSpec the model produced was rejected by the schema before this one was accepted
    output_retries: list[str] = Field(default_factory=list)

    def derived(self) -> dict[str, float] | None:
        """The spec's derived proportions (heads_tall, leg_ratio, ...), None if unbuildable."""
        try:
            return resolve_proportions(self.spec).derived_values(self.spec.view)
        except BuildError:
            return None


class RunRecord(_Record):
    # full: the whole pipeline, like `rig-agent run`. guard: only the input guard (--guard-only),
    # so status is accepted | rejected | error and there are no attempts.
    mode: Literal["full", "guard"] = "full"
    case_id: str
    category: str
    run: int  # 1..k
    prompt: str
    view_given: View | None
    model: str  # provider:model of the planner (of the guard, in guard mode)
    guard_model: str | None = None  # provider:model of the input guard
    status: str  # success | best_effort | rejected | error; guard mode: accepted | rejected | error
    error: str | None = None
    guard_accepted: bool | None = None
    guard_category: str | None = None
    attempts: list[AttemptRec] = Field(default_factory=list)
    final_iteration: int | None = None  # which attempt is the delivered rig
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    unity_status: str | None = None  # applied | failed | skipped | unavailable, None if not asked
    rig_dir: str | None = None

    @property
    def first(self) -> AttemptRec | None:
        return self.attempts[0] if self.attempts else None

    @property
    def final(self) -> AttemptRec | None:
        return next((a for a in self.attempts if a.iteration == self.final_iteration), None)

    @property
    def view(self) -> View | None:
        """The view of the delivered rig (or of the first attempt), None if nothing was planned."""
        attempt = self.final or self.first
        return attempt.spec.view if attempt else None


def load_records(folder: str | Path) -> list[RunRecord]:
    path = Path(folder) / RECORDS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    return [RunRecord.model_validate_json(line) for line in lines if line.strip()]


def append_record(folder: str | Path, record: RunRecord) -> None:
    with (Path(folder) / RECORDS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")
