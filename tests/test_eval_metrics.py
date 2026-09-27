"""evals/metrics (Phase H4): per-run expectation checks and Q1-Q13, on hand-made run records so
every expected number can be worked out by hand."""

import json

import pytest

from evals.golden import Expected, GoldenCase
from evals.metrics.expectations import check_run
from evals.metrics.quantitative import Prices, Target, compute_metrics
from evals.records import AttemptRec, RunRecord
from evals.report import fmt, render_report, write_results
from rig_agent.schemas.rig_spec import RigSpec

FRONT = {
    "character_summary": "a chibi knight",
    "style": "chibi",
    "preset": "chibi",
    "view": "front",
    "rest_pose": "A_pose",
    "assumptions": ["front view by default"],
}
SIDE = dict(FRONT, view="side", rest_pose="side_neutral")
REALISTIC = dict(FRONT, preset="realistic", style="realistic")
GOOD_METRICS = {
    "required_bone_coverage": 1.0,
    "joint_connectivity": 1.0,
    "symmetry_error": 0.0,
    "proportion_error": 0.0,
}


def attempt(spec=FRONT, iteration=1, passed=True, metrics=None, errors=(), bones=15, retries=()):
    return AttemptRec(
        iteration=iteration,
        spec=RigSpec.model_validate(spec),
        passed=passed,
        issue_codes=list(errors),
        error_codes=list(errors),
        metrics=GOOD_METRICS if metrics is None else metrics,
        bone_count=bones,
        output_retries=list(retries),
    )


def record(case_id, category="standard", status="success", attempts=None, final=None, run=1, **kw):
    attempts = (
        [attempt()] if attempts is None and status in ("success", "best_effort") else attempts
    )
    attempts = attempts or []
    if final is None and attempts:
        final = attempts[-1].iteration
    guard = kw.pop("guard", "ok" if status != "rejected" else "non_humanoid")
    return RunRecord(
        case_id=case_id,
        category=category,
        run=run,
        prompt="p",
        view_given=None,
        model="openai:test",
        status=status,
        guard_accepted=guard == "ok",
        guard_category=guard,
        attempts=attempts,
        final_iteration=final,
        **kw,
    )


def case(id, category="standard", **expect):
    return GoldenCase(id=id, category=category, prompt="p", expect=Expected(**expect))


def by_id(metrics):
    return {m.id: m for m in metrics}


# ---- check_run ----------------------------------------------------------------------------------


def test_a_rejection_must_have_one_of_the_expected_categories():
    c = case("horse", "adversarial", outcome="reject", categories=("non_humanoid",))
    assert check_run(record("horse", status="rejected"), c).outcome_ok
    wrong = check_run(record("horse", status="rejected", guard="off_topic"), c)
    assert not wrong.outcome_ok and "rejected as off_topic" in wrong.failures[0]
    accepted = check_run(record("horse"), c)
    assert not accepted.outcome_ok and "should be rejected" in accepted.failures[0]


def test_reject_or_clamp_accepts_either():
    c = case("bones", "adversarial", outcome="reject_or_clamp")
    assert check_run(record("bones", status="rejected", guard="manipulation"), c).outcome_ok
    assert check_run(record("bones"), c).outcome_ok
    assert not check_run(record("bones", status="error", error="boom"), c).outcome_ok


def test_a_valid_prompt_that_was_rejected_is_a_failure():
    checks = check_run(record("v", status="rejected"), case("v"))
    assert not checks.outcome_ok and "valid request" in checks.failures[0]


def test_view_proportion_bone_and_assumption_checks():
    c = case(
        "x", view="side", proportions={"heads_tall": (6.5, 8.5)}, bones=(14, 20), assumption=True
    )
    checks = check_run(record("x", attempts=[attempt(FRONT, bones=30)]), c)  # chibi, front
    assert checks.view_ok is False and checks.proportions_ok is False and checks.bones_ok is False
    assert checks.assumption_ok is True
    assert any("view: expected side" in f for f in checks.failures)
    assert any(f.startswith("heads_tall 3 not in [6.5, 8.5]") for f in checks.failures)


def test_extras_f1_is_checked_on_the_delivered_spec():
    spec = dict(
        FRONT,
        extra_bones=[
            {
                "name": "extra_ponytail",
                "parent": "head",
                "direction_deg": -120,
                "length_ratio": 0.2,
                "mirror": True,
            }
        ],
    )
    checks = check_run(
        record("a", attempts=[attempt(spec)]), case("a", extras={"hair": 2, "cloth": 1})
    )
    assert checks.extras_f1 == pytest.approx(0.8)  # precision 1, recall 2/3
    assert "expected cloth x1, hair x2; got hair x2" in checks.failures[0]


