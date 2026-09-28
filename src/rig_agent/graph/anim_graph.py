"""The animation pipeline (Goal 2, A3): a LangGraph flow with the same shape as the rig pipeline.

input_guard -> plan -> bake (bake + validate) -> export -> [unity]
                 ^         | fails, repairs left
                 +---------+
plan: a clip this rig's view does not allow (a walk on a front-view rig) -> wrong_view (stops
      with a clear message; nothing is swapped in)
out of repairs or budget -> best_effort (the best attempt is written with its failing report)
"""

import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from pydantic_ai.exceptions import AgentRunError, FallbackExceptionGroup

from rig_agent.agent.anim_planner import AnimPlanResult, plan_animation
from rig_agent.animation.baker import BakeError, bake
from rig_agent.animation.validator import validate_clip
from rig_agent.config import Settings, settings
from rig_agent.export.animation_exporter import animation_paths, export_animation
from rig_agent.graph.budget import budget_problem, remaining_limits
from rig_agent.graph.nodes import describe_error
from rig_agent.guardrails.anim_guard import check_animation_input
from rig_agent.llm import MissingApiKeyError
from rig_agent.observability.tracing import traced_node
from rig_agent.schemas.animation import CLIP_VIEWS, AnimationClip, AnimationSpec
from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.state import Status, UnityResult, UsageTotals, score_report
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport
from rig_agent.unity.animation import rig_object_names

MODEL_ERRORS = (AgentRunError, FallbackExceptionGroup, MissingApiKeyError)
RECURSION_LIMIT = 60
_ARTICLES = {"a", "an", "the"}


class AnimAttempt(BaseModel):
    iteration: int
    spec: AnimationSpec
    report: ValidationReport
    score: float
    clip: AnimationClip | None = None


class AnimState(TypedDict, total=False):
    request_id: str
    user_prompt: str
    rig_folder: str
    skeleton: Skeleton
    clip_name: str
    unity_mode: bool
    started_at: float
    guard: GuardResult | None
    spec: AnimationSpec | None
    clip: AnimationClip | None
    validation: ValidationReport | None
    iteration: int
    attempts: list[AnimAttempt]
    usage: UsageTotals
    output_path: str | None
    unity_result: UnityResult | None
    error: str | None
    status: Status


class AnimUnityLike(Protocol):
    def deliver_animation(
        self, clip: AnimationClip, skeleton: Skeleton, rig_names: list[str]
    ) -> UnityResult: ...


def _silent(message: str) -> None:
    pass


@dataclass
class AnimDeps:
    check_input: Callable[[str], GuardResult]
    plan: Callable[..., AnimPlanResult]
    clock: Callable[[], float] = time.monotonic
    say: Callable[[str], None] = _silent
    config: Settings = field(default_factory=lambda: settings)
    unity: AnimUnityLike | None = None


def default_anim_deps(say: Callable[[str], None] = _silent) -> AnimDeps:
    from rig_agent.unity.delivery import UnityDelivery

    return AnimDeps(
        check_input=check_animation_input,
        plan=plan_animation,
        say=say,
        unity=UnityDelivery(say=say),
    )


def clip_file_name(description: str) -> str:
    """A file name from the request: "a heavy, tired walk" -> "heavy_tired_walk"."""
    words = re.findall(r"[a-z0-9]+", description.lower())
    while words and words[0] in _ARTICLES:
        words = words[1:]
    return "_".join(words)[:40].strip("_") or "clip"


