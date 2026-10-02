"""evals/anim (Goal 2, M4): the animation golden set, checks, metrics, runner and CLI, offline."""

import json
from collections import Counter

import pytest

from evals.anim.golden import (
    ANIM_CATEGORIES,
    AnimCase,
    AnimExpected,
    direction_ok,
    load_anim_golden,
    select_cases,
)
from evals.anim.metrics import check_anim_run, compute_anim_metrics
from evals.anim.records import AnimAttemptRec, AnimRunRecord, load_anim_records
from evals.anim.run import main
from evals.anim.runner import run_anim_case
from graph_helpers import Clock
from rig_agent.agent.anim_planner import AnimPlanResult
from rig_agent.agent.anim_prompt import build_anim_system_prompt
from rig_agent.config import Settings
from rig_agent.graph.anim_graph import AnimDeps
from rig_agent.guardrails.anim_guard import build_anim_guard_prompt
from rig_agent.schemas.animation import CLIP_VIEWS, AnimationSpec
from rig_agent.schemas.guardrail import GuardResult

GOLDEN = load_anim_golden()
RIGS = GOLDEN.build_rigs()


# ---- the golden set --------------------------------------------------------------------------------


def test_the_set_covers_every_category():
    assert Counter(c.category for c in GOLDEN.cases) == {
        "neutral": 6, "mood": 10, "modifier": 8, "backflip": 5,
        "view_rule": 5, "unsupported": 6, "adversarial": 3,
    }  # fmt: skip
    assert set(ANIM_CATEGORIES) == {c.category for c in GOLDEN.cases}


def test_the_test_rigs_are_built_without_a_model_and_cover_both_views():
    assert {name: rig.view for name, rig in RIGS.items()} == {
        "knight": "side", "chibi_knight": "side", "elf": "front", "mage": "front",
    }  # fmt: skip
    assert RIGS["chibi_knight"].bones[3].length != RIGS["knight"].bones[3].length  # a real chibi


def test_no_prompt_copies_the_planner_or_guard_examples():
    """The planner copies its examples verbatim, so a copied prompt would measure memory."""
    prompts = build_anim_system_prompt() + build_anim_guard_prompt()
    assert [c.id for c in GOLDEN.cases if f'"{c.prompt}"' in prompts] == []


def test_expectations_fit_the_rig():
    for case in GOLDEN.cases:
        view = RIGS[case.rig].view
        expect = case.expect
        if expect.outcome == "accept":
            assert view in CLIP_VIEWS[expect.clip], case.id  # an accepted clip must be playable
        if expect.outcome == "wrong_view":
            assert view not in CLIP_VIEWS[expect.clip], case.id
        if "lean_deg" in expect.directions:
            assert view == "side", case.id  # lean does nothing in the front view


def test_direction_semantics():
    assert direction_ok("speed", 0.7, "down") and not direction_ok("speed", 0.97, "down")
    assert direction_ok("bounce", 1.3, "up") and not direction_ok("bounce", 1.03, "up")
    assert direction_ok("stride", 1.1, "same") and not direction_ok("stride", 1.3, "same")
    assert direction_ok("lean_deg", 8, "up") and direction_ok("lean_deg", -3, "down")
    assert direction_ok("lean_deg", 2, "same") and not direction_ok("lean_deg", 1, "up")


def test_the_loader_refuses_inconsistent_expectations():
    with pytest.raises(ValueError, match="no clip"):
        AnimExpected(outcome="reject", clip="walk")
    with pytest.raises(ValueError, match="names the clip"):
        AnimExpected(outcome="wrong_view")
    with pytest.raises(ValueError, match="unknown setting"):
        AnimExpected(clip="walk", directions={"swagger": "up"})
    with pytest.raises(ValueError, match="categories"):
        AnimExpected(clip="walk", categories=("off_topic",))


def test_select_cases():
    assert {c.category for c in select_cases(GOLDEN.cases, categories=["backflip"])} == {"backflip"}
    with pytest.raises(ValueError, match="no such case"):
        select_cases(GOLDEN.cases, ids=["nope"])


# ---- checks and metrics on hand-made records ---------------------------------------------------------


def spec(clip="walk", **kw):
    return AnimationSpec(clip=clip, style="t", **kw)


