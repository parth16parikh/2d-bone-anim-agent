"""Command line: run the whole pipeline, plan a RigSpec, or build a rig from a RigSpec (LLD 3.12)."""

import argparse
import os
import sys
import time
import webbrowser
from pathlib import Path

os.environ.setdefault(
    "PYDANTIC_AI_NO_BANNER", "1"
)  # keep the startup banner out of the progress log

from pydantic import ValidationError
from pydantic_ai.exceptions import AgentRunError

from rig_agent.agent.planner import plan
from rig_agent.agent.tools import dry_run_validate
from rig_agent.builder.errors import BuildError
from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.config import settings
from rig_agent.export.json_exporter import (
    SKELETON_FILE,
    NotARigFolderError,
    delete_rig,
    export,
    load_skeleton,
)
from rig_agent.graph.build_graph import run_rig
from rig_agent.graph.nodes import default_deps
from rig_agent.guardrails.input_guard import check_input
from rig_agent.llm import MissingApiKeyError
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.unity.batch import collect_rigs
from rig_agent.unity.delivery import UnityDelivery
from rig_agent.unity.install import UnityProjectError, install_scripts, scripts_installed
from rig_agent.unity.mcp_client import NEEDED_TOOLS, UnityMcpError, check_unity
from rig_agent.unity.prefab import PrefabFolderError, PrefabOptions
from rig_agent.validator.report import validate
from rig_agent.viewer_server import create_server


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _build(args: argparse.Namespace) -> int:
    started = time.perf_counter()

    def elapsed(since: float) -> str:
        return f"{time.perf_counter() - since:.1f}s"

    _say(f"[1/4] Reading spec {args.spec} ...")
    step = time.perf_counter()
    try:
        spec = RigSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    except OSError as error:
        print(f"cannot read {args.spec}: {error}", file=sys.stderr)
        return 2
    except ValidationError as error:
        print(f"{args.spec} is not a valid RigSpec:\n{error}", file=sys.stderr)
        return 2
    _say(
        f"      {spec.preset} preset, {spec.view} view, {spec.rest_pose}, "
        f"{len(spec.optional_bones)} optional bone tokens, {len(spec.extra_bones)} extra chains "
        f"({elapsed(step)})"
    )

    _say("[2/4] Building the skeleton ...")
    step = time.perf_counter()
    try:
        skeleton = build_skeleton(spec, source_prompt=args.prompt)
    except BuildError as error:
        print(f"cannot build the rig: {error}", file=sys.stderr)
        return 2
    extras = sum(b.name.startswith("extra_") for b in skeleton.bones)
    _say(
        f"      {len(skeleton.bones)} bones ({len(skeleton.bones) - extras} canonical, "
        f"{extras} extra) in {elapsed(step)}"
    )

    _say("[3/4] Validating ...")
    step = time.perf_counter()
    report = validate(skeleton, spec)
    status = "PASSED" if report.passed else "FAILED"
    _say(
        f"      {status}: {len(report.errors)} errors, {len(report.warnings)} warnings "
        f"({elapsed(step)})"
    )
    metric_names = {
        "joint_connectivity": "connectivity",
        "symmetry_error": "symmetry error",
        "proportion_error": "proportion error",
    }
    shown = [
        f"{label} {report.metrics[key]:.4f}"
        for key, label in metric_names.items()
        if key in report.metrics
    ]
    if shown:
        _say("      " + ", ".join(shown))

    _say(f"[4/4] Exporting to {args.out} ...")
    if (args.out / SKELETON_FILE).is_file():
        _say(f"      note: replacing the rig already at {args.out}")
    result = export(skeleton, report, args.out)
    _say(f"      wrote {result.skeleton_path.name} and {result.report_path.name}")
    _say(f"Finished in {elapsed(started)}.")

    print(f"Built '{skeleton.rig_name}': {skeleton.view} view, {len(skeleton.bones)} bones")
    print(f"skeleton: {result.skeleton_path}")
    print(f"report:   {result.report_path} ({status})")
    for issue in report.issues:
        print(f"  [{issue.severity}] {issue.code.value}: {issue.message}")
    return 0 if report.passed else 1


