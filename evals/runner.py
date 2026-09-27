"""Runs golden cases and records what happened (Phase H4).

A full run goes through the graph `rig-agent run` uses; only its injectable `plan` dependency is
wrapped, to keep each planner call's schema retries (Q1, Q9b), which the graph state does not
hold. A guard run (--guard-only) calls only the input guard: a cheap way to measure Q9 and to
compare guard models, since the planner is the expensive part of a full run.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evals.golden import GoldenCase
from evals.records import AttemptRec, RunRecord
from rig_agent.agent.planner import PlanResult
from rig_agent.config import Settings
from rig_agent.graph.build_graph import run_rig
from rig_agent.graph.nodes import GraphDeps
from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.state import RigState

DepsFactory = Callable[[], GraphDeps]
GuardCheck = Callable[[str], GuardResult]
RunOne = Callable[[GoldenCase, int], RunRecord]
Clock = Callable[[], float]


def model_label(cfg: Settings, role: str) -> str:
    """provider:model of the primary provider's planner or guard."""
    openai = cfg.primary_provider == "openai"
    if role == "guard":
        model = cfg.guard_model if openai else cfg.anthropic_guard_model
    else:
        model = cfg.planner_model if openai else cfg.anthropic_planner_model
    return f"{cfg.primary_provider}:{model}"


def _attempts(state: RigState, plans: list[PlanResult]) -> list[AttemptRec]:
    records = []
    for index, attempt in enumerate(state.get("attempts") or []):
        report = attempt.report
        retries = plans[index].output_retries if index < len(plans) else ()
        records.append(
            AttemptRec(
                iteration=attempt.iteration,
                spec=attempt.spec,
                passed=report.passed,
                issue_codes=[i.code.value for i in report.issues],
                error_codes=[i.code.value for i in report.errors],
                metrics=dict(report.metrics),
                bone_count=len(attempt.skeleton.bones) if attempt.skeleton else None,
                output_retries=list(retries),
            )
        )
    return records


def _final_iteration(state: RigState) -> int | None:
    spec = state.get("rig_spec")
    for attempt in state.get("attempts") or []:
        if attempt.spec is spec:
            return attempt.iteration
    return None


def run_case(
    case: GoldenCase,
    run: int,
    *,
    deps_factory: DepsFactory,
    out_root: Path,
    unity: bool = False,
    guard_label: str | None = None,
    clock: Clock = time.perf_counter,
) -> RunRecord:
    """One full run of one case. A crash is recorded as an `error` run, not raised: one bad case must
    not end a long, paid-for suite."""
    deps = deps_factory()
    plans: list[PlanResult] = []
    inner = deps.plan

    def recording_plan(*args: Any, **kwargs: Any) -> PlanResult:
        result = inner(*args, **kwargs)
        plans.append(result)
        return result

    deps.plan = recording_plan
    rig_dir = out_root / "rigs" / f"{case.id}__{run}"
    base = {
        "case_id": case.id,
        "category": case.category,
        "run": run,
        "prompt": case.prompt,
        "view_given": case.view,
        "model": model_label(deps.config, "planner"),
        "guard_model": guard_label or model_label(deps.config, "guard"),
    }
    started = clock()
    try:
        state = run_rig(
            case.prompt, view=case.view, unity_mode=unity, out_dir=str(rig_dir), deps=deps
        )
    except Exception as error:  # noqa: BLE001 - recorded, see the docstring
        return RunRecord(
            **base, status="error", error=f"crash: {error!r}", latency_s=clock() - started
        )
    latency = clock() - started

    guard, usage, unity_result = state.get("guard"), state.get("usage"), state.get("unity_result")
    return RunRecord(
        **base,
        status=state.get("status", "error"),
        error=state.get("error"),
        guard_accepted=guard.accepted if guard else None,
        guard_category=guard.category if guard else None,
        attempts=_attempts(state, plans),
        final_iteration=_final_iteration(state),
        requests=usage.requests if usage else 0,
        tool_calls=usage.tool_calls if usage else 0,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        latency_s=latency,
        unity_status=unity_result.status if (unity and unity_result) else None,
        rig_dir=str(rig_dir) if state.get("output_path") else None,
    )


def run_guard_case(
    case: GoldenCase, run: int, *, check: GuardCheck, label: str, clock: Clock = time.perf_counter
) -> RunRecord:
    """One guard-only run: status accepted or rejected, as the input guard decided."""
    base = {
        "mode": "guard",
        "case_id": case.id,
        "category": case.category,
        "run": run,
        "prompt": case.prompt,
        "view_given": case.view,
        "model": label,
        "guard_model": label,
    }
    started = clock()
    try:
        guard = check(case.prompt)
    except Exception as error:  # noqa: BLE001 - recorded, as in run_case
        return RunRecord(
            **base, status="error", error=f"crash: {error!r}", latency_s=clock() - started
        )
    return RunRecord(
        **base,
        status="accepted" if guard.accepted else "rejected",
        guard_accepted=guard.accepted,
        guard_category=guard.category,
        latency_s=clock() - started,
    )


def run_suite(
    cases: list[GoldenCase],
    k: int,
    run_one: RunOne,
    on_record: Callable[[RunRecord], None] | None = None,
) -> list[RunRecord]:
    """Every case k times, case by case. `on_record` sees each record as soon as it exists (the
    CLI uses it to append to records.jsonl, so an interrupted suite keeps what it finished)."""
    records = []
    for case in cases:
        for run in range(1, k + 1):
            record = run_one(case, run)
            records.append(record)
            if on_record:
                on_record(record)
    return records
