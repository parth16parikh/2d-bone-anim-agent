import json

import pytest
from langgraph.checkpoint.memory import MemorySaver
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.usage import UsageLimits

from graph_helpers import (
    BAD_1,
    BAD_2,
    GOOD,
    UNBUILDABLE,
    Clock,
    FakeDelivery,
    FakePlanner,
    horn,
    make_deps,
)
from rig_agent.config import Settings
from rig_agent.export.json_exporter import load_report, load_skeleton
from rig_agent.graph.build_graph import build_graph, initial_state, run_rig
from rig_agent.llm import MissingApiKeyError
from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.state import UnityResult


def run(planner, tmp_path, **kw):
    lines = []
    deps_kw = {k: kw.pop(k) for k in ("guard", "clock", "config", "unity") if k in kw}
    state = run_rig(
        "a chibi knight",
        out_dir=str(tmp_path),
        deps=make_deps(planner, lines=lines, **deps_kw),
        **kw,
    )
    return state, lines


# ---- the happy path ------------------------------------------------------------------------------


def test_a_good_first_attempt_succeeds_and_exports(tmp_path):
    planner = FakePlanner(GOOD)
    state, _ = run(planner, tmp_path)
    assert state["status"] == "success" and state["iteration"] == 1
    assert len(state["attempts"]) == 1 and state["attempts"][0].score == 1.0
    assert state["validation"].passed and state["error"] is None
    assert state["output_path"] == str(tmp_path / "skeleton.json")
    assert load_skeleton(tmp_path / "skeleton.json").metadata.iterations == 1
    assert load_report(tmp_path / "validation_report.json").passed
    assert len(planner.calls) == 1


def test_the_planner_receives_the_prompt_the_view_and_no_repair_context(tmp_path):
    planner = FakePlanner(GOOD)
    run_rig("a chibi knight", view="front", out_dir=str(tmp_path), deps=make_deps(planner))
    call = planner.calls[0]
    assert (call["description"], call["view"]) == ("a chibi knight", "front")
    assert call["previous"] is None and call["report"] is None


def test_usage_adds_the_guard_call_and_the_planner_run(tmp_path):
    state, _ = run(FakePlanner(GOOD, requests=4, tool_calls=3, tokens=(2000, 300)), tmp_path)
    usage = state["usage"]
    assert (usage.requests, usage.tool_calls) == (5, 3)
    assert (usage.input_tokens, usage.output_tokens) == (2000, 300)


def test_the_skeleton_records_the_model_and_iteration(tmp_path):
    state, _ = run(FakePlanner(GOOD), tmp_path)
    assert state["skeleton"].metadata.model == "openai:gpt-5.4-mini"


# ---- the repair loop -----------------------------------------------------------------------------


def test_a_failed_attempt_is_repaired_with_the_previous_spec_and_report(tmp_path):
    planner = FakePlanner(BAD_1, GOOD)
    state, lines = run(planner, tmp_path)
    assert state["status"] == "success" and state["iteration"] == 2
    assert [a.iteration for a in state["attempts"]] == [1, 2]
    assert [a.report.passed for a in state["attempts"]] == [False, True]

    second = planner.calls[1]
    assert second["previous"] == RigSpec.model_validate(BAD_1)
    assert second["report"].has("mirror_coincident")
    assert load_skeleton(tmp_path / "skeleton.json").metadata.iterations == 2
    assert any("Repairing: the last attempt had 1 error(s)" in line for line in lines)


def test_an_unbuildable_spec_is_repaired_like_any_other_failure(tmp_path):
    planner = FakePlanner(UNBUILDABLE, GOOD)
    state, _ = run(planner, tmp_path)
    assert state["status"] == "success"
    first = state["attempts"][0]
    assert first.skeleton is None and first.score == 0.0 and first.report.has("unbuildable")
    assert "no_such_bone" in planner.calls[1]["report"].issues[0].message


