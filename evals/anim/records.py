"""What one animation eval run leaves behind: everything the metrics need, one JSON line per run in
records.jsonl, so a finished (paid-for) run can be re-scored without any model call."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rig_agent.schemas.animation import AnimationSpec
from rig_agent.vocabulary.bones import View

RECORDS_FILE = "records.jsonl"


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnimAttemptRec(_Record):
    iteration: int
    spec: AnimationSpec
    passed: bool
    error_codes: list[str]
    metrics: dict[str, float]  # the clip validator's measured values


class AnimRunRecord(_Record):
    case_id: str
    category: str
    run: int
    prompt: str
    rig: str
    rig_view: View
    model: str
    guard_model: str
    status: str  # success | best_effort | rejected | error
    error: str | None = None
    guard_accepted: bool | None = None
    guard_category: str | None = None
    planned: AnimationSpec | None = None  # what the planner chose first
    first_plan_retries: list[str] = Field(default_factory=list)  # schema rejections before it
    plan_calls: int = 0
    final_spec: AnimationSpec | None = None  # what was delivered (or planned last)
    attempts: list[AnimAttemptRec] = Field(default_factory=list)
    final_iteration: int | None = None
    stopped_for_view: bool = False  # stopped because the clip needs a side-view rig
    clip_written: bool = False
    requests: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0

    @property
    def first(self) -> AnimAttemptRec | None:
        return self.attempts[0] if self.attempts else None


def load_anim_records(folder: str | Path) -> list[AnimRunRecord]:
    lines = (Path(folder) / RECORDS_FILE).read_text(encoding="utf-8").splitlines()
    return [AnimRunRecord.model_validate_json(line) for line in lines if line.strip()]


def append_anim_record(folder: str | Path, record: AnimRunRecord) -> None:
    with (Path(folder) / RECORDS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json() + "\n")