def _plan(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    try:
        _say(f"[1/3] Input guard ({settings.guard_model}) ...")
        step = time.perf_counter()
        guard = check_input(args.description)
        if not guard.accepted:
            _say(f"      not accepted ({guard.category}) in {time.perf_counter() - step:.1f}s")
            print(f"Request not accepted ({guard.category}): {guard.reason}", file=sys.stderr)
            if guard.suggestion:
                print(f"Suggestion: {guard.suggestion}", file=sys.stderr)
            return 1
        _say(f"      accepted in {time.perf_counter() - step:.1f}s")

        _say(f"[2/3] Planner ({settings.planner_model}) ...")
        step = time.perf_counter()
        result = plan(args.description, args.view, progress=_say)
        _say(
            f"      done in {time.perf_counter() - step:.1f}s: {result.requests} model calls, "
            f"{result.tool_calls} tool calls, {result.input_tokens:,} tokens in, "
            f"{result.output_tokens:,} out"
        )
    except MissingApiKeyError as error:
        print(error, file=sys.stderr)
        return 2
    except AgentRunError as error:
        print(f"the model run failed: {error}", file=sys.stderr)
        return 2

    spec_json = result.spec.model_dump_json(indent=2, exclude_defaults=True)
    if args.out:
        args.out.write_text(spec_json + "\n", encoding="utf-8")
        _say(f"      RigSpec written to {args.out}")
    else:
        print(spec_json)

    report = dry_run_validate(result.spec)
    status = "PASSED" if report.passed else "FAILED"
    _say(f"[3/3] Dry run: {status} ({len(report.errors)} errors, {len(report.warnings)} warnings)")
    for issue in report.issues:
        _say(f"      [{issue.severity}] {issue.code.value}: {issue.message}")
    _say(f"Finished in {time.perf_counter() - started:.1f}s. Next: rig-agent build --spec <file>")
    return 0 if report.passed else 1


def _prefab_options(args: argparse.Namespace) -> PrefabOptions | None:
    """The prefab settings from --prefab-dir or UNITY_PREFAB_DIR; None means no prefabs."""
    folder = args.prefab_dir if args.prefab_dir is not None else settings.unity_prefab_dir
    if not folder:
        if args.overwrite_prefab:
            raise PrefabFolderError("--overwrite-prefab needs --prefab-dir (or UNITY_PREFAB_DIR)")
        return None
    return PrefabOptions(folder, overwrite=args.overwrite_prefab)


def _run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    try:
        prefab = _prefab_options(args) if args.unity else None
    except PrefabFolderError as error:
        print(error, file=sys.stderr)
        return 2
    state = run_rig(
        args.description,
        view=args.view,
        unity_mode=args.unity,
        out_dir=str(args.out),
        deps=default_deps(say=_say, prefab=prefab, ik=not args.no_ik),
    )
    status = state["status"]
    usage = state["usage"]
    attempts = state.get("attempts") or []
    scores = ", ".join(f"{a.score:.2f}" for a in attempts)
    _say(
        f"Finished in {time.perf_counter() - started:.1f}s: {len(attempts)} attempt(s)"
        + (f" (scores {scores})" if scores else "")
        + f", {usage.requests} model calls, {usage.tool_calls} tool calls, "
        f"{usage.total_tokens:,} tokens"
    )

    print(f"Status: {status}")
    if status == "rejected":
        guard = state.get("guard")
        if guard:
            print(f"Request not accepted ({guard.category}): {guard.reason}", file=sys.stderr)
            if guard.suggestion:
                print(f"Suggestion: {guard.suggestion}", file=sys.stderr)
        return 1
    if status == "error":
        print(f"Error: {state.get('error')}", file=sys.stderr)
        return 2

    output_path = state.get("output_path")
    if output_path:
        print(f"skeleton: {output_path}")
        print(f"report:   {Path(output_path).with_name('validation_report.json')}")
    unity = state.get("unity_result")
    if unity:
        print(f"unity:    {unity.status} ({unity.detail})")
    if status == "best_effort":
        print("Not import-ready: the rig did not pass validation.")
        report = state.get("validation")
        for issue in report.issues if report else []:
            print(f"  [{issue.severity}] {issue.code.value}: {issue.message}")
        return 1
    return 0


def _unity_check(args: argparse.Namespace) -> int:
    url = args.url or settings.unity_mcp_url
    _say(f"Connecting to the Unity MCP server at {url} ...")
    try:
        status = check_unity(url)
    except UnityMcpError as error:
        print(error, file=sys.stderr)
        return 2
    print(f"server:   {status.server or 'connected'} ({status.url})")
    print(f"unity:    {status.unity_version}, project instance {status.instance}")
    print(f"scene:    {status.scene or '-'}")
    print(f"state:    {'ready' if status.ready else 'busy: ' + ', '.join(status.blocking)}")
    print(f"tools:    {status.tool_count} available")
    needed = ", ".join(NEEDED_TOOLS)
    if status.missing_tools:
        print(f"MISSING:  {', '.join(status.missing_tools)} (rig-agent needs: {needed})")
    else:
        print(f"needed:   all {len(NEEDED_TOOLS)} tools rig-agent uses are present")
    project = settings.unity_project_path
    if not project:
        print("project:  UNITY_PROJECT_PATH is not set")
    else:
        try:
            state = (
                "installed"
                if scripts_installed(project)
                else "NOT installed (run rig-agent unity-install)"
            )
        except UnityProjectError as error:
            state = f"unusable: {error}"
        print(f"project:  {project}")
        print(f"scripts:  {state}")
    return 0 if status.ok else 2


def _unity_install(args: argparse.Namespace) -> int:
    project = args.project or settings.unity_project_path
    if not project:
        print("Give --project or set UNITY_PROJECT_PATH in .env.", file=sys.stderr)
        return 2
    try:
        result = install_scripts(project)
    except UnityProjectError as error:
        print(error, file=sys.stderr)
        return 2
    for name in result.copied:
        print(f"installed: {name}")
    for name in result.unchanged:
        print(f"unchanged: {name}")
    print("Unity will now recompile. Run `rig-agent unity-check` to confirm it is ready.")
    return 0


def _unity_apply(args: argparse.Namespace) -> int:
    try:
        skeleton = load_skeleton(args.skeleton)
    except OSError as error:
        print(f"cannot read {args.skeleton}: {error}", file=sys.stderr)
        return 2
    except ValidationError as error:
        print(f"{args.skeleton} is not a valid skeleton.json:\n{error}", file=sys.stderr)
        return 2

    try:
        prefab = _prefab_options(args)
    except PrefabFolderError as error:
        print(error, file=sys.stderr)
        return 2
    result = UnityDelivery(say=_say, prefab=prefab, ik=not args.no_ik).deliver(skeleton)
    detail = f" ({result.detail})" if result.detail else ""
    print(f"unity: {result.status}{detail}")
    return {"applied": 0, "failed": 1}.get(result.status, 2)


def _unity_apply_all(args: argparse.Namespace) -> int:
    try:
        prefab = _prefab_options(args)
    except PrefabFolderError as error:
        print(error, file=sys.stderr)
        return 2
    rigs, skipped = collect_rigs(args.out)
    for item in skipped:
        print(f"skipped {item.source}: {item.reason}", file=sys.stderr)
    if not rigs:
        print(
            f"No rigs found in {args.out}/ (looking for <folder>/skeleton.json).", file=sys.stderr
        )
        return 2
    _say(f"Found {len(rigs)} rig(s) in {args.out}/: {', '.join(r.name for r in rigs)}")

    result = UnityDelivery(say=_say, prefab=prefab, ik=not args.no_ik).deliver_all(rigs)
    width = max(len(o.name) for o in result.rigs) if result.rigs else 0
    for outcome in result.rigs:
        print(f"  {outcome.name:<{width}}  {outcome.status:<8} {outcome.detail}")
    applied = sum(o.status == "applied" for o in result.rigs)
    detail = f" ({result.detail})" if result.detail else ""
    print(f"unity: {result.status}{detail}: {applied} of {len(rigs)} rig(s) built")
    return {"applied": 0, "failed": 1}.get(result.status, 2)


def _view(args: argparse.Namespace) -> int:
    try:
        server = create_server(args.out, args.port)
    except OSError as error:
        print(f"cannot listen on port {args.port}: {error}", file=sys.stderr)
        return 2
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Viewer:  {url}")
    print(f"Serving: viewer/ and {args.out}/ only. Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


def _add_prefab_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-ik",
        action="store_true",
        help="do not set up arm and leg IK in Unity (default: a Limb solver per arm and leg)",
    )
    parser.add_argument(
        "--prefab-dir",
        metavar="ASSETS_PATH",
        help="also save each verified rig as a prefab in this folder of the Unity project, "
        "for example Assets/Prefabs/Rigs (default: UNITY_PREFAB_DIR)",
    )
    parser.add_argument(
        "--overwrite-prefab",
        action="store_true",
        help="replace a prefab that already exists (default: keep it, it may have been edited)",
    )


def _delete(args: argparse.Namespace) -> int:
    if args.all and args.folders:
        print("give either folders or --all, not both", file=sys.stderr)
        return 2
    if not args.all and not args.folders:
        print("give one or more rig folders to delete, or --all", file=sys.stderr)
        return 2

    if args.all:
        rigs, skipped = collect_rigs(args.out)
        for item in skipped:
            print(f"skipped {item.source}: {item.reason}", file=sys.stderr)
        folders = [rig.source.parent for rig in rigs]
        if not folders:
            print(f"{args.out}/ is already empty (no rigs found).")
            return 0
    else:
        folders = args.folders

    exit_code = 0
    for folder in folders:
        try:
            result = delete_rig(folder)
        except NotARigFolderError as error:
            print(error, file=sys.stderr)
            exit_code = 2
            continue
        kept = " (folder kept: not empty)" if not result.folder_removed else ""
        print(f"deleted {folder}: {', '.join(result.removed_files)}{kept}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rig-agent", description="2D humanoid rig agent")
    commands = parser.add_subparsers(dest="command", required=True)

    checker = commands.add_parser("unity-check", help="check the connection to Unity (MCP)")
    checker.add_argument("--url", help="the MCP endpoint (default: UNITY_MCP_URL)")
    checker.set_defaults(handler=_unity_check)

    installer = commands.add_parser(
        "unity-install", help="copy the C# scripts into the Unity project"
    )
    installer.add_argument(
        "--project", type=Path, help="Unity project folder (default: UNITY_PROJECT_PATH)"
    )
    installer.set_defaults(handler=_unity_install)

    applier = commands.add_parser(
        "unity-apply", help="deliver a skeleton.json to the open Unity Editor"
    )
    applier.add_argument("skeleton", type=Path, help="path to a skeleton.json")
    _add_prefab_arguments(applier)
    applier.set_defaults(handler=_unity_apply)

    all_applier = commands.add_parser(
        "unity-apply-all", help="build every rig found in out/ in Unity, side by side"
    )
    all_applier.add_argument("--out", type=Path, default=Path("out"), help="folder of rigs")
    _add_prefab_arguments(all_applier)
    all_applier.set_defaults(handler=_unity_apply_all)

    viewer = commands.add_parser("view", help="serve the rig viewer with a picker for out/")
    viewer.add_argument("--out", type=Path, default=Path("out"), help="folder of rigs to list")
    viewer.add_argument("--port", type=int, default=8000)
    viewer.add_argument("--open", action="store_true", help="open the viewer in a browser")
    viewer.set_defaults(handler=_view)

    runner = commands.add_parser("run", help="prompt to validated rig: guard, plan, build, repair")
    runner.add_argument("description", help="the character, for example 'chibi knight'")
    runner.add_argument("--view", choices=["front", "side"], help="force the view")
    runner.add_argument("--out", type=Path, default=Path("out"), help="output directory")
    runner.add_argument(
        "--unity",
        action="store_true",
        help="also build the rig in the open Unity Editor (needs UNITY_PROJECT_PATH)",
    )
    _add_prefab_arguments(runner)
    runner.set_defaults(handler=_run)

    planner = commands.add_parser("plan", help="plan a RigSpec from a text description")
    planner.add_argument("description", help="the character, for example 'chibi knight'")
    planner.add_argument("--view", choices=["front", "side"], help="force the view")
    planner.add_argument("--out", type=Path, help="write the RigSpec here instead of printing it")
    planner.set_defaults(handler=_plan)

    build = commands.add_parser("build", help="build a rig from a RigSpec JSON file (no LLM)")
    build.add_argument("--spec", required=True, type=Path, help="path to a RigSpec JSON file")
    build.add_argument("--out", type=Path, default=Path("out"), help="output directory")
    build.add_argument("--prompt", default="", help="text recorded as the skeleton's source_prompt")
    build.set_defaults(handler=_build)

    deleter = commands.add_parser(
        "delete", help="remove one or more rigs (skeleton.json + validation_report.json) from out/"
    )
    deleter.add_argument(
        "folders", nargs="*", type=Path, help="rig folders to delete, e.g. out/knight"
    )
    deleter.add_argument("--all", action="store_true", help="delete every rig folder under --out")
    deleter.add_argument(
        "--out", type=Path, default=Path("out"), help="used with --all: the folder to clear"
    )
    deleter.set_defaults(handler=_delete)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