def test_repairs_stop_after_three_attempts_and_return_the_best_one(tmp_path):
    planner = FakePlanner(BAD_1, BAD_1, BAD_1)
    state, lines = run(planner, tmp_path)
    assert len(planner.calls) == 3 and state["iteration"] == 3
    assert state["status"] == "best_effort" and len(state["attempts"]) == 3
    assert any("3 repair attempts were used" in line for line in lines)
    assert load_report(tmp_path / "validation_report.json").passed is False
    assert (tmp_path / "skeleton.json").exists() and state["skeleton"] is not None


def test_best_effort_returns_the_highest_scoring_attempt(tmp_path):
    state, _ = run(FakePlanner(BAD_2, BAD_1, BAD_2), tmp_path)
    scores = [a.score for a in state["attempts"]]
    assert scores == pytest.approx([0.8, 0.9, 0.8])
    assert state["rig_spec"] == RigSpec.model_validate(BAD_1)
    assert len(state["validation"].errors) == 1


def test_the_latest_attempt_wins_a_tie(tmp_path):
    other = horn(name="extra_horn_b")
    state, _ = run(FakePlanner(BAD_1, other, BAD_1), tmp_path)
    assert state["attempts"][0].score == state["attempts"][2].score
    assert state["skeleton"].metadata.iterations == 3


def test_a_buildable_attempt_beats_unbuildable_ones(tmp_path):
    state, _ = run(FakePlanner(UNBUILDABLE, BAD_1, UNBUILDABLE), tmp_path)
    assert state["status"] == "best_effort"
    assert state["rig_spec"] == RigSpec.model_validate(BAD_1)


def test_when_no_attempt_can_be_built_the_result_is_an_error_without_files(tmp_path):
    state, _ = run(FakePlanner(UNBUILDABLE), tmp_path)
    assert state["status"] == "error" and len(state["attempts"]) == 3
    assert "none of the attempts could be built" in state["error"]
    assert not (tmp_path / "skeleton.json").exists() and state.get("output_path") is None


# ---- guard and errors ----------------------------------------------------------------------------


def test_a_rejected_request_never_reaches_the_planner(tmp_path):
    horse = GuardResult(
        accepted=False, category="non_humanoid", reason="A horse.", suggestion="A person."
    )
    planner = FakePlanner(GOOD)
    state, lines = run(planner, tmp_path, guard=horse)
    assert state["status"] == "rejected" and state["guard"] == horse
    assert planner.calls == [] and state["usage"].requests == 0
    assert not (tmp_path / "skeleton.json").exists()
    assert "[guard] not accepted: non_humanoid" in lines


def test_a_guard_failure_is_an_error_not_a_crash(tmp_path):
    state, _ = run(
        FakePlanner(GOOD), tmp_path, guard=MissingApiKeyError("OPENAI_API_KEY is not set.")
    )
    assert state["status"] == "error" and "OPENAI_API_KEY" in state["error"]


def test_a_planner_failure_on_the_first_attempt_is_an_error(tmp_path):
    state, _ = run(FakePlanner(UnexpectedModelBehavior("kept returning invalid output")), tmp_path)
    assert state["status"] == "error" and "invalid output" in state["error"]
    assert state["attempts"] == [] and state["iteration"] == 1


def test_a_planner_failure_after_an_attempt_returns_the_best_effort(tmp_path):
    state, lines = run(FakePlanner(BAD_1, ModelHTTPError(503, "gpt")), tmp_path)
    assert state["status"] == "best_effort" and len(state["attempts"]) == 1
    assert any("Stopping (" in line and "503" in line for line in lines)


def test_every_provider_failing_is_reported_readably(tmp_path):
    from pydantic_ai.exceptions import FallbackExceptionGroup

    failure = FallbackExceptionGroup(
        "all failed", [ModelHTTPError(500, "a"), ModelHTTPError(529, "b")]
    )
    state, _ = run(FakePlanner(failure), tmp_path)
    assert state["status"] == "error" and "every provider failed" in state["error"]


# ---- budgets -------------------------------------------------------------------------------------


