"""evals/runner.py and evals/run.py (Phase H4): the real graph, with scripted fakes for the models."""

import dataclasses
import functools
import json

import pytest

from evals import run as run_module
from evals.golden import GoldenCase
from evals.records import RECORDS_FILE, load_records
from evals.run import main
from evals.runner import run_case, run_guard_case, run_suite
from graph_helpers import BAD_1, BAD_2, GOOD, FakeDelivery, FakePlanner, make_deps
from rig_agent.schemas.guardrail import GuardResult

KNIGHT = GoldenCase(id="knight", category="standard", prompt="a chibi knight")


def run(planner, tmp_path, **kw):
    guard = kw.pop("guard", None)
    unity = kw.pop("delivery", None)
    extra = {"guard": guard} if guard else {}

    def factory():
        return make_deps(planner, unity=unity, **extra)

    return run_case(KNIGHT, 1, deps_factory=factory, out_root=tmp_path, **kw)


def test_a_successful_run_is_recorded(tmp_path):
    record = run(FakePlanner(GOOD), tmp_path)
    assert record.status == "success" and record.final_iteration == 1
    assert len(record.attempts) == 1 and record.attempts[0].passed
    assert (
        record.attempts[0].bone_count
        and record.attempts[0].metrics["required_bone_coverage"] == 1.0
    )
    assert (record.input_tokens, record.output_tokens, record.tool_calls) == (1000, 200, 2)
    assert record.guard_accepted and record.guard_category == "ok"
    assert record.model.startswith("openai:")
    assert (tmp_path / "rigs" / "knight__1" / "skeleton.json").is_file()
    assert record.rig_dir == str(tmp_path / "rigs" / "knight__1")


def test_a_repaired_run_keeps_every_attempt(tmp_path):
    record = run(FakePlanner(BAD_1, GOOD), tmp_path)
    assert [a.passed for a in record.attempts] == [False, True]
    assert record.attempts[0].error_codes and record.final_iteration == 2
    assert record.first is record.attempts[0] and record.final is record.attempts[1]


def test_best_effort_points_at_the_attempt_it_delivered(tmp_path):
    record = run(FakePlanner(BAD_2, BAD_1, BAD_2), tmp_path)
    assert record.status == "best_effort"
    assert record.final_iteration == 2  # the attempt with the fewest errors


def test_schema_retries_are_attached_to_their_attempt(tmp_path):
    inner = FakePlanner(BAD_1, GOOD)
    calls = []

    def planner(*args, **kwargs):
        result = inner(*args, **kwargs)
        calls.append(result)
        retries = ("front view needs A_pose",) if len(calls) == 1 else ()
        return dataclasses.replace(result, output_retries=retries)

    record = run(planner, tmp_path)
    assert record.attempts[0].output_retries == ["front view needs A_pose"]
    assert record.attempts[1].output_retries == []


def test_a_rejected_run_has_no_attempts_and_no_rig(tmp_path):
    horse = GuardResult(accepted=False, category="non_humanoid", reason="not a person")
    record = run(FakePlanner(GOOD), tmp_path, guard=horse)
    assert record.status == "rejected" and record.attempts == []
    assert record.guard_category == "non_humanoid" and record.rig_dir is None
    assert record.final is None and record.view is None


def test_a_crash_is_recorded_not_raised(tmp_path):
    record = run(FakePlanner(RuntimeError("provider exploded")), tmp_path)
    assert record.status == "error" and "provider exploded" in (record.error or "")


def test_unity_status_is_recorded_only_when_asked(tmp_path):
    assert run(FakePlanner(GOOD), tmp_path).unity_status is None
    delivered = run(FakePlanner(GOOD), tmp_path, delivery=FakeDelivery(), unity=True)
    assert delivered.unity_status == "applied"