def record(case_id, status="success", planned=None, final=None, **kw):
    case = GOLDEN.by_id()[case_id]
    final = final if final is not None else planned
    attempts = (
        [
            AnimAttemptRec(
                iteration=1, spec=final, passed=True, error_codes=[], metrics={"max_foot_slip": 0.0}
            )
        ]
        if status == "success" and final
        else []
    )
    defaults = {
        "case_id": case_id, "category": case.category, "run": 1, "prompt": case.prompt, "rig": case.rig,
        "rig_view": RIGS[case.rig].view, "model": "openai:test", "guard_model": "openai:test",
        "status": status, "planned": planned, "final_spec": final, "plan_calls": 1 if planned else 0,
        "attempts": attempts, "final_iteration": 1 if attempts else None, "clip_written": status == "success",
        "guard_accepted": status != "rejected", "guard_category": kw.pop("guard_category", "ok"),
    }  # fmt: skip
    return AnimRunRecord(**(defaults | kw))


def test_a_mood_case_checks_clip_and_directions():
    case = GOLDEN.by_id()["mood_exhausted"]  # walk, speed down, bounce down
    good = check_anim_run(record("mood_exhausted", planned=spec(speed=0.7, bounce=0.5)), case)
    assert good.outcome_ok and good.clip_ok and all(ok for _, ok in good.directions)
    bad = check_anim_run(record("mood_exhausted", planned=spec("run", speed=1.2, bounce=0.5)), case)
    assert bad.clip_ok is False and ("speed", False) in bad.directions
    assert any("the planner chose run" in f for f in bad.failures)


def test_a_wrong_view_case_must_stop_without_swapping_or_writing():
    case = GOLDEN.by_id()["view_walk_front"]
    stopped = record(
        "view_walk_front",
        status="error",
        planned=spec("walk"),
        stopped_for_view=True,
        clip_written=False,
    )
    assert check_anim_run(stopped, case).outcome_ok
    swapped = record("view_walk_front", planned=spec("idle"))  # an idle quietly delivered instead
    checks = check_anim_run(swapped, case)
    assert not checks.outcome_ok and checks.clip_ok is False


def test_refusals_need_the_right_category():
    case = GOLDEN.by_id()["uns_jump"]
    assert check_anim_run(
        record("uns_jump", status="rejected", guard_category="unsupported_motion"), case
    ).outcome_ok
    assert not check_anim_run(
        record("uns_jump", status="rejected", guard_category="off_topic"), case
    ).outcome_ok
    assert not check_anim_run(record("uns_jump", planned=spec("run")), case).outcome_ok


def metric(metrics, id_):
    return next(m for m in metrics if m.id == id_)


def test_metrics_on_hand_made_records():
    cases = GOLDEN.by_id()
    runs = [
        record("mood_exhausted", planned=spec(speed=0.7, bounce=0.5)),  # all right
        record("mood_panic", planned=spec("run", speed=0.9)),  # speed should go up
        record(
            "view_walk_front",
            status="error",
            planned=spec("walk"),
            stopped_for_view=True,
            clip_written=False,
        ),
        record("uns_jump", status="rejected", guard_category="unsupported_motion"),
        record("neu_walk", status="rejected", guard_category="off_topic"),  # a false rejection
    ]
    m = compute_anim_metrics(runs, cases)
    assert metric(m, "A2").value == pytest.approx(2 / 3)  # 2 of the 3 accept runs succeeded
    assert metric(m, "A3").value == 1.0
    assert metric(m, "A4").value == pytest.approx(2 / 3)  # speed+bounce right, panic speed wrong
    assert metric(m, "A5 recall").value == 1.0
    assert metric(m, "A5 false-reject").value == pytest.approx(1 / 4)
    assert metric(m, "A6").value == 1.0
    assert metric(m, "A8 clip").value is None and "k >= 2" in metric(m, "A8 clip").detail
    assert metric(m, "A9 cost").value is None


