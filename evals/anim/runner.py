"""Runs animation golden cases through the real `rig-agent animate` pipeline (Goal 2, M4).

Only the injectable `plan` dependency is wrapped, to keep what the planner chose first and its
schema retries, which the pipeline state does not hold. A crash is recorded, not raised."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evals.anim.golden import AnimCase
from evals.anim.records import AnimAttemptRec, AnimRunRecord
from evals.runner import model_label
from rig_agent.agent.anim_planner import AnimPlanResult
from rig_agent.export.json_exporter import export
from rig_agent.graph.anim_graph import AnimDeps, AnimState, run_animation
from rig_agent.schemas.animation import CLIP_VIEWS
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import ValidationReport

AnimDepsFactory = Callable[[], AnimDeps]
Clock = Callable[[], float]


def _attempts(state: AnimState) -> list[AnimAttemptRec]:
    return [
        AnimAttemptRec(
            iteration=a.iteration,
            spec=a.spec,
            passed=a.report.passed,
            error_codes=[i.code.value for i in a.report.errors],
            metrics=dict(a.report.metrics),
        )
        for a in state.get("attempts") or []
    ]


def _final_iteration(state: AnimState) -> int | None:
    spec = state.get("spec")
    for attempt in state.get("attempts") or []:
        if attempt.spec is spec:
            return attempt.iteration
    return None


def run_anim_case(
    case: AnimCase,
    run: int,
    *,
    rigs: dict[str, Skeleton],
    deps_factory: AnimDepsFactory,
    out_root: Path,
    clock: Clock = time.perf_counter,
) -> AnimRunRecord:
    skeleton = rigs[case.rig]
    deps = deps_factory()
    plans: list[AnimPlanResult] = []
    inner = deps.plan

    def recording_plan(*args: Any, **kwargs: Any) -> AnimPlanResult:
        result = inner(*args, **kwargs)
        plans.append(result)
        return result

    deps.plan = recording_plan
    folder = out_root / "rigs" / f"{case.id}__{run}"
    export(skeleton, ValidationReport(), folder)  # the rig beside its clip, for the viewer
    base = {
        "case_id": case.id,
        "category": case.category,
        "run": run,
        "prompt": case.prompt,
        "rig": case.rig,
        "rig_view": skeleton.view,
        "model": model_label(deps.config, "planner"),
        "guard_model": model_label(deps.config, "guard"),
    }
    started = clock()
    try:
        state = run_animation(case.prompt, skeleton, folder, deps=deps)
    except Exception as error:  # noqa: BLE001 - one bad case must not end a paid-for suite
        return AnimRunRecord(
            **base, status="error", error=f"crash: {error!r}", latency_s=clock() - started
        )
    latency = clock() - started

    guard, usage, spec = state.get("guard"), state.get("usage"), state.get("spec")
    status = state.get("status", "error")
    return AnimRunRecord(
        **base,
        status=status,
        error=state.get("error"),
        guard_accepted=guard.accepted if guard else None,
        guard_category=guard.category if guard else None,
        planned=plans[0].spec if plans else None,
        first_plan_retries=list(plans[0].output_retries) if plans else [],
        plan_calls=len(plans),
        final_spec=spec,
        attempts=_attempts(state),
        final_iteration=_final_iteration(state),
        stopped_for_view=bool(
            status == "error" and spec is not None and skeleton.view not in CLIP_VIEWS[spec.clip]
        ),
        clip_written=bool(state.get("output_path")),
        requests=usage.requests if usage else 0,
        tool_calls=usage.tool_calls if usage else 0,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        latency_s=latency,
    )


def run_anim_suite(
    cases: list[AnimCase],
    k: int,
    *,
    rigs: dict[str, Skeleton],
    deps_factory: AnimDepsFactory,
    out_root: Path,
    on_record: Callable[[AnimRunRecord], None] | None = None,
) -> list[AnimRunRecord]:
    records = []
    for case in cases:
        for run in range(1, k + 1):
            record = run_anim_case(
                case, run, rigs=rigs, deps_factory=deps_factory, out_root=out_root
            )
            records.append(record)
            if on_record:
                on_record(record)
    return records