def test_run_suite_runs_each_case_k_times_and_reports_each_record(tmp_path):
    seen = []
    other = GoldenCase(id="other", category="standard", prompt="an elf")
    records = run_suite(
        [KNIGHT, other],
        2,
        functools.partial(
            run_case, deps_factory=lambda: make_deps(FakePlanner(GOOD)), out_root=tmp_path
        ),
        seen.append,
    )
    assert [(r.case_id, r.run) for r in records] == [
        ("knight", 1),
        ("knight", 2),
        ("other", 1),
        ("other", 2),
    ]
    assert seen == records


# ---- the command line ---------------------------------------------------------------------------


def offline(argv, tmp_path, planner=GOOD):
    return main(
        [*argv, "--out", str(tmp_path)], deps_factory=lambda: make_deps(FakePlanner(planner))
    )


def only_folder(tmp_path):
    (folder,) = [p for p in tmp_path.iterdir() if p.is_dir()]
    return folder


def test_main_writes_records_metrics_and_report(tmp_path, capsys):
    assert offline(["--case", "std_villager", "--case", "adv_horse", "--k", "2"], tmp_path) == 0
    folder = only_folder(tmp_path)
    records = load_records(folder)
    assert [(r.case_id, r.run) for r in records] == [
        ("std_villager", 1),
        ("std_villager", 2),
        ("adv_horse", 1),
        ("adv_horse", 2),
    ]
    metrics = {m["id"]: m for m in json.loads((folder / "metrics.json").read_text())}
    assert metrics["Q9 recall"]["value"] == 0.0  # the fake guard accepts the horse
    report = (folder / "report.md").read_text()
    assert "`adv_horse` run 1 (adversarial): should be rejected" in report
    out = capsys.readouterr().out
    assert "[4/4] adv_horse #2: success" in out and "target(s) missed" in out


def test_rescore_recomputes_the_same_metrics_without_running_anything(tmp_path, capsys):
    offline(["--category", "ambiguous", "--k", "1"], tmp_path)
    folder = only_folder(tmp_path)
    before = (folder / "metrics.json").read_text()
    (folder / "metrics.json").unlink()
    assert main(["--rescore", str(folder)]) == 0  # no deps_factory: would be live if it ran
    assert (folder / "metrics.json").read_text() == before


def test_rescore_with_prices_fills_in_the_cost(tmp_path):
    offline(["--case", "std_villager", "--k", "1"], tmp_path)
    folder = only_folder(tmp_path)
    main(["--rescore", str(folder), "--usd-per-mtok-in", "1", "--usd-per-mtok-out", "2"])
    metrics = {m["id"]: m for m in json.loads((folder / "metrics.json").read_text())}
    assert metrics["Q12 cost"]["value"] == pytest.approx((1000 * 1 + 200 * 2) / 1e6)


def test_render_draws_every_delivered_rig(tmp_path):
    pytest.importorskip("PIL")
    offline(["--case", "std_villager", "--k", "1", "--render"], tmp_path)
    assert (only_folder(tmp_path) / "rigs" / "std_villager__1" / "skeleton.png").is_file()


