"""The graph running the real plan() and a real Pydantic AI agent; only the model is scripted."""

from pydantic_ai.messages import UserPromptPart

from graph_helpers import ACCEPT, BAD_1, GOOD, make_deps
from rig_agent.agent.planner import build_planner
from rig_agent.agent.planner import plan as real_plan
from rig_agent.export.json_exporter import load_report
from rig_agent.graph.build_graph import run_rig
from test_planner import Script


def deps_with_real_planner(script, lines):
    deps = make_deps(None, guard=ACCEPT, lines=lines)

    def plan(description, view=None, *, progress=None, **kw):
        agent = build_planner(script.model_for_test(), progress=progress)
        return real_plan(description, view, agent=agent, **kw)

    deps.plan = plan
    return deps


class ScriptedModel(Script):
    def model_for_test(self):
        from pydantic_ai.models.function import FunctionModel

        return FunctionModel(self)


def user_prompts(script):
    return [
        "".join(p.content for p in request[-1].parts if isinstance(p, UserPromptPart))
        for request in script.requests
        if any(isinstance(p, UserPromptPart) for p in request[-1].parts)
    ]


def test_a_repair_round_runs_through_the_real_planner(tmp_path):
    script = ScriptedModel(("dry_run_validate", BAD_1), ("final", BAD_1), ("final", GOOD))
    lines = []
    state = run_rig(
        "a chibi knight", out_dir=str(tmp_path), deps=deps_with_real_planner(script, lines)
    )

    assert state["status"] == "success" and state["iteration"] == 2
    assert [a.report.passed for a in state["attempts"]] == [False, True]
    assert state["usage"].requests == 1 + 2 + 1  # guard, first plan (tool call + answer), repair
    assert state["usage"].tool_calls == 1
    assert load_report(tmp_path / "validation_report.json").passed

    first, repair = user_prompts(script)
    assert "failed validation" not in first
    assert "failed validation" in repair and "mirror_coincident" in repair
    assert "Change only the fields named in the listed errors" in repair

    text = "\n".join(lines)
    assert "-> dry_run_validate(style='chibi knight'" in text
    assert "<- dry_run_validate: 1 errors, 0 warnings" in text
    assert "[plan 2/3] Repairing" in text


def test_the_remaining_budget_reaches_the_real_agent(tmp_path):
    script = ScriptedModel(("list_vocabulary", {}))  # loops on a tool call forever
    lines = []
    state = run_rig("a knight", out_dir=str(tmp_path), deps=deps_with_real_planner(script, lines))
    assert state["status"] == "error"
    assert "request_limit of 11" in state["error"]  # 12 model calls minus the guard's one
    assert len(script.requests) == 11