def test_the_model_call_budget_stops_the_repair_loop(tmp_path):
    config = Settings(_env_file=None, max_llm_calls=4)  # the guard uses 1, the first plan 3
    planner = FakePlanner(BAD_1, GOOD)
    state, lines = run(planner, tmp_path, config=config)
    assert state["status"] == "best_effort" and len(planner.calls) == 1
    assert any("budget of 4 model calls is used up" in line for line in lines)


def test_the_time_budget_stops_the_repair_loop(tmp_path):
    clock = Clock()
    planner = FakePlanner(BAD_1, GOOD, clock=clock, seconds=70)
    state, lines = run(planner, tmp_path, clock=clock)
    assert state["status"] == "best_effort" and len(planner.calls) == 1
    assert any("60s time budget is used up" in line for line in lines)


def test_the_token_budget_stops_the_repair_loop(tmp_path):
    config = Settings(_env_file=None, max_total_tokens=1000)
    planner = FakePlanner(BAD_1, GOOD, tokens=(900, 200))
    state, lines = run(planner, tmp_path, config=config)
    assert state["status"] == "best_effort" and len(planner.calls) == 1
    assert any("1,000 tokens is used up" in line for line in lines)


def test_the_tool_call_budget_stops_the_repair_loop(tmp_path):
    config = Settings(_env_file=None, max_tool_calls=5)
    planner = FakePlanner(BAD_1, GOOD, tool_calls=5)
    state, _ = run(planner, tmp_path, config=config)
    assert state["status"] == "best_effort" and len(planner.calls) == 1


def test_the_planner_gets_only_the_remaining_budget(tmp_path):
    planner = FakePlanner(BAD_1, GOOD, requests=3, tool_calls=4, tokens=(1000, 200))
    run(planner, tmp_path)
    first, second = (c["limits"] for c in planner.calls)
    assert isinstance(first, UsageLimits)
    assert (first.request_limit, first.tool_calls_limit, first.total_tokens_limit) == (
        11,
        15,
        150_000,
    )
    assert (second.request_limit, second.tool_calls_limit, second.total_tokens_limit) == (
        11 - 3,
        15 - 4,
        150_000 - 1200,
    )


def test_each_planner_call_gets_a_timeout_that_shrinks(tmp_path):
    clock = Clock()
    planner = FakePlanner(BAD_1, GOOD, clock=clock, seconds=20)
    run(planner, tmp_path, clock=clock)
    first, second = (c["timeout"] for c in planner.calls)
    assert first == pytest.approx(60) and second == pytest.approx(40)


# ---- unity mode and progress ---------------------------------------------------------------------


def test_unity_mode_applies_then_verifies_the_rig(tmp_path):
    unity = FakeDelivery()
    state, lines = run(FakePlanner(GOOD), tmp_path, unity_mode=True, unity=unity)
    assert state["status"] == "success"
    assert len(unity.applied) == 1 and len(unity.verified) == 1
    assert unity.applied[0] == state["skeleton"] == unity.verified[0]
    assert (
        state["unity_result"].status == "applied"
        and "25 bones verified" in state["unity_result"].detail
    )
    text = "\n".join(lines)
    assert (
        "[unity] Delivering to Unity" in text
        and "[unity] apply: applied" in text
        and "[unity] verify: applied" in text
    )


def test_unity_is_not_touched_when_the_rig_was_not_asked_for_in_unity(tmp_path):
    unity = FakeDelivery()
    run(FakePlanner(GOOD), tmp_path, unity=unity)
    assert unity.applied == [] and unity.verified == []


def test_an_unavailable_unity_does_not_invalidate_the_rig(tmp_path):
    unity = FakeDelivery(
        apply_result=UnityResult(status="unavailable", detail="cannot reach the Unity MCP server")
    )
    state, _ = run(FakePlanner(GOOD), tmp_path, unity_mode=True, unity=unity)
    assert state["status"] == "success" and (tmp_path / "skeleton.json").exists()
    assert state["unity_result"].status == "unavailable"
    assert unity.verified == []


