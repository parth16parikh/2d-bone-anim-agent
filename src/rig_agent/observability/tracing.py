"""Logfire tracing: instruments Pydantic AI agent calls and traces each LangGraph node (LLD 3.9,
open question 6; the observability row: "Traces for each run: tool calls, tokens, latency, and
validation failures").

configure() is safe to call always, even with no token at all: send_to_logfire="if-token-present"
means nothing is ever sent anywhere unless LOGFIRE_TOKEN (settings.logfire_token) is actually set,
the same way OPENAI_API_KEY and ANTHROPIC_API_KEY are optional until you add them. Spans created
before configure() runs (as most of the test suite does, deliberately) are simply inert rather than
an error; pyproject.toml's [tool.logfire] silences the resulting warning.

logfire.instrument_pydantic_ai() covers every guard and planner call on its own: each model
request, tool call and its tokens. traced_node() covers the rest of LLD's list -- latency and
validation failures -- for the graph steps that never call the model at all (build, validate,
export, the Unity steps).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import logfire

from rig_agent.config import settings

_configured = False


def configure() -> None:
    """Set up Logfire once per process. Safe to call repeatedly, and safe with no token."""
    global _configured
    if _configured:
        return
    logfire.configure(
        token=settings.logfire_token,
        service_name="rig-agent",
        send_to_logfire="if-token-present",
        console=False,  # progress already goes to stderr via `_say`; do not print it twice
    )
    logfire.instrument_pydantic_ai()  # every guard/planner call: tools, tokens, latency
    _configured = True


Node = Callable[[Any], dict[str, Any]]  # a node of either graph: RigState or AnimState in


def traced_node(name: str, fn: Node) -> Callable[..., Any]:
    """Wrap one LangGraph node so calling it opens a Logfire span named after it.

    Records the iteration the state was on, and whichever of the well-known result keys the node
    actually returned (a node's return value is always a partial state update): the guard's
    verdict, the running usage totals, the validation report and the Unity result. These are the
    same fields the CLI already prints to stderr, now attached to the span instead of only text.

    Returns Callable[..., Any] rather than Node: LangGraph's add_node() infers its state type from
    a Protocol match on the exact callable it is given, which mypy cannot do through a named
    wrapper function (the same reason the un-wrapped `getattr(nodes, name)` this replaces was only
    ever accepted as `Any`, never checked against that Protocol either).
    """

    def wrapped(state: Mapping[str, Any]) -> dict[str, Any]:
        with logfire.span("node {node}", node=name, iteration=state.get("iteration")) as span:
            result = fn(state)
            _annotate(span, result)
            return result

    return wrapped


def _annotate(span: logfire.LogfireSpan, result: dict[str, Any]) -> None:
    guard = result.get("guard")
    if guard is not None:
        span.set_attributes({"guard.accepted": guard.accepted, "guard.category": guard.category})

    usage = result.get("usage")
    if usage is not None:
        span.set_attributes(
            {
                "usage.requests": usage.requests,
                "usage.tool_calls": usage.tool_calls,
                "usage.total_tokens": usage.total_tokens,
            }
        )

    validation = result.get("validation")
    if validation is not None:
        span.set_attributes(
            {
                "validation.passed": validation.passed,
                "validation.errors": len(validation.errors),
                "validation.warnings": len(validation.warnings),
            }
        )

    unity_result = result.get("unity_result")
    if unity_result is not None:
        span.set_attribute("unity.status", unity_result.status)

    status = result.get("status")
    if status is not None:
        span.set_attribute("status", status)