def test_unchecked_attributes_stay_none():
    checks = check_run(record("x"), case("x"))
    assert (checks.view_ok, checks.proportions_ok, checks.extras_f1) == (None, None, None)
    assert checks.failures == ()


# ---- compute_metrics ----------------------------------------------------------------------------


def test_q1_counts_first_attempts_the_schema_sent_back():
    cases = {"a": case("a"), "b": case("b")}
    runs = [record("a"), record("b", attempts=[attempt(retries=["bad pose"])])]
    assert by_id(compute_metrics(runs, cases))["Q1"].value == 0.5


def test_q2_is_over_valid_prompts_only_and_counts_a_false_rejection():
    cases = {"a": case("a"), "b": case("b"), "h": case("h", "adversarial", outcome="reject")}
    runs = [record("a"), record("b", status="rejected"), record("h", status="rejected")]
    q2 = by_id(compute_metrics(runs, cases))["Q2"]
    assert (q2.value, q2.n) == (0.5, 2)


def test_q3_to_q5_on_first_attempts_see_an_unbuildable_first_spec():
    unbuildable = attempt(iteration=1, passed=False, metrics={}, errors=["unbuildable"], bones=None)
    runs = [record("a", attempts=[unbuildable, attempt(iteration=2)]), record("b")]
    m = by_id(compute_metrics(runs, {"a": case("a"), "b": case("b")}))
    assert m["Q3"].value == 1.0 and m["Q4"].value == 1.0  # the delivered rigs are fine
    assert m["Q3 first"].value == 0.5 and m["Q4 first"].value == 0.5 and m["Q5 first"].value == 0.5


def test_q6b_is_side_view_only():
    bad_depth = dict(GOOD_METRICS, depth_order_correct=0.0)
    runs = [
        record("s1", attempts=[attempt(SIDE, metrics=dict(GOOD_METRICS, depth_order_correct=1.0))]),
        record("s2", attempts=[attempt(SIDE, metrics=bad_depth)]),
        record("f"),
    ]
    q6b = by_id(compute_metrics(runs, {i: case(i) for i in ("s1", "s2", "f")}))["Q6b"]
    assert (q6b.value, q6b.n) == (0.5, 2)


def test_metrics_are_also_split_by_view():
    runs = [record("f"), record("s", attempts=[attempt(SIDE, retries=["x"])])]
    q1 = by_id(compute_metrics(runs, {"f": case("f"), "s": case("s")}))["Q1"]
    assert q1.by_view == {"front": 1.0, "side": 0.0}


def test_q8_view_style_and_extras():
    cases = {
        "v": case("v", "view_selection", view="side"),
        "st": case("st", "stylized", proportions={"heads_tall": (None, 4.0)}),
        "md": case("md", "modifier", proportions={"leg_ratio": (0.51, None)}),
        "ac": case("ac", "accessory", extras={}),
    }
    runs = [record("v"), record("st"), record("md"), record("ac")]
    m = by_id(compute_metrics(runs, cases))
    assert m["Q8 view"].value == 0.0 and m["Q8 style"].value == 1.0  # chibi is <= 4 heads
    assert m["Q8 modifier"].value == 0.0 and m["Q8 extras"].value == 1.0
    assert m["Q8 modifier"].target is None  # no LLD target: reported only


def test_q9_recall_precision_and_false_rejects():
    cases = {
        "h1": case("h1", "adversarial", outcome="reject", categories=("non_humanoid",)),
        "h2": case("h2", "adversarial", outcome="reject"),
        "ok": case("ok"),
        "ok2": case("ok2"),
    }
    runs = [
        record("h1", status="rejected"),
        record("h2"),  # a miss
        record("ok", status="rejected"),  # a false rejection
        record("ok2"),
    ]
    m = by_id(compute_metrics(runs, cases))
    assert (
        m["Q9 recall"].value == 0.5
        and m["Q9 recall"].detail == "1/2 also with the expected category"
    )
    assert m["Q9 precision"].value == 0.5
    assert m["Q9 false-reject"].value == 0.5 and m["Q9 false-reject"].passed is False


def test_q9b_counts_first_attempts_code_caught_and_names_the_rules():
    runs = [
        record(
            "a", attempts=[attempt(passed=False, errors=["unknown_bone"]), attempt(iteration=2)]
        ),
        record("b", attempts=[attempt(retries=["side view needs side_neutral"])]),
        record("c"),
        record("d"),
    ]
    q9b = by_id(compute_metrics(runs, {i: case(i) for i in "abcd"}))["Q9b"]
    assert q9b.value == 0.5
    assert "validator: unknown_bone x1" in q9b.detail and "schema: side view needs" in q9b.detail