def test_a_failed_verification_is_reported_but_the_rig_still_succeeds(tmp_path):
    unity = FakeDelivery(
        verify_result=UnityResult(status="failed", detail="'hand_R' head is 0.0500 units off")
    )
    state, _ = run(FakePlanner(GOOD), tmp_path, unity_mode=True, unity=unity)
    assert state["status"] == "success" and state["unity_result"].status == "failed"
    assert "units off" in state["unity_result"].detail


def test_unity_mode_without_a_delivery_object_is_unavailable(tmp_path):
    state, _ = run(FakePlanner(GOOD), tmp_path, unity_mode=True)
    assert state["status"] == "success"
    assert (
        state["unity_result"].status == "unavailable"
        and "not configured" in state["unity_result"].detail
    )


def test_unity_gets_the_repaired_rig_not_a_failed_attempt(tmp_path):
    unity = FakeDelivery()
    state, _ = run(FakePlanner(BAD_1, GOOD), tmp_path, unity_mode=True, unity=unity)
    assert state["iteration"] == 2 and unity.applied[0].metadata.iterations == 2


def test_without_unity_mode_there_is_no_unity_result(tmp_path):
    state, _ = run(FakePlanner(GOOD), tmp_path)
    assert state["unity_result"] is None


def test_a_best_effort_rig_skips_unity(tmp_path):
    state, _ = run(FakePlanner(BAD_1), tmp_path, unity_mode=True)
    assert state["unity_result"].status == "skipped"


def test_progress_lines_follow_the_flow(tmp_path):
    _, lines = run(FakePlanner(BAD_1, GOOD), tmp_path)
    text = "\n".join(lines)
    for expected in (
        "[guard] Input guard (gpt-5.4-mini)", "[guard] accepted", "[plan 1/3] Planner (gpt-5.4-mini)",
        "-> list_vocabulary()", "[plan 1/3] done: 3 model calls", "[build] ", "[validate] attempt 1: FAILED",
        "mirror_coincident", "[plan 2/3] Repairing", "[validate] attempt 2: PASSED", "[export] wrote",
    ):  # fmt: skip
        assert expected in text, expected
    order = [
        text.index(k)
        for k in (
            "[guard]",
            "[plan 1/3]",
            "[validate] attempt 1",
            "[plan 2/3]",
            "[validate] attempt 2",
            "[export]",
        )
    ]
    assert order == sorted(order)


# ---- the graph itself ----------------------------------------------------------------------------


def test_the_graph_has_the_nodes_and_edges_of_the_lld():
    app = build_graph(make_deps(FakePlanner(GOOD)))
    graph = app.get_graph()
    assert {
        "input_guard",
        "plan",
        "build",
        "validate",
        "export",
        "best_effort",
        "reject",
        "fail",
    } <= set(graph.nodes)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("build", "validate") in edges and ("validate", "plan") in edges
    assert ("validate", "export") in edges and ("validate", "best_effort") in edges
    assert ("input_guard", "reject") in edges and ("plan", "best_effort") in edges
    assert ("export", "unity_apply") in edges and ("unity_apply", "unity_verify") in edges
    assert ("export", "__end__") in edges and ("unity_apply", "__end__") in edges


def test_the_graph_draws_as_mermaid():
    text = build_graph(make_deps(FakePlanner(GOOD))).get_graph().draw_mermaid()
    assert "validate" in text and "best_effort" in text


def test_a_checkpointer_saves_the_final_state(tmp_path):
    saver = MemorySaver()
    app = build_graph(make_deps(FakePlanner(BAD_1, GOOD)), saver)
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": 60}
    app.invoke(initial_state("a knight", None, False, str(tmp_path), "t"), config)
    saved = app.get_state(config).values
    assert saved["status"] == "success" and saved["iteration"] == 2
    assert len(list(app.get_state_history(config))) > 5


def test_the_state_is_json_friendly_at_the_edges(tmp_path):
    state, _ = run(FakePlanner(GOOD), tmp_path)
    json.dumps(
        {
            "status": state["status"],
            "output_path": state["output_path"],
            "usage": state["usage"].model_dump(),
        }
    )
