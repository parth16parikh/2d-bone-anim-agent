"""The Planner Agent: system prompt + tools wired into a Pydantic AI agent returning a RigSpec (LLD 3.4 #2)."""

import functools
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from rig_agent.agent.system_prompt import build_repair_message, build_system_prompt, format_request
from rig_agent.agent.tools import PLANNER_TOOLS
from rig_agent.config import settings
from rig_agent.llm import build_model
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.validation import ValidationReport
from rig_agent.vocabulary.bones import View

Progress = Callable[[str], None]


def _short(value: Any, limit: int = 90) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _describe_args(kwargs: dict[str, Any]) -> str:
    parts = []
    for name, value in kwargs.items():
        if isinstance(value, RigSpec):
            parts.append(f"style={value.style!r}, view={value.view}, preset={value.preset}")
        else:
            parts.append(f"{name}={_short(value, 40)}")
    return ", ".join(parts)


def _outcome(result: Any) -> str:
    if isinstance(result, ValidationReport):
        return f"{len(result.errors)} errors, {len(result.warnings)} warnings"
    if isinstance(result, dict) and "error" in result:
        return f"error: {_short(result['error'])}"
    if isinstance(result, dict) and result.get("warnings"):
        return f"{len(result['warnings'])} warnings"
    return "ok"


def _logged(tool: Callable[..., Any], say: Progress, started: float) -> Callable[..., Any]:
    """The same tool, reporting each call and result. Its name and signature are unchanged."""

    @functools.wraps(tool)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        say(
            f"  [{time.perf_counter() - started:5.1f}s] -> {tool.__name__}({_describe_args(kwargs)})"
        )
        try:
            result = tool(*args, **kwargs)
        except Exception as error:
            say(f"  [{time.perf_counter() - started:5.1f}s] !! {tool.__name__} raised {error!r}")
            raise
        say(f"  [{time.perf_counter() - started:5.1f}s] <- {tool.__name__}: {_outcome(result)}")
        return result

    return wrapper


def usage_limits() -> UsageLimits:
    """The per-run budget: model calls and tool calls (LLD 3.7, 3.8.2)."""
    return UsageLimits(
        request_limit=settings.max_llm_calls, tool_calls_limit=settings.max_tool_calls
    )


def build_planner(
    model: Model | str | None = None, progress: Progress | None = None
) -> Agent[None, RigSpec]:
    """The planner agent. Without a model it uses the configured OpenAI planner model.

    `progress`, when given, is called with a line of text for each tool call and result.

    The agent returns only a RigSpec (schema-validated, retried on error), and its tools are the
    read-only knowledge tools; nothing here can reach Unity.
    """
    started = time.perf_counter()
    tools = [_logged(t, progress, started) for t in PLANNER_TOOLS] if progress else PLANNER_TOOLS
    return Agent(
        model or build_model("planner"),
        output_type=RigSpec,
        instructions=build_system_prompt(),
        tools=tools,
        retries=settings.max_inner_retries,
        defer_model_check=True,
    )


@dataclass(frozen=True)
class PlanResult:
    spec: RigSpec
    requests: int  # model calls made
    tool_calls: int
    input_tokens: int
    output_tokens: int


def plan(
    description: str,
    view: View | None = None,
    *,
    previous: RigSpec | None = None,
    report: ValidationReport | None = None,
    agent: Agent[None, RigSpec] | None = None,
    progress: Progress | None = None,
    limits: UsageLimits | None = None,
    timeout: float | None = None,
) -> PlanResult:
    """Ask the planner for a RigSpec. Pass `previous` and `report` to repair an earlier attempt.

    `progress`, when given, is called with a line of text for each tool call and result. It only
    works when plan() builds the agent itself; for your own agent, pass it to build_planner().
    `limits` replaces the default budget, and `timeout` (seconds) applies to each model call.
    """
    if agent is not None and progress is not None:
        raise ValueError("pass progress to build_planner() when you supply your own agent")
    planner = agent or build_planner(progress=progress)
    message = format_request(description, view)
    if previous is not None and report is not None:
        message += "\n\n" + build_repair_message(previous, report)
    result = planner.run_sync(
        message,
        usage_limits=limits or usage_limits(),
        model_settings=ModelSettings(timeout=timeout) if timeout else None,
    )
    usage = result.usage
    return PlanResult(
        spec=result.output,
        requests=usage.requests,
        tool_calls=usage.tool_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
