"""The animation planner (Goal 2, A3): a Pydantic AI agent that turns a motion description into an
AnimationSpec for a given rig. Same shape as the rig planner (agent/planner.py): typed output,
schema retries, knowledge tools, a budget; the rig is the agent's dependency, so its tools can
bake and preview on it."""

import time
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from rig_agent.agent.anim_prompt import (
    build_anim_repair_message,
    build_anim_system_prompt,
    format_anim_request,
)
from rig_agent.agent.anim_tools import ANIM_TOOLS
from rig_agent.agent.planner import Progress, _logged, rejected_outputs, usage_limits
from rig_agent.config import settings
from rig_agent.llm import build_model
from rig_agent.schemas.animation import AnimationSpec
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import ValidationReport


@dataclass(frozen=True)
class AnimPlanResult:
    spec: AnimationSpec
    requests: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    output_retries: tuple[str, ...] = ()


def build_anim_planner(
    model: Model | str | None = None, progress: Progress | None = None
) -> Agent[Skeleton, AnimationSpec]:
    started = time.perf_counter()
    tools = [_logged(t, progress, started) for t in ANIM_TOOLS] if progress else ANIM_TOOLS
    return Agent(
        model or build_model("planner"),
        deps_type=Skeleton,
        output_type=AnimationSpec,
        instructions=build_anim_system_prompt(),
        tools=tools,
        retries=settings.max_inner_retries,
        defer_model_check=True,
    )


def plan_animation(
    description: str,
    skeleton: Skeleton,
    *,
    previous: AnimationSpec | None = None,
    report: ValidationReport | None = None,
    agent: Agent[Skeleton, AnimationSpec] | None = None,
    progress: Progress | None = None,
    limits: UsageLimits | None = None,
    timeout: float | None = None,
) -> AnimPlanResult:
    """Ask the planner for an AnimationSpec. Pass `previous` and `report` to repair an attempt."""
    if agent is not None and progress is not None:
        raise ValueError("pass progress to build_anim_planner() when you supply your own agent")
    planner = agent or build_anim_planner(progress=progress)
    message = format_anim_request(description, skeleton)
    if previous is not None and report is not None:
        message += "\n\n" + build_anim_repair_message(previous, report)
    result = planner.run_sync(
        message,
        deps=skeleton,
        usage_limits=limits or usage_limits(),
        model_settings=ModelSettings(timeout=timeout) if timeout else None,
    )
    usage = result.usage
    return AnimPlanResult(
        spec=result.output,
        requests=usage.requests,
        tool_calls=usage.tool_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        output_retries=rejected_outputs(result.all_messages()),
    )