def test_a_live_run_is_never_started_non_interactively_without_yes(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--case", "std_villager", "--out", str(tmp_path)])  # stdin is not a tty in pytest
    assert exc.value.code == 2
    assert not any(tmp_path.iterdir())  # nothing was created, nothing was called


@pytest.mark.parametrize(
    "argv",
    [
        ["--k", "0"],
        ["--case", "no_such_case"],
        ["--usd-per-mtok-in", "1"],
        ["--category", "adversarial", "--case", "std_villager"],  # both filters: nothing matches
    ],
)
def test_bad_arguments_exit_2(argv, tmp_path):
    with pytest.raises(SystemExit) as exc:
        offline(argv, tmp_path)
    assert exc.value.code == 2


def test_rescore_of_a_folder_without_records_exits_2(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--rescore", str(tmp_path)])
    assert exc.value.code == 2
    assert not (tmp_path / RECORDS_FILE).exists()


def test_a_full_run_records_which_guard_model_decided(tmp_path):
    assert run(FakePlanner(GOOD), tmp_path).guard_model == "openai:gpt-5.4-mini"


# ---- guard only ---------------------------------------------------------------------------------


def fake_guard(text):
    """Rejects anything with a four-legged animal in it, accepts the rest."""
    if any(word in text for word in ("horse", "centaur", "spider")):
        return GuardResult(accepted=False, category="non_humanoid", reason="not a person")
    return GuardResult(accepted=True, category="ok", reason="a person")


def test_a_guard_run_records_only_the_guards_decision():
    accepted = run_guard_case(KNIGHT, 1, check=fake_guard, label="openai:nano")
    assert (accepted.mode, accepted.status, accepted.guard_category) == ("guard", "accepted", "ok")
    assert accepted.attempts == [] and accepted.model == accepted.guard_model == "openai:nano"
    horse = GoldenCase(id="h", category="adversarial", prompt="rig a horse")
    rejected = run_guard_case(horse, 1, check=fake_guard, label="x")
    assert (rejected.status, rejected.guard_category) == ("rejected", "non_humanoid")


def test_a_guard_crash_is_recorded(tmp_path):
    def broken(text):
        raise RuntimeError("rate limited")

    record = run_guard_case(KNIGHT, 1, check=broken, label="x")
    assert record.status == "error" and "rate limited" in (record.error or "")


def test_guard_only_reports_only_the_guardrail_metrics(tmp_path, capsys):
    argv = ["--guard-only", "--category", "adversarial", "--category", "accessory", "--k", "2"]
    assert main([*argv, "--out", str(tmp_path)], guard_check=fake_guard) == 0
    folder = only_folder(tmp_path)
    records = load_records(folder)
    assert len(records) == 34 and {r.mode for r in records} == {"guard"}
    metrics = {m["id"]: m for m in json.loads((folder / "metrics.json").read_text())}
    assert set(metrics) == {"Q9 recall", "Q9 precision", "Q9 clamp", "Q9 false-reject"}
    # the fake guard catches horse, centaur and spider (3 of 6 reject cases), and never a valid one
    assert metrics["Q9 recall"]["value"] == pytest.approx(0.5)
    assert metrics["Q9 false-reject"]["value"] == 0.0
    assert metrics["Q9 clamp"]["value"] == 1.0  # accepted: the planner's limits would clamp it
    report = (folder / "report.md").read_text()
    assert (
        "Mode: guard only" in report
        and "`adv_poem` run 1 (adversarial): should be rejected" in report
    )
    assert "`acc_" not in report  # accepted valid prompts are not failures
    assert "adv_horse #1: rejected (non_humanoid" in capsys.readouterr().out


def test_guard_only_rescores_to_the_same_metrics(tmp_path):
    main(
        ["--guard-only", "--category", "adversarial", "--k", "1", "--out", str(tmp_path)],
        guard_check=fake_guard,
    )
    folder = only_folder(tmp_path)
    before = (folder / "metrics.json").read_text()
    assert main(["--rescore", str(folder)]) == 0
    assert (folder / "metrics.json").read_text() == before


@pytest.mark.parametrize("flag", ["--render", "--unity"])
def test_guard_only_makes_no_rigs_to_render_or_deliver(flag, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--guard-only", flag, "--out", str(tmp_path)], guard_check=fake_guard)
    assert exc.value.code == 2


def test_a_live_guard_only_run_also_needs_yes_non_interactively(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--guard-only", "--out", str(tmp_path)])
    assert exc.value.code == 2 and not any(tmp_path.iterdir())


def test_the_guard_model_can_be_swapped_without_touching_the_settings(monkeypatch):
    monkeypatch.setattr(run_module.settings, "openai_api_key", "sk-test")
    before = run_module.settings.guard_model
    check, label = run_module._live_guard("gpt-5.4-mini")
    assert label == "openai:gpt-5.4-mini"
    assert run_module.settings.guard_model == before  # the global settings are untouched
    assert check.keywords["agent"].model.model_name == "gpt-5.4-mini"
