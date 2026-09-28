"""The per-request budget (LLD 3.7), shared by the rig pipeline and the animation pipeline."""

from pydantic_ai.usage import UsageLimits

from rig_agent.config import Settings
from rig_agent.schemas.state import UsageTotals


def budget_problem(config: Settings, usage: UsageTotals, elapsed: float) -> str | None:
    """Why the request may not spend any more, or None if budget is left."""
    if elapsed >= config.max_seconds:
        return f"the {config.max_seconds}s time budget is used up"
    if usage.requests >= config.max_llm_calls:
        return f"the budget of {config.max_llm_calls} model calls is used up"
    if usage.total_tokens >= config.max_total_tokens:
        return f"the budget of {config.max_total_tokens:,} tokens is used up"
    if usage.tool_calls >= config.max_tool_calls:
        return f"the budget of {config.max_tool_calls} tool calls is used up"
    return None


def remaining_limits(config: Settings, usage: UsageTotals) -> UsageLimits:
    """What is left of the budget, as limits for the next model run."""
    return UsageLimits(
        request_limit=max(1, config.max_llm_calls - usage.requests),
        tool_calls_limit=max(0, config.max_tool_calls - usage.tool_calls),
        total_tokens_limit=max(1, config.max_total_tokens - usage.total_tokens),
    )
