"""Graph nodes and routers: input_guard, plan, build, validate, export, best_effort, reject, fail (LLD 3.7)."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup
from pydantic_ai.usage import UsageLimits

from rig_agent.agent.planner import PlanResult, plan
from rig_agent.builder.errors import BuildError
from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.config import Settings, settings
from rig_agent.export.json_exporter import export
from rig_agent.guardrails.input_guard import check_input
from rig_agent.llm import MissingApiKeyError
from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.state import (
    AttemptRecord,
    RigState,
    UnityResult,
    UsageTotals,
    score_report,
)
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport
from rig_agent.unity.delivery import UnityDelivery
from rig_agent.unity.prefab import PrefabOptions
from rig_agent.validator.report import validate

MODEL_ERRORS = (AgentRunError, FallbackExceptionGroup, MissingApiKeyError)


def _silent(message: str) -> None:
    pass


class UnityDeliveryLike(Protocol):
    """What the graph needs from the Unity step (UnityDelivery, or a fake in tests)."""

    def apply(self, skeleton: Skeleton) -> UnityResult: ...

    def verify(self, skeleton: Skeleton) -> UnityResult: ...


@dataclass
class GraphDeps:
    """Everything the nodes need from outside, so tests can replace the models and the clock."""

    check_input: Callable[[str], GuardResult]
    plan: Callable[..., PlanResult]
    clock: Callable[[], float] = time.monotonic
    say: Callable[[str], None] = _silent
    config: Settings = field(default_factory=lambda: settings)
    unity: UnityDeliveryLike | None = None


def default_deps(
    say: Callable[[str], None] = _silent, prefab: PrefabOptions | None = None
) -> GraphDeps:
    """The real guard and planner, using the configured models. Prefab options, if given, make
    the Unity step save each verified rig as a prefab."""
    unity = UnityDelivery(say=say, prefab=prefab)
    return GraphDeps(check_input=check_input, plan=plan, say=say, unity=unity)


def describe_error(error: BaseException) -> str:
    """One readable line for a model-side failure, including grouped provider failures."""
    if isinstance(error, FallbackExceptionGroup):
        return "every provider failed: " + "; ".join(str(e) for e in error.exceptions)
    return str(error)


class RigNodes:
    def __init__(self, deps: GraphDeps):
        self.deps = deps

    @property
    def config(self) -> Settings:
        return self.deps.config

    def say(self, message: str) -> None:
        self.deps.say(message)

    # ---- budgets -----------------------------------------------------------------------------

    def budget_problem(self, state: RigState) -> str | None:
        """Why the request may not spend any more, or None if budget is left (LLD 3.7)."""
        cfg = self.config
        usage = state.get("usage") or UsageTotals()
        elapsed = self.deps.clock() - state.get("started_at", self.deps.clock())
        if elapsed >= cfg.max_seconds:
            return f"the {cfg.max_seconds}s time budget is used up"
        if usage.requests >= cfg.max_llm_calls:
            return f"the budget of {cfg.max_llm_calls} model calls is used up"
        if usage.total_tokens >= cfg.max_total_tokens:
            return f"the budget of {cfg.max_total_tokens:,} tokens is used up"
        if usage.tool_calls >= cfg.max_tool_calls:
            return f"the budget of {cfg.max_tool_calls} tool calls is used up"
        return None

    def _limits(self, usage: UsageTotals) -> UsageLimits:
        cfg = self.config
        return UsageLimits(
            request_limit=max(1, cfg.max_llm_calls - usage.requests),
            tool_calls_limit=max(0, cfg.max_tool_calls - usage.tool_calls),
            total_tokens_limit=max(1, cfg.max_total_tokens - usage.total_tokens),
        )

    # ---- nodes -------------------------------------------------------------------------------

    def input_guard(self, state: RigState) -> dict[str, Any]:
        started = self.deps.clock()
        self.say(f"[guard] Input guard ({self.config.guard_model}) ...")
        try:
            guard = self.deps.check_input(state["user_prompt"])
        except MODEL_ERRORS as error:
            return {"started_at": started, "error": describe_error(error)}
        usage = state.get("usage") or UsageTotals()
        if guard.accepted:
            usage = usage.plus(requests=1)
        self.say(f"[guard] {'accepted' if guard.accepted else 'not accepted: ' + guard.category}")
        return {"started_at": started, "guard": guard, "usage": usage, "error": None}

    def plan(self, state: RigState) -> dict[str, Any]:
        cfg = self.config
        usage = state.get("usage") or UsageTotals()
        attempts = state.get("attempts") or []
        problem = self.budget_problem(state)
        if problem:
            return {"error": problem}

        iteration = state.get("iteration", 0) + 1
        last = attempts[-1] if attempts else None
        label = f"[plan {iteration}/{cfg.max_outer_iterations}]"
        if last:
            self.say(
                f"{label} Repairing: the last attempt had {len(last.report.errors)} error(s) "
                f"(score {last.score:.2f})"
            )
        self.say(f"{label} Planner ({cfg.planner_model}) ...")
        remaining = cfg.max_seconds - (self.deps.clock() - state.get("started_at", 0.0))
        try:
            result = self.deps.plan(
                state["user_prompt"],
                state.get("view"),
                previous=last.spec if last else None,
                report=last.report if last else None,
                limits=self._limits(usage),
                timeout=max(remaining, 1.0),
                progress=self.say,
            )
        except MODEL_ERRORS as error:
            return {"iteration": iteration, "error": describe_error(error)}
        self.say(
            f"{label} done: {result.requests} model calls, {result.tool_calls} tool calls, "
            f"{result.input_tokens:,} tokens in, {result.output_tokens:,} out"
        )
        return {
            "rig_spec": result.spec,
            "iteration": iteration,
            "usage": usage.plus(
                requests=result.requests,
                tool_calls=result.tool_calls,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            ),
            "skeleton": None,
            "validation": None,
            "error": None,
        }

    def build(self, state: RigState) -> dict[str, Any]:
        cfg = self.config
        spec = state["rig_spec"]
        assert spec is not None
        provider = cfg.primary_provider
        model = cfg.planner_model if provider == "openai" else cfg.anthropic_planner_model
        try:
            skeleton = build_skeleton(
                spec,
                source_prompt=state["user_prompt"],
                model=f"{provider}:{model}",
                iterations=state["iteration"],
            )
        except BuildError as error:
            self.say(f"[build] cannot build the rig: {error}")
            issue = ValidationIssue(code=IssueCode.UNBUILDABLE, message=str(error))
            return {"skeleton": None, "validation": ValidationReport(issues=[issue])}
        self.say(f"[build] {len(skeleton.bones)} bones")
        return {"skeleton": skeleton, "validation": None}

    def validate(self, state: RigState) -> dict[str, Any]:
        spec, skeleton = state["rig_spec"], state.get("skeleton")
        assert spec is not None
        report = validate(skeleton, spec) if skeleton is not None else state["validation"]
        assert report is not None
        attempt = AttemptRecord(
            iteration=state["iteration"],
            spec=spec,
            report=report,
            score=score_report(report),
            skeleton=skeleton,
        )
        status = "PASSED" if report.passed else "FAILED"
        self.say(
            f"[validate] attempt {attempt.iteration}: {status} ({len(report.errors)} errors, "
            f"{len(report.warnings)} warnings, score {attempt.score:.2f})"
        )
        for issue in report.issues:
            self.say(f"           [{issue.severity}] {issue.code.value}: {issue.message}")
        return {"validation": report, "attempts": [*(state.get("attempts") or []), attempt]}

    def export(self, state: RigState) -> dict[str, Any]:
        skeleton, report = state.get("skeleton"), state.get("validation")
        assert skeleton is not None and report is not None
        result = export(skeleton, report, state["out_dir"])
        self.say(f"[export] wrote {result.skeleton_path} and {result.report_path.name}")
        return {"output_path": str(result.skeleton_path), "status": "success"}

    def unity_apply(self, state: RigState) -> dict[str, Any]:
        """Deliver the rig to the open Unity Editor. A failure never invalidates the rig."""
        skeleton = state.get("skeleton")
        assert skeleton is not None
        if self.deps.unity is None:
            result = UnityResult(status="unavailable", detail="Unity delivery is not configured")
        else:
            self.say("[unity] Delivering to Unity ...")
            result = self.deps.unity.apply(skeleton)
        detail = f" ({result.detail})" if result.detail else ""
        self.say(f"[unity] apply: {result.status}{detail}")
        return {"unity_result": result}

    def unity_verify(self, state: RigState) -> dict[str, Any]:
        """Compare what Unity created with skeleton.json."""
        skeleton = state.get("skeleton")
        assert skeleton is not None and self.deps.unity is not None
        result = self.deps.unity.verify(skeleton)
        detail = f" ({result.detail})" if result.detail else ""
        self.say(f"[unity] verify: {result.status}{detail}")
        return {"unity_result": result}

    def best_effort(self, state: RigState) -> dict[str, Any]:
        attempts = state.get("attempts") or []
        best = max(attempts, key=lambda a: (a.score, a.iteration))
        if state.get("iteration", 0) >= self.config.max_outer_iterations:
            reason = f"{self.config.max_outer_iterations} repair attempts were used"
        else:
            reason = self.budget_problem(state) or state.get("error") or "no repair was possible"
        self.say(
            f"[best_effort] Stopping ({reason}); returning attempt {best.iteration} "
            f"(score {best.score:.2f}, {len(best.report.errors)} errors)"
        )
        update: dict[str, Any] = {
            "rig_spec": best.spec,
            "skeleton": best.skeleton,
            "validation": best.report,
        }
        if best.skeleton is None:
            return update | {
                "status": "error",
                "error": "none of the attempts could be built into a skeleton",
            }
        result = export(best.skeleton, best.report, state["out_dir"])
        self.say(f"[export] wrote {result.skeleton_path} (not import-ready: validation failed)")
        unity = None
        if state.get("unity_mode"):
            unity = UnityResult(status="skipped", detail="The rig did not pass validation.")
        return update | {
            "output_path": str(result.skeleton_path),
            "status": "best_effort",
            "unity_result": unity,
        }

    def reject(self, state: RigState) -> dict[str, Any]:
        return {"status": "rejected"}

    def fail(self, state: RigState) -> dict[str, Any]:
        return {"status": "error", "error": state.get("error") or "the request failed"}

    # ---- routers -----------------------------------------------------------------------------

    def after_guard(self, state: RigState) -> str:
        if state.get("error"):
            return "fail"
        guard = state.get("guard")
        return "plan" if guard and guard.accepted else "reject"

    def after_plan(self, state: RigState) -> str:
        if state.get("error"):
            return "best_effort" if state.get("attempts") else "fail"
        return "build"

    def after_export(self, state: RigState) -> str:
        return "unity_apply" if state.get("unity_mode") else "end"

    def after_unity_apply(self, state: RigState) -> str:
        result = state.get("unity_result")
        return "unity_verify" if result and result.status == "applied" else "end"

    def after_validate(self, state: RigState) -> str:
        report = state["validation"]
        assert report is not None
        if report.passed:
            return "export"
        if state["iteration"] < self.config.max_outer_iterations and not self.budget_problem(state):
            return "plan"
        return "best_effort"
