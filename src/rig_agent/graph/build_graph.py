"""Wires the nodes into the LangGraph StateGraph with the bounded repair loop and the Unity step (LLD 3.7)."""

import uuid
from typing import Any

from langgraph.graph import END, START, StateGraph

from rig_agent.graph.nodes import GraphDeps, RigNodes, default_deps
from rig_agent.schemas.state import RigState, UsageTotals
from rig_agent.vocabulary.bones import View

RECURSION_LIMIT = 60  # far above the longest legal path (guard, 3 x plan/build/validate, export)


def build_graph(deps: GraphDeps | None = None, checkpointer: Any = None):
    """The compiled graph: guard, then plan/build/validate with up to N repairs, then export.

    Pass a checkpointer (for example langgraph's MemorySaver) to save state after every node.
    """
    nodes = RigNodes(deps or default_deps())
    graph = StateGraph(RigState)
    for name in (
        "input_guard",
        "plan",
        "build",
        "validate",
        "export",
        "unity_apply",
        "unity_verify",
        "best_effort",
        "reject",
        "fail",
    ):
        graph.add_node(name, getattr(nodes, name))

    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges(
        "input_guard", nodes.after_guard, {"plan": "plan", "reject": "reject", "fail": "fail"}
    )
    graph.add_conditional_edges(
        "plan", nodes.after_plan, {"build": "build", "best_effort": "best_effort", "fail": "fail"}
    )
    graph.add_edge("build", "validate")
    graph.add_conditional_edges(
        "validate",
        nodes.after_validate,
        {"export": "export", "plan": "plan", "best_effort": "best_effort"},
    )
    graph.add_conditional_edges(
        "export", nodes.after_export, {"unity_apply": "unity_apply", "end": END}
    )
    graph.add_conditional_edges(
        "unity_apply", nodes.after_unity_apply, {"unity_verify": "unity_verify", "end": END}
    )
    for terminal in ("unity_verify", "best_effort", "reject", "fail"):
        graph.add_edge(terminal, END)
    return graph.compile(checkpointer=checkpointer)


def initial_state(
    prompt: str, view: View | None, unity_mode: bool, out_dir: str, request_id: str
) -> RigState:
    return {
        "request_id": request_id,
        "user_prompt": prompt,
        "view": view,
        "unity_mode": unity_mode,
        "out_dir": out_dir,
        "iteration": 0,
        "attempts": [],
        "usage": UsageTotals(),
        "unity_result": None,
        "error": None,
        "status": "running",
    }


def run_rig(
    prompt: str,
    *,
    view: View | None = None,
    unity_mode: bool = False,
    out_dir: str = "out",
    deps: GraphDeps | None = None,
    checkpointer: Any = None,
) -> RigState:
    """Run one request through the whole graph and return the final state."""
    request_id = uuid.uuid4().hex
    app = build_graph(deps, checkpointer)
    config = {"recursion_limit": RECURSION_LIMIT, "configurable": {"thread_id": request_id}}
    return app.invoke(initial_state(prompt, view, unity_mode, out_dir, request_id), config)  # type: ignore[return-value]