def test_q10_needs_two_runs_of_a_case():
    single = by_id(compute_metrics([record("a")], {"a": case("a")}))
    assert single["Q10 bucket"].value is None and "k >= 2" in single["Q10 bucket"].detail


def test_q10_bucket_agreement_and_spread():
    cases = {"a": case("a"), "b": case("b")}
    runs = [
        record("a", run=1),
        record("a", run=2),  # both chibi: same bucket, no spread
        record("b", run=1),
        record("b", run=2, attempts=[attempt(REALISTIC)]),  # chibi vs realistic
    ]
    m = by_id(compute_metrics(runs, cases))
    assert m["Q10 bucket"].value == 0.5 and m["Q10 bucket"].n == 2
    assert m["Q10 sigma"].value > 0


def test_q11_mean_iterations_and_pass_at_k():
    runs = [
        record("a", attempts=[attempt(passed=False, errors=["x"]), attempt(iteration=2)]),
        record("b"),
    ]
    m = by_id(compute_metrics(runs, {"a": case("a"), "b": case("b")}))
    assert m["Q11"].value == 1.5 and m["Q11"].passed is True
    assert m["Q11 pass@1"].value == 0.5 and m["Q11 pass@3"].value == 1.0


def test_q12_percentiles_and_cost_only_with_prices():
    runs = [
        record(c, latency_s=s, input_tokens=1000, output_tokens=500)
        for c, s in (("a", 10.0), ("b", 20.0), ("c", 40.0))
    ]
    cases = {i: case(i) for i in "abc"}
    m = by_id(compute_metrics(runs, cases))
    assert m["Q12 p50 latency"].value == 20.0
    assert (
        m["Q12 p95 latency"].value == pytest.approx(38.0) and m["Q12 p95 latency"].passed is False
    )
    assert m["Q12 cost"].value is None and "--usd-per-mtok-in" in m["Q12 cost"].detail
    priced = by_id(compute_metrics(runs, cases, Prices(1.0, 4.0)))
    assert priced["Q12 cost"].value == pytest.approx((1000 * 1.0 + 500 * 4.0) / 1e6)


def test_q13_only_when_unity_was_asked_for():
    runs = [record("a"), record("b")]
    cases = {"a": case("a"), "b": case("b")}
    assert by_id(compute_metrics(runs, cases))["Q13"].value is None
    runs = [record("a", unity_status="applied"), record("b", unity_status="failed")]
    assert by_id(compute_metrics(runs, cases))["Q13"].value == 0.5


def test_records_of_cases_no_longer_in_the_golden_set_are_ignored():
    m = by_id(compute_metrics([record("gone"), record("a")], {"a": case("a")}))
    assert m["Q2"].n == 1


def test_targets():
    assert Target(">=", 0.95).met(0.95) and not Target(">=", 0.95).met(0.94)
    assert Target("<=", 0.01).met(0.01) and not Target("<=", 0.01).met(0.02)
    assert Target("=", 1.0).met(1.0) and not Target("=", 1.0).met(0.99)


# ---- the report ---------------------------------------------------------------------------------


def test_fmt():
    assert fmt(0.955, "%") == "95.5%" and fmt(None, "%") == "-"
    assert (
        fmt(12.34, "s") == "12.3s"
        and fmt(1234.0, "tokens") == "1,234"
        and fmt(0.01, "$") == "$0.0100"
    )


def test_the_report_lists_metrics_categories_and_failures(tmp_path):
    cases = {"a": case("a", view="side"), "h": case("h", "adversarial", outcome="reject")}
    runs = [record("a"), record("h", "adversarial")]
    metrics = compute_metrics(runs, cases)
    text = render_report(runs, cases, metrics, "Eval report: test")
    assert "| Q2 | Final validity rate | 100.0% |" in text
    assert "| adversarial | 1 | 1 | 0 | 0 | 0 | 0 |" in text
    assert "`a` run 1 (standard): view: expected side, got front" in text
    assert "`h` run 1 (adversarial): should be rejected" in text

    metrics_path, report_path = write_results(tmp_path, runs, cases, metrics, "t")
    saved = {m["id"]: m for m in json.loads(metrics_path.read_text())}
    assert saved["Q9 recall"]["passed"] is False and saved["Q13"]["value"] is None
    assert report_path.read_text().startswith("# t")


def test_accepted_by_the_guard_alone_counts_as_right_for_valid_and_clampable_prompts():
    guard_run = record("v", status="accepted", mode="guard")
    assert check_run(guard_run, case("v")).outcome_ok
    assert check_run(guard_run, case("v", "adversarial", outcome="reject_or_clamp")).outcome_ok
    assert not check_run(guard_run, case("v", "adversarial", outcome="reject")).outcome_ok