class AnimNodes:
    def __init__(self, deps: AnimDeps):
        self.deps = deps

    @property
    def config(self) -> Settings:
        return self.deps.config

    def say(self, message: str) -> None:
        self.deps.say(message)

    def _budget(self, state: AnimState) -> str | None:
        usage = state.get("usage") or UsageTotals()
        return budget_problem(
            self.config, usage, self.deps.clock() - state.get("started_at", self.deps.clock())
        )

    # ---- nodes -------------------------------------------------------------------------------

    def input_guard(self, state: AnimState) -> dict[str, Any]:
        started = self.deps.clock()
        self.say(f"[guard] Animation request guard ({self.config.guard_model}) ...")
        try:
            guard = self.deps.check_input(state["user_prompt"])
        except MODEL_ERRORS as error:
            return {"started_at": started, "error": describe_error(error)}
        usage = state.get("usage") or UsageTotals()
        if guard.accepted:
            usage = usage.plus(requests=1)
        self.say(f"[guard] {'accepted' if guard.accepted else 'not accepted: ' + guard.category}")
        return {"started_at": started, "guard": guard, "usage": usage, "error": None}

    def plan(self, state: AnimState) -> dict[str, Any]:
        problem = self._budget(state)
        if problem:
            return {"error": problem}
        usage = state.get("usage") or UsageTotals()
        attempts = state.get("attempts") or []
        iteration = state.get("iteration", 0) + 1
        last = attempts[-1] if attempts else None
        label = f"[plan {iteration}/{self.config.max_outer_iterations}]"
        if last:
            self.say(f"{label} Repairing: the last clip had {len(last.report.errors)} error(s)")
        self.say(f"{label} Animation planner ({self.config.planner_model}) ...")
        remaining = self.config.max_seconds - (self.deps.clock() - state.get("started_at", 0.0))
        try:
            result = self.deps.plan(
                state["user_prompt"],
                state["skeleton"],
                previous=last.spec if last else None,
                report=last.report if last else None,
                limits=remaining_limits(self.config, usage),
                timeout=max(remaining, 1.0),
                progress=self.say,
            )
        except MODEL_ERRORS as error:
            return {"iteration": iteration, "error": describe_error(error)}
        spec = result.spec
        self.say(
            f"{label} {spec.clip} ('{spec.style}'): speed {spec.speed:g}, stride {spec.stride:g}, "
            f"bounce {spec.bounce:g}, arm swing {spec.arm_swing:g}, knee lift {spec.knee_lift:g}, "
            f"lean {spec.lean_deg:g}°"
        )
        return {
            "spec": spec,
            "iteration": iteration,
            "usage": usage.plus(
                requests=result.requests,
                tool_calls=result.tool_calls,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            ),
            "error": None,
        }

    def wrong_view(self, state: AnimState) -> dict[str, Any]:
        spec, skeleton = state["spec"], state["skeleton"]
        assert spec is not None
        allowed = " or ".join(CLIP_VIEWS[spec.clip])
        message = (
            f"a {spec.clip} clip needs a {allowed}-view rig, and '{skeleton.rig_name}' is a "
            f"{skeleton.view}-view rig. Build a side-view rig to animate this "
            f'(rig-agent run "..." --view side), or ask for an idle.'
        )
        self.say(f"[plan] {message}")
        return {"status": "error", "error": message}

    def bake(self, state: AnimState) -> dict[str, Any]:
        spec, skeleton = state["spec"], state["skeleton"]
        assert spec is not None
        try:
            clip: AnimationClip | None = bake(spec, skeleton, name=state["clip_name"])
        except BakeError as error:
            clip = None
            report = ValidationReport(
                issues=[ValidationIssue(code=IssueCode.UNBUILDABLE, message=str(error))]
            )
        if clip is not None:
            report = validate_clip(clip, skeleton)
        attempt = AnimAttempt(
            iteration=state["iteration"],
            spec=spec,
            report=report,
            score=score_report(report),
            clip=clip,
        )
        status = "PASSED" if report.passed else "FAILED"
        frames = f"{clip.frame_count} frames, " if clip else ""
        self.say(
            f"[bake] attempt {attempt.iteration}: {frames}{status} ({len(report.errors)} errors)"
        )
        for issue in report.issues:
            self.say(f"        [{issue.severity}] {issue.code.value}: {issue.message}")
        return {
            "clip": clip,
            "validation": report,
            "attempts": [*(state.get("attempts") or []), attempt],
        }

    def export(self, state: AnimState) -> dict[str, Any]:
        clip, report = state.get("clip"), state.get("validation")
        assert clip is not None and report is not None
        paths = animation_paths(state["rig_folder"], clip.name)
        if paths.clip_path.is_file():
            self.say(f"[export] note: replacing the clip already at {paths.clip_path}")
        export_animation(clip, report, state["rig_folder"])
        self.say(f"[export] wrote {paths.clip_path} and {paths.report_path.name}")
        return {"output_path": str(paths.clip_path), "status": "success"}

    def unity(self, state: AnimState) -> dict[str, Any]:
        clip, skeleton = state.get("clip"), state["skeleton"]
        assert clip is not None
        if self.deps.unity is None:
            return {
                "unity_result": UnityResult(
                    status="unavailable", detail="Unity delivery is not configured"
                )
            }
        self.say("[unity] Delivering the clip to Unity ...")
        result = self.deps.unity.deliver_animation(
            clip, skeleton, rig_object_names(skeleton, state["rig_folder"])
        )
        self.say(f"[unity] {result.status}" + (f" ({result.detail})" if result.detail else ""))
        return {"unity_result": result}

    def best_effort(self, state: AnimState) -> dict[str, Any]:
        attempts = state.get("attempts") or []
        best = max(attempts, key=lambda a: (a.score, a.iteration))
        reason = (
            self._budget(state)
            or state.get("error")
            or f"{self.config.max_outer_iterations} attempts were used"
        )
        self.say(f"[best_effort] Stopping ({reason}); keeping attempt {best.iteration}")
        update: dict[str, Any] = {"spec": best.spec, "clip": best.clip, "validation": best.report}
        if best.clip is None:
            return update | {"status": "error", "error": "none of the attempts could be baked"}
        export_animation(best.clip, best.report, state["rig_folder"])
        path = animation_paths(state["rig_folder"], best.clip.name).clip_path
        self.say(f"[export] wrote {path} (not import-ready: validation failed)")
        unity = (
            UnityResult(status="skipped", detail="The clip did not pass validation.")
            if state.get("unity_mode")
            else None
        )
        return update | {"output_path": str(path), "status": "best_effort", "unity_result": unity}

    def reject(self, state: AnimState) -> dict[str, Any]:
        return {"status": "rejected"}

    def fail(self, state: AnimState) -> dict[str, Any]:
        return {"status": "error", "error": state.get("error") or "the request failed"}

    # ---- routers -----------------------------------------------------------------------------

    def after_guard(self, state: AnimState) -> str:
        if state.get("error"):
            return "fail"
        guard = state.get("guard")
        return "plan" if guard and guard.accepted else "reject"

    def after_plan(self, state: AnimState) -> str:
        if state.get("error"):
            return "best_effort" if state.get("attempts") else "fail"
        spec = state["spec"]
        assert spec is not None
        return "bake" if state["skeleton"].view in CLIP_VIEWS[spec.clip] else "wrong_view"

    def after_bake(self, state: AnimState) -> str:
        report = state["validation"]
        assert report is not None
        if report.passed:
            return "export"
        if state["iteration"] < self.config.max_outer_iterations and not self._budget(state):
            return "plan"
        return "best_effort"

    def after_export(self, state: AnimState) -> str:
        return "unity" if state.get("unity_mode") else "end"


