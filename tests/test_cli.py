import json
from pathlib import Path
from typing import ClassVar

import pytest

from rig_agent.cli import main
from rig_agent.export.json_exporter import load_report, load_skeleton

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SPECS = sorted(EXAMPLES.glob("*.json"))


def test_the_examples_exist():
    assert {p.name for p in SPECS} >= {
        "knight_side.json",
        "elf_front.json",
        "chibi_mage_front.json",
    }


@pytest.mark.parametrize("spec", SPECS, ids=[p.stem for p in SPECS])
def test_each_example_builds_a_valid_rig(spec, tmp_path, capsys):
    assert main(["build", "--spec", str(spec), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "PASSED" in out and str(tmp_path / "skeleton.json") in out
    skeleton = load_skeleton(tmp_path / "skeleton.json")
    assert load_report(tmp_path / "validation_report.json").passed
    assert [b.id for b in skeleton.bones] == list(range(len(skeleton.bones)))


def test_side_and_front_examples_differ_as_expected(tmp_path):
    main(["build", "--spec", str(EXAMPLES / "knight_side.json"), "--out", str(tmp_path / "s")])
    main(["build", "--spec", str(EXAMPLES / "elf_front.json"), "--out", str(tmp_path / "f")])
    side, front = (
        load_skeleton(tmp_path / "s/skeleton.json"),
        load_skeleton(tmp_path / "f/skeleton.json"),
    )
    assert (side.view, side.facing, front.view, front.facing) == ("side", "right", "front", None)
    assert {b.name for b in side.bones} >= {"toe_L", "extra_sword", "extra_cape_3"}


def test_prompt_is_recorded(tmp_path):
    main(
        [
            "build",
            "--spec",
            str(EXAMPLES / "elf_front.json"),
            "--out",
            str(tmp_path),
            "--prompt",
            "an elf",
        ]
    )
    assert load_skeleton(tmp_path / "skeleton.json").source_prompt == "an elf"


def test_default_output_directory_is_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["build", "--spec", str(EXAMPLES / "elf_front.json")]) == 0
    assert (tmp_path / "out" / "skeleton.json").exists()


def test_a_missing_spec_file_exits_with_2(tmp_path, capsys):
    assert main(["build", "--spec", str(tmp_path / "nope.json")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_an_invalid_spec_exits_with_2_and_says_why(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"character_summary": "x", "style": "s", "view": "side", "rest_pose": "A_pose"})
    )
    assert main(["build", "--spec", str(bad), "--out", str(tmp_path / "o")]) == 2
    err = capsys.readouterr().err
    assert "not a valid RigSpec" in err and "side_neutral" in err
    assert not (tmp_path / "o").exists()


def test_a_spec_that_cannot_be_built_exits_with_2(tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(
        json.dumps(
            {
                "character_summary": "x",
                "style": "s",
                "view": "front",
                "rest_pose": "A_pose",
                "base": {"heads_tall": 2.0, "leg_ratio": 0.6},
            }
        )
    )
    assert main(["build", "--spec", str(spec), "--out", str(tmp_path / "o")]) == 2
    assert "no room for a torso" in capsys.readouterr().err


def test_a_rig_that_fails_validation_still_writes_files_and_exits_with_1(tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({
        "character_summary": "x", "style": "s", "view": "front", "rest_pose": "A_pose",
        "extra_bones": [{"name": "extra_horn", "parent": "head", "direction_deg": 90, "length_ratio": 0.1, "mirror": True}],
    }))  # fmt: skip
    assert main(["build", "--spec", str(spec), "--out", str(tmp_path / "o")]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "mirror_coincident" in out
    assert not load_report(tmp_path / "o" / "validation_report.json").passed
    assert (tmp_path / "o" / "skeleton.json").exists()


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


# ---- plan ----------------------------------------------------------------------------------------

from pydantic_ai.exceptions import UnexpectedModelBehavior

from rig_agent.agent.planner import PlanResult
from rig_agent.llm import MissingApiKeyError
from rig_agent.schemas.guardrail import GuardResult
from rig_agent.schemas.rig_spec import RigSpec

ACCEPT = GuardResult(accepted=True, category="ok", reason="A humanoid request.")
KNIGHT = {
    "character_summary": "a chibi knight",
    "style": "chibi knight",
    "preset": "chibi",
    "view": "front",
    "rest_pose": "A_pose",
    "optional_bones": ["hands"],
}


def result_for(spec_data):
    return PlanResult(
        spec=RigSpec.model_validate(spec_data),
        requests=3,
        tool_calls=2,
        input_tokens=10,
        output_tokens=5,
    )


@pytest.fixture
def fake_llm(monkeypatch):
    calls = {}

    def fake_plan(description, view=None, **kw):
        calls["plan"] = (description, view)
        return result_for(KNIGHT)

    monkeypatch.setattr("rig_agent.cli.check_input", lambda text: ACCEPT)
    monkeypatch.setattr("rig_agent.cli.plan", fake_plan)
    return calls


def test_plan_prints_a_rigspec_that_build_accepts(fake_llm, tmp_path, capsys):
    assert main(["plan", "a chibi knight"]) == 0
    captured = capsys.readouterr()
    spec = RigSpec.model_validate_json(captured.out)
    assert spec.preset == "chibi" and fake_llm["plan"] == ("a chibi knight", None)
    assert "[3/3] Dry run: PASSED (0 errors, 0 warnings)" in captured.err

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(captured.out)
    assert main(["build", "--spec", str(spec_file), "--out", str(tmp_path / "rig")]) == 0
    assert load_report(tmp_path / "rig" / "validation_report.json").passed


def test_plan_writes_to_a_file_with_out(fake_llm, tmp_path, capsys):
    target = tmp_path / "knight.json"
    assert main(["plan", "a chibi knight", "--out", str(target)]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and f"written to {target}" in captured.err
    assert RigSpec.model_validate_json(target.read_text()).style == "chibi knight"


def test_plan_passes_the_view_flag(fake_llm):
    main(["plan", "a knight", "--view", "side"])
    assert fake_llm["plan"] == ("a knight", "side")


def test_plan_rejects_a_bad_view_flag():
    with pytest.raises(SystemExit) as excinfo:
        main(["plan", "a knight", "--view", "top"])
    assert excinfo.value.code == 2


def test_a_rejected_request_never_reaches_the_planner(monkeypatch, capsys):
    horse = GuardResult(
        accepted=False,
        category="non_humanoid",
        reason="A horse is not a humanoid.",
        suggestion="Describe a person.",
    )
    monkeypatch.setattr("rig_agent.cli.check_input", lambda text: horse)
    monkeypatch.setattr("rig_agent.cli.plan", lambda *a, **k: pytest.fail("planner must not run"))
    assert main(["plan", "a horse"]) == 1
    err = capsys.readouterr().err
    assert (
        "non_humanoid" in err
        and "A horse is not a humanoid." in err
        and "Describe a person." in err
    )


def test_a_missing_api_key_exits_with_2(monkeypatch, capsys):
    def no_key(text):
        raise MissingApiKeyError(
            "OPENAI_API_KEY is not set. Add it to the .env file in the project root."
        )

    monkeypatch.setattr("rig_agent.cli.check_input", no_key)
    assert main(["plan", "a knight"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_a_failed_model_run_exits_with_2(monkeypatch, capsys):
    def boom(*a, **k):
        raise UnexpectedModelBehavior("the model kept returning invalid output")

    monkeypatch.setattr("rig_agent.cli.check_input", lambda text: ACCEPT)
    monkeypatch.setattr("rig_agent.cli.plan", boom)
    assert main(["plan", "a knight"]) == 2
    assert "the model run failed" in capsys.readouterr().err


def test_a_spec_that_fails_the_dry_run_exits_with_1(monkeypatch, capsys):
    bad = dict(
        KNIGHT,
        extra_bones=[
            {
                "name": "extra_horn",
                "parent": "head",
                "direction_deg": 90,
                "length_ratio": 0.1,
                "mirror": True,
            }
        ],
    )
    monkeypatch.setattr("rig_agent.cli.check_input", lambda text: ACCEPT)
    monkeypatch.setattr("rig_agent.cli.plan", lambda *a, **k: result_for(bad))
    assert main(["plan", "a knight"]) == 1
    assert "Dry run: FAILED" in capsys.readouterr().err


def test_plan_prints_numbered_stages_with_models_and_timings(fake_llm, capsys):
    main(["plan", "a chibi knight"])
    err = capsys.readouterr().err
    assert "[1/3] Input guard (gpt-5.4-nano) ..." in err
    assert "[2/3] Planner (gpt-5.4-mini) ..." in err
    assert "3 model calls, 2 tool calls, 10 tokens in, 5 out" in err
    assert "[3/3] Dry run: PASSED" in err and "Finished in" in err
    assert err.index("[1/3]") < err.index("accepted in") < err.index("[2/3]") < err.index("[3/3]")


def test_a_rejection_still_reports_the_first_stage(monkeypatch, capsys):
    horse = GuardResult(accepted=False, category="non_humanoid", reason="A horse.")
    monkeypatch.setattr("rig_agent.cli.check_input", lambda text: horse)
    main(["plan", "a horse"])
    err = capsys.readouterr().err
    assert "[1/3] Input guard" in err and "not accepted (non_humanoid)" in err
    assert "[2/3]" not in err


# ---- build progress ------------------------------------------------------------------------------


def test_build_prints_numbered_stages_to_stderr(tmp_path, capsys):
    main(["build", "--spec", str(EXAMPLES / "knight_side.json"), "--out", str(tmp_path)])
    err = capsys.readouterr().err
    for stage in (
        "[1/4] Reading spec",
        "[2/4] Building the skeleton",
        "[3/4] Validating",
        "[4/4] Exporting",
    ):
        assert stage in err
    assert err.index("[1/4]") < err.index("[2/4]") < err.index("[3/4]") < err.index("[4/4]")
    assert "heroic preset, side view, side_neutral, 5 optional bone tokens, 2 extra chains" in err
    assert "25 bones (21 canonical, 4 extra)" in err
    assert "PASSED: 0 errors, 0 warnings" in err
    assert "connectivity 1.0000, symmetry error 0.0000, proportion error 0.0000" in err
    assert "wrote skeleton.json and validation_report.json" in err and "Finished in" in err


def test_build_keeps_the_result_summary_on_stdout(tmp_path, capsys):
    main(["build", "--spec", str(EXAMPLES / "elf_front.json"), "--out", str(tmp_path)])
    captured = capsys.readouterr()
    assert "[1/4]" not in captured.out and "Built 'a_tall_lanky_elf_archer" in captured.out
    assert "PASSED" in captured.out


def test_build_progress_stops_at_the_failing_stage(tmp_path, capsys):
    main(["build", "--spec", str(tmp_path / "nope.json"), "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err
    assert "[1/4] Reading spec" in err and "cannot read" in err and "[2/4]" not in err


def test_build_reports_failed_validation_in_the_stages(tmp_path, capsys):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({
        "character_summary": "x", "style": "s", "view": "front", "rest_pose": "A_pose",
        "extra_bones": [{"name": "extra_horn", "parent": "head", "direction_deg": 90, "length_ratio": 0.1, "mirror": True}],
    }))  # fmt: skip
    assert main(["build", "--spec", str(spec), "--out", str(tmp_path / "o")]) == 1
    err = capsys.readouterr().err
    assert "[3/4] Validating" in err and "FAILED: 1 errors" in err and "[4/4] Exporting" in err


# ---- run (the whole graph) -----------------------------------------------------------------------

from pydantic_ai.exceptions import UnexpectedModelBehavior as _Unexpected  # noqa: F401

from graph_helpers import BAD_1 as BAD_SPEC
from graph_helpers import GOOD as GOOD_SPEC
from graph_helpers import FakePlanner, make_deps


@pytest.fixture
def fake_graph(monkeypatch):
    """Replace the real models behind `run` with a scripted planner; returns it for inspection."""

    def install(*steps, guard=ACCEPT, **kw):
        planner = FakePlanner(*steps, **kw)

        def deps_with_progress(say=None, prefab=None):
            deps = make_deps(planner, guard=guard)
            if say:
                deps.say = say
            install.prefab_seen.append(prefab)
            return deps

        monkeypatch.setattr("rig_agent.cli.default_deps", deps_with_progress)
        return planner

    install.prefab_seen = []
    return install


def test_run_succeeds_end_to_end_and_prints_progress(fake_graph, tmp_path, capsys):
    fake_graph(GOOD_SPEC)
    assert main(["run", "a chibi knight", "--out", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "Status: success" in captured.out
    assert f"skeleton: {tmp_path / 'skeleton.json'}" in captured.out
    assert "report:" in captured.out and "validation_report.json" in captured.out
    for stage in ("[guard]", "[plan 1/3]", "[build]", "[validate] attempt 1: PASSED", "[export]"):
        assert stage in captured.err
    assert "Finished in" in captured.err and "1 attempt(s) (scores 1.00)" in captured.err
    assert load_report(tmp_path / "validation_report.json").passed


def test_run_repairs_and_reports_both_attempts(fake_graph, tmp_path, capsys):
    planner = fake_graph(BAD_SPEC, GOOD_SPEC)
    assert main(["run", "a chibi knight", "--out", str(tmp_path)]) == 0
    err = capsys.readouterr().err
    assert len(planner.calls) == 2 and "[plan 2/3] Repairing" in err
    assert "2 attempt(s) (scores 0.90, 1.00)" in err


def test_run_passes_the_view_and_unity_flags(fake_graph, tmp_path, capsys):
    planner = fake_graph(GOOD_SPEC)
    assert main(["run", "a knight", "--view", "side", "--unity", "--out", str(tmp_path)]) == 0
    assert planner.calls[0]["view"] == "side"
    assert "unity:    unavailable" in capsys.readouterr().out


def test_run_returns_1_for_a_best_effort_rig(fake_graph, tmp_path, capsys):
    fake_graph(BAD_SPEC)
    assert main(["run", "a knight", "--out", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "Status: best_effort" in out and "Not import-ready" in out and "mirror_coincident" in out
    assert (tmp_path / "skeleton.json").exists()


def test_run_returns_1_for_a_rejected_request(fake_graph, tmp_path, capsys):
    horse = GuardResult(
        accepted=False, category="non_humanoid", reason="A horse.", suggestion="Try a person."
    )
    planner = fake_graph(GOOD_SPEC, guard=horse)
    assert main(["run", "a horse", "--out", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "Status: rejected" in captured.out and planner.calls == []
    assert "non_humanoid" in captured.err and "Try a person." in captured.err


def test_run_returns_2_for_a_model_failure(fake_graph, tmp_path, capsys):
    fake_graph(UnexpectedModelBehavior("kept returning invalid output"))
    assert main(["run", "a knight", "--out", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "Status: error" in captured.out and "invalid output" in captured.err


def test_run_returns_2_without_an_api_key(monkeypatch, tmp_path, capsys):
    for name in ("openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(f"rig_agent.llm.settings.{name}", None)
    assert main(["run", "a knight", "--out", str(tmp_path)]) == 2
    assert "No API key is set" in capsys.readouterr().err


def test_run_needs_a_description():
    with pytest.raises(SystemExit) as excinfo:
        main(["run"])
    assert excinfo.value.code == 2


# ---- unity-apply and unity-check -----------------------------------------------------------------

from rig_agent.schemas.state import UnityResult as _UnityResult
from rig_agent.unity.delivery import BatchResult, RigOutcome


class _FakeUnityDelivery:
    result = _UnityResult(status="applied", detail="25 bones under RigAgent_Output/x")
    delivered: ClassVar[list] = []

    prefabs: ClassVar[list] = []
    batch: ClassVar[list] = []
    batch_result = None

    def __init__(self, *args, **kwargs):
        self.say = kwargs.get("say")
        type(self).prefabs.append(kwargs.get("prefab"))

    def deliver(self, skeleton):
        type(self).delivered.append(skeleton)
        if self.say:
            self.say("[unity] connected")
        return type(self).result

    def deliver_all(self, rigs):
        type(self).batch.append([r.name for r in rigs])
        return type(self).batch_result or BatchResult(
            status="applied", rigs=[RigOutcome(r.name, "applied", "20 bones") for r in rigs]
        )


@pytest.fixture
def fake_delivery(monkeypatch):
    _FakeUnityDelivery.delivered = []
    _FakeUnityDelivery.prefabs = []
    _FakeUnityDelivery.batch = []
    _FakeUnityDelivery.batch_result = None
    monkeypatch.setattr("rig_agent.cli.settings.unity_prefab_dir", "")
    monkeypatch.setattr("rig_agent.cli.UnityDelivery", _FakeUnityDelivery)
    return _FakeUnityDelivery


def _built_skeleton(tmp_path):
    main(["build", "--spec", str(EXAMPLES / "knight_side.json"), "--out", str(tmp_path)])
    return tmp_path / "skeleton.json"


def test_unity_apply_delivers_the_skeleton(fake_delivery, tmp_path, capsys):
    path = _built_skeleton(tmp_path)
    capsys.readouterr()
    assert main(["unity-apply", str(path)]) == 0
    captured = capsys.readouterr()
    assert "unity: applied (25 bones under RigAgent_Output/x)" in captured.out
    assert "[unity] connected" in captured.err
    assert len(fake_delivery.delivered) == 1 and fake_delivery.delivered[0].view == "side"


@pytest.mark.parametrize(
    ("status", "code"), [("applied", 0), ("failed", 1), ("unavailable", 2), ("skipped", 2)]
)
def test_unity_apply_exit_codes(fake_delivery, tmp_path, status, code):
    fake_delivery.result = _UnityResult(status=status, detail="why")
    assert main(["unity-apply", str(_built_skeleton(tmp_path))]) == code


def test_unity_apply_rejects_a_missing_or_invalid_file(fake_delivery, tmp_path, capsys):
    assert main(["unity-apply", str(tmp_path / "nope.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"bones": []}')
    assert main(["unity-apply", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "cannot read" in err and "not a valid skeleton.json" in err
    assert fake_delivery.delivered == []


def test_unity_check_reports_a_healthy_fake(monkeypatch, capsys):
    from fake_unity import FakeUnity
    from rig_agent.unity.mcp_client import check_unity

    monkeypatch.setattr("rig_agent.cli.check_unity", lambda url: check_unity(FakeUnity().server))
    monkeypatch.setattr("rig_agent.cli.settings.unity_project_path", None)
    assert main(["unity-check"]) == 0
    out = capsys.readouterr().out
    assert "unity:    6000.4.0f1" in out and "all 5 tools rig-agent uses are present" in out
    assert "UNITY_PROJECT_PATH is not set" in out


def test_unity_check_says_when_nothing_is_listening(capsys):
    assert main(["unity-check", "--url", "http://127.0.0.1:9/mcp"]) == 2
    assert "cannot reach the Unity MCP server" in capsys.readouterr().err


def test_unity_install_copies_the_scripts(tmp_path, capsys):
    (tmp_path / "Assets").mkdir()
    (tmp_path / "ProjectSettings").mkdir()
    assert main(["unity-install", "--project", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("installed:") == 3 and "Unity will now recompile" in out
    assert main(["unity-install", "--project", str(tmp_path)]) == 0
    assert capsys.readouterr().out.count("unchanged:") == 3


def test_unity_install_refuses_a_non_unity_folder(tmp_path, capsys):
    assert main(["unity-install", "--project", str(tmp_path)]) == 2
    assert "not a Unity project" in capsys.readouterr().err


def test_unity_check_shows_the_script_status_for_a_configured_project(
    monkeypatch, tmp_path, capsys
):
    from fake_unity import FakeUnity
    from rig_agent.unity.mcp_client import check_unity

    (tmp_path / "Assets").mkdir()
    (tmp_path / "ProjectSettings").mkdir()
    monkeypatch.setattr("rig_agent.cli.check_unity", lambda url: check_unity(FakeUnity().server))
    monkeypatch.setattr("rig_agent.cli.settings.unity_project_path", tmp_path)
    main(["unity-check"])
    assert "NOT installed" in capsys.readouterr().out
    main(["unity-install", "--project", str(tmp_path)])
    capsys.readouterr()
    main(["unity-check"])
    assert "scripts:  installed" in capsys.readouterr().out


# ---- prefabs and unity-apply-all -----------------------------------------------------------------


def test_unity_apply_makes_no_prefab_unless_asked(fake_delivery, tmp_path):
    main(["unity-apply", str(_built_skeleton(tmp_path))])
    assert fake_delivery.prefabs == [None]


def test_unity_apply_passes_the_prefab_folder(fake_delivery, tmp_path):
    path = _built_skeleton(tmp_path)
    main(["unity-apply", str(path), "--prefab-dir", "Assets/Prefabs/Rigs", "--overwrite-prefab"])
    prefab = fake_delivery.prefabs[-1]
    assert prefab.folder == "Assets/Prefabs/Rigs" and prefab.overwrite is True


def test_the_prefab_folder_can_come_from_the_settings(fake_delivery, tmp_path, monkeypatch):
    monkeypatch.setattr("rig_agent.cli.settings.unity_prefab_dir", "Assets/FromEnv")
    main(["unity-apply", str(_built_skeleton(tmp_path))])
    assert fake_delivery.prefabs[-1].folder == "Assets/FromEnv"
    main(["unity-apply", str(tmp_path / "skeleton.json"), "--prefab-dir", ""])  # switched off
    assert fake_delivery.prefabs[-1] is None


def test_a_prefab_folder_outside_assets_is_refused_before_anything_runs(
    fake_delivery, tmp_path, capsys
):
    path = _built_skeleton(tmp_path)
    assert main(["unity-apply", str(path), "--prefab-dir", "/tmp/elsewhere"]) == 2
    assert "inside the project's Assets folder" in capsys.readouterr().err
    assert fake_delivery.delivered == []


def test_overwrite_without_a_folder_is_an_error(fake_delivery, tmp_path, capsys):
    assert main(["unity-apply", str(_built_skeleton(tmp_path)), "--overwrite-prefab"]) == 2
    assert "--overwrite-prefab needs --prefab-dir" in capsys.readouterr().err


def test_run_passes_the_prefab_folder_to_the_unity_step(fake_graph, tmp_path):
    fake_graph(GOOD_SPEC)
    args = ["run", "a knight", "--unity", "--out", str(tmp_path)]
    assert main([*args, "--prefab-dir", "Assets/Prefabs"]) == 0
    assert fake_graph.prefab_seen[-1].folder == "Assets/Prefabs"
    assert main(args) == 0
    assert fake_graph.prefab_seen[-1] is None


def _out_with_rigs(tmp_path, *names):
    for name in names:
        main(["build", "--spec", str(EXAMPLES / "knight_side.json"), "--out", str(tmp_path / name)])
    return tmp_path


def test_unity_apply_all_builds_every_rig_in_out(fake_delivery, tmp_path, capsys):
    out = _out_with_rigs(tmp_path, "knight", "knight2")
    capsys.readouterr()
    assert main(["unity-apply-all", "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert fake_delivery.batch == [["knight", "knight2"]]
    assert "knight2" in captured.out and "unity: applied: 2 of 2 rig(s) built" in captured.out
    assert "Found 2 rig(s)" in captured.err


def test_unity_apply_all_passes_the_prefab_folder(fake_delivery, tmp_path):
    out = _out_with_rigs(tmp_path, "knight")
    main(["unity-apply-all", "--out", str(out), "--prefab-dir", "Assets/Prefabs/Rigs"])
    assert fake_delivery.prefabs[-1].folder == "Assets/Prefabs/Rigs"


def test_unity_apply_all_with_no_rigs_is_an_error(fake_delivery, tmp_path, capsys):
    assert main(["unity-apply-all", "--out", str(tmp_path / "empty")]) == 2
    assert "No rigs found" in capsys.readouterr().err
    assert fake_delivery.batch == []


def test_unity_apply_all_mentions_skipped_files(fake_delivery, tmp_path, capsys):
    out = _out_with_rigs(tmp_path, "knight")
    (out / "broken").mkdir()
    (out / "broken" / "skeleton.json").write_text("{nope")
    assert main(["unity-apply-all", "--out", str(out)]) == 0
    assert "skipped" in capsys.readouterr().err


@pytest.mark.parametrize(("status", "code"), [("failed", 1), ("unavailable", 2)])
def test_unity_apply_all_exit_codes(fake_delivery, tmp_path, status, code):
    fake_delivery.batch_result = BatchResult(status=status, detail="why")
    assert main(["unity-apply-all", "--out", str(_out_with_rigs(tmp_path, "knight"))]) == code