def test_consistency_across_runs():
    cases = GOLDEN.by_id()
    runs = [
        record("mood_exhausted", run=1, planned=spec(speed=0.7, bounce=0.5)),
        record(
            "mood_exhausted", run=2, planned=spec(speed=1.1, bounce=0.5)
        ),  # speed verdict differs
        record("mood_panic", run=1, planned=spec("run", speed=1.4)),
        record("mood_panic", run=2, planned=spec("walk", speed=1.4)),  # a different clip
    ]
    m = compute_anim_metrics(runs, cases)
    assert metric(m, "A8 clip").value == 0.5
    assert metric(m, "A8 directions").value == pytest.approx(
        2 / 3
    )  # bounce agrees; both speeds differ


# ---- the runner and the command line, with rule-based fakes ------------------------------------------


REFUSE = (
    "jump",
    "attack",
    "front flip",
    "dance",
    "crawl",
    "skip",
    "joke",
    "ignore",
    "system prompt",
)


def fake_guard(text):
    if any(word in text for word in REFUSE):
        category = (
            "manipulation"
            if "ignore" in text or "prompt" in text
            else "off_topic"
            if "joke" in text
            else "unsupported_motion"
        )
        return GuardResult(accepted=False, category=category, reason="no", suggestion="a walk")
    return GuardResult(accepted=True, category="ok", reason="yes")


def fake_planner(description, skeleton, **kw):
    text = description.lower()
    clip = (
        "backflip" if "flip" in text or "somersault" in text
        else "run" if any(w in text for w in ("run", "dash", "jog"))
        else "idle" if any(w in text for w in ("idle", "standing", "breath", "fidget"))
        else "walk"
    )  # fmt: skip
    slow = any(w in text for w in ("slow", "exhausted", "elderly", "creep", "lazy", "asleep"))
    return AnimPlanResult(spec(clip, speed=0.7 if slow else 1.0), 2, 1, 900, 100)


def fake_deps():
    return AnimDeps(
        check_input=fake_guard, plan=fake_planner, clock=Clock(), config=Settings(_env_file=None)
    )


def test_run_case_records_success_view_stop_and_refusal(tmp_path):
    cases = GOLDEN.by_id()
    ok = run_anim_case(
        cases["mood_exhausted"], 1, rigs=RIGS, deps_factory=fake_deps, out_root=tmp_path
    )
    assert (
        ok.status == "success"
        and ok.planned.speed == 0.7
        and ok.clip_written
        and ok.final_iteration == 1
    )
    assert (tmp_path / "rigs" / "mood_exhausted__1" / "skeleton.json").is_file()
    stop = run_anim_case(
        cases["view_walk_front"], 1, rigs=RIGS, deps_factory=fake_deps, out_root=tmp_path
    )
    assert stop.stopped_for_view and not stop.clip_written and stop.planned.clip == "walk"
    refused = run_anim_case(
        cases["uns_jump"], 1, rigs=RIGS, deps_factory=fake_deps, out_root=tmp_path
    )
    assert refused.status == "rejected" and refused.plan_calls == 0


def test_the_whole_golden_set_runs_offline_and_rescores_identically(tmp_path, capsys):
    assert main(["--k", "1", "--out", str(tmp_path)], deps_factory=fake_deps) == 0
    (folder,) = list(tmp_path.iterdir())
    records = load_anim_records(folder)
    assert len(records) == len(GOLDEN.cases)
    saved = {m["id"]: m for m in json.loads((folder / "metrics.json").read_text())}
    assert saved["A5 recall"]["value"] == 1.0  # the fake guard refuses every refusal case
    assert saved["A6"]["value"] == 1.0  # every front-view walk/run/backflip stopped
    report = (folder / "report.md").read_text()
    assert "## Failed expectations" in report and "Animation eval report" in report
    before = (folder / "metrics.json").read_text()
    assert main(["--rescore", str(folder)]) == 0
    assert (folder / "metrics.json").read_text() == before
    assert "target(s) missed" in capsys.readouterr().out


def test_a_live_run_is_never_started_without_yes(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--case", "neu_walk", "--out", str(tmp_path)])
    assert exc.value.code == 2 and not any(tmp_path.iterdir())


def test_bad_arguments(tmp_path):
    for argv in (["--k", "0"], ["--case", "nope"], ["--usd-per-mtok-in", "1"]):
        with pytest.raises(SystemExit) as exc:
            main([*argv, "--out", str(tmp_path)], deps_factory=fake_deps)
        assert exc.value.code == 2
    assert isinstance(GOLDEN.cases[0], AnimCase)