NODES = (
    "input_guard",
    "plan",
    "wrong_view",
    "bake",
    "export",
    "unity",
    "best_effort",
    "reject",
    "fail",
)


def build_anim_graph(deps: AnimDeps | None = None):
    nodes = AnimNodes(deps or default_anim_deps())
    graph = StateGraph(AnimState)
    for name in NODES:
        graph.add_node(name, traced_node(name, getattr(nodes, name)))
    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges(
        "input_guard", nodes.after_guard, {"plan": "plan", "reject": "reject", "fail": "fail"}
    )
    graph.add_conditional_edges(
        "plan",
        nodes.after_plan,
        {"bake": "bake", "wrong_view": "wrong_view", "best_effort": "best_effort", "fail": "fail"},
    )
    graph.add_conditional_edges(
        "bake", nodes.after_bake, {"export": "export", "plan": "plan", "best_effort": "best_effort"}
    )
    graph.add_conditional_edges("export", nodes.after_export, {"unity": "unity", "end": END})
    for terminal in ("unity", "wrong_view", "best_effort", "reject", "fail"):
        graph.add_edge(terminal, END)
    return graph.compile()


def run_animation(
    description: str,
    skeleton: Skeleton,
    rig_folder: str | Path,
    *,
    name: str | None = None,
    unity_mode: bool = False,
    deps: AnimDeps | None = None,
) -> AnimState:
    """One animation request through the whole pipeline; returns the final state."""
    state: AnimState = {
        "request_id": uuid.uuid4().hex,
        "user_prompt": description,
        "rig_folder": str(rig_folder),
        "skeleton": skeleton,
        "clip_name": name or clip_file_name(description),
        "unity_mode": unity_mode,
        "iteration": 0,
        "attempts": [],
        "usage": UsageTotals(),
        "unity_result": None,
        "error": None,
        "status": "running",
    }
    app = build_anim_graph(deps)
    return app.invoke(state, {"recursion_limit": RECURSION_LIMIT})  # type: ignore[return-value]
