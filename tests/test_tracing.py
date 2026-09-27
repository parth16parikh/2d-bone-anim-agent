"""observability.tracing: configure() is safe with no token, and traced_node() emits real spans
with the fields LLD 3.9 asks for (tool calls, tokens, latency, validation failures)."""

from graph_helpers import GOOD, FakePlanner, make_deps
from rig_agent.graph.build_graph import run_rig
from rig_agent.observability import tracing
from rig_agent.observability.tracing import configure, traced_node


def spans(capfire):
    return capfire.exporter.exported_spans_as_dict(parse_json_attributes=True)


def by_node(capfire, name):
    return [s for s in spans(capfire) if s["attributes"].get("node") == name]


# ---- configure() -----------------------------------------------------------------------------


def test_configure_is_safe_with_no_token_and_idempotent(monkeypatch):
    monkeypatch.setattr(tracing, "_configured", False)
    monkeypatch.setattr(tracing.settings, "logfire_token", None)
    configure()
    configure()  # a second call must not re-configure or raise
    assert tracing._configured is True


def test_a_node_can_be_wrapped_and_run_before_configure_is_ever_called():
    """Most of this test suite never calls configure() at all; that must stay harmless."""

    def node(state):
        return {"status": "success"}

    assert traced_node("export", node)({}) == {"status": "success"}


# ---- traced_node(): the graph really is traced ------------------------------------------------


def test_every_node_that_ran_gets_its_own_named_span(capfire, tmp_path):
    run_rig("a chibi knight", deps=make_deps(FakePlanner(GOOD)), out_dir=str(tmp_path))
    names = {s["attributes"]["node"] for s in spans(capfire)}
    assert names == {"input_guard", "plan", "build", "validate", "export"}


def test_the_plan_span_carries_the_running_usage_totals(capfire, tmp_path):
    run_rig("a chibi knight", deps=make_deps(FakePlanner(GOOD)), out_dir=str(tmp_path))
    plan_span = by_node(capfire, "plan")[0]
    attrs = plan_span["attributes"]
    assert attrs["usage.requests"] >= 1
    assert attrs["usage.tool_calls"] == 2  # FakePlanner's default
    assert attrs["usage.total_tokens"] == 1200  # FakePlanner's default tokens (1000, 200)


def test_the_validate_span_carries_the_validation_result(capfire, tmp_path):
    run_rig("a chibi knight", deps=make_deps(FakePlanner(GOOD)), out_dir=str(tmp_path))
    validate_span = by_node(capfire, "validate")[0]
    attrs = validate_span["attributes"]
    assert attrs["validation.passed"] is True
    assert attrs["validation.errors"] == 0


def test_a_rejected_request_is_traced_too(capfire, tmp_path):
    from rig_agent.schemas.guardrail import GuardResult

    horse = GuardResult(accepted=False, category="non_humanoid", reason="not a person")
    run_rig("a horse", deps=make_deps(FakePlanner(GOOD), guard=horse), out_dir=str(tmp_path))
    guard_span = by_node(capfire, "input_guard")[0]
    assert guard_span["attributes"]["guard.accepted"] is False
    assert guard_span["attributes"]["guard.category"] == "non_humanoid"
    assert by_node(capfire, "reject")[0]["attributes"]["status"] == "rejected"


def test_the_export_span_records_the_final_status(capfire, tmp_path):
    run_rig("a chibi knight", deps=make_deps(FakePlanner(GOOD)), out_dir=str(tmp_path))
    assert by_node(capfire, "export")[0]["attributes"]["status"] == "success"


def test_wrapping_does_not_change_what_the_node_returns():
    """traced_node is a pure passthrough: the graph's own behaviour must be unaffected."""
    calls = []

    def node(state):
        calls.append(state)
        return {"iteration": state.get("iteration", 0) + 1}

    wrapped = traced_node("plan", node)
    assert wrapped({"iteration": 2}) == {"iteration": 3}
    assert calls == [{"iteration": 2}]
