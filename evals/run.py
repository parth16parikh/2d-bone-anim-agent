"""The eval runner's command line (Phase H4).

    uv run python -m evals.run --category accessory --k 1         # a small, cheap live run
    uv run python -m evals.run                                    # the whole golden set, k = 3
    uv run python -m evals.run --rescore evals/results/<run>      # recompute metrics, no model calls
    uv run python -m evals.run --guard-only --guard-model gpt-5.4-mini   # only the input guard (Q9)

A live run calls the real planner and guard for every case, k times, and so costs money; it asks
before starting unless --yes. Results go to evals/results/<timestamp>/: records.jsonl (one line
per run, written as each run ends), metrics.json, report.md, and rigs/<case>__<run>/ with each
delivered skeleton.json (plus skeleton.png with --render).
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from evals.golden import CATEGORIES, GOLDEN_PATH, GoldenCase, load_golden, select
from evals.metrics.quantitative import Prices, compute_metrics
from evals.records import RECORDS_FILE, RunRecord, append_record, load_records
from evals.report import fmt, verdict, write_results
from evals.runner import DepsFactory, GuardCheck, model_label, run_case, run_guard_case, run_suite
from rig_agent.config import settings
from rig_agent.graph.nodes import GraphDeps, default_deps
from rig_agent.guardrails.input_guard import build_guard_agent, check_input
from rig_agent.llm import build_model
from rig_agent.observability.tracing import configure

RESULTS_DIR = Path(__file__).with_name("results")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evals.run", description="Run the golden eval set and compute Q1-Q13."
    )
    p.add_argument(
        "--golden", default=str(GOLDEN_PATH), help="the golden set (default evals/golden.yaml)"
    )
    p.add_argument("--k", type=int, default=3, help="runs per case (default 3, as in LLD 4.1)")
    p.add_argument(
        "--case", action="append", default=[], metavar="ID", help="only this case (repeatable)"
    )
    p.add_argument(
        "--category",
        action="append",
        default=[],
        choices=CATEGORIES,
        help="only this category (repeatable)",
    )
    p.add_argument("--limit", type=int, help="at most this many cases (after the filters)")
    p.add_argument("--out", default=str(RESULTS_DIR), help="parent folder for the results")
    p.add_argument("--unity", action="store_true", help="also deliver each rig to Unity (Q13)")
    p.add_argument("--render", action="store_true", help="draw each delivered rig to skeleton.png")
    p.add_argument(
        "--usd-per-mtok-in", type=float, help="input price, US$ per million tokens (Q12 cost)"
    )
    p.add_argument("--usd-per-mtok-out", type=float, help="output price, US$ per million tokens")
    p.add_argument(
        "--rescore", metavar="DIR", help="recompute metrics for a finished run; no model calls"
    )
    p.add_argument(
        "--guard-only",
        action="store_true",
        help="run only the input guard on each prompt (Q9); cheap, no planner, no rigs",
    )
    p.add_argument(
        "--guard-model",
        metavar="MODEL",
        help="the guard model to use instead of the configured one (e.g. gpt-5.4-mini)",
    )
    p.add_argument("--yes", action="store_true", help="do not ask before a live (paid) run")
    return p


def _live_guard(guard_model: str | None) -> tuple[GuardCheck, str]:
    """The real input guard, optionally with another model, built once and reused per prompt."""
    cfg = settings
    if guard_model:
        field = "guard_model" if cfg.primary_provider == "openai" else "anthropic_guard_model"
        cfg = cfg.model_copy(update={field: guard_model})
    agent = build_guard_agent(build_model("guard", cfg))
    return functools.partial(check_input, agent=agent), model_label(cfg, "guard")


def _prices(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Prices | None:
    given = (args.usd_per_mtok_in, args.usd_per_mtok_out)
    if given == (None, None):
        return None
    if None in given:
        parser.error("give both --usd-per-mtok-in and --usd-per-mtok-out")
    return Prices(args.usd_per_mtok_in, args.usd_per_mtok_out)


def _summary(folder: Path, records: Sequence[RunRecord], cases: dict, prices: Prices | None) -> int:
    metrics = compute_metrics(records, cases, prices)
    title = f"Eval report: {folder.name}"
    _, report_path = write_results(folder, records, cases, metrics, title)
    for m in metrics:
        print(f"  {m.id:<17} {fmt(m.value, m.unit):>10}  {verdict(m):<4}  {m.name}")
    failed = [m.id for m in metrics if m.passed is False]
    print(f"\n{len(failed)} target(s) missed{': ' + ', '.join(failed) if failed else ''}")
    print(f"report: {report_path}")
    return 0


def _render(records: Sequence[RunRecord]) -> None:
    try:
        from evals.render_skeleton import render_folder
    except ImportError:
        print("--render needs Pillow: uv sync --extra eval", file=sys.stderr)
        return
    for r in records:
        if r.rig_dir:
            render_folder(r.rig_dir)


def main(
    argv: Sequence[str] | None = None,
    deps_factory: DepsFactory | None = None,
    guard_check: GuardCheck | None = None,
) -> int:
    """`deps_factory` (full runs) and `guard_check` (--guard-only) replace the real models in
    tests; without them a run is live."""
    parser = _parser()
    args = parser.parse_args(argv)
    prices = _prices(args, parser)
    golden = load_golden(args.golden)
    cases = golden.by_id()

    if args.rescore:
        folder = Path(args.rescore)
        if not (folder / RECORDS_FILE).is_file():
            parser.error(f"no {RECORDS_FILE} in {folder}")
        return _summary(folder, load_records(folder), cases, prices)

    if args.k < 1:
        parser.error("--k must be at least 1")
    if args.guard_only and (args.unity or args.render):
        parser.error("--guard-only makes no rigs: it cannot be combined with --unity or --render")
    try:
        chosen = select(golden.cases, ids=args.case, categories=args.category, limit=args.limit)
    except ValueError as error:
        parser.error(str(error))
    if not chosen:
        parser.error("no cases match the filters")

    runs = len(chosen) * args.k
    live = (guard_check if args.guard_only else deps_factory) is None
    if live:
        what = "the guard model only" if args.guard_only else "the real guard and planner"
        print(f"{len(chosen)} case(s) x k={args.k} = {runs} run(s), each calling {what}.")
        if not args.yes:
            if not sys.stdin.isatty():
                parser.error("a live run costs money: pass --yes to run it non-interactively")
            if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                print("cancelled")
                return 1
        configure()  # Logfire traces for every eval run too, when LOGFIRE_TOKEN is set

    folder = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")  # local time
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RECORDS_FILE).touch()

    run_one: Callable[[GoldenCase, int], RunRecord]
    if args.guard_only:
        check, label = (guard_check, "test:guard") if guard_check else _live_guard(args.guard_model)
        run_one = functools.partial(run_guard_case, check=check, label=label)
    else:
        factory: DepsFactory = deps_factory or default_deps
        guard_label = None
        if args.guard_model and live:
            check, guard_label = _live_guard(args.guard_model)
            base_factory = factory

            def factory() -> GraphDeps:
                return dataclasses.replace(base_factory(), check_input=check)

        run_one = functools.partial(
            run_case,
            deps_factory=factory,
            out_root=folder,
            unity=args.unity,
            guard_label=guard_label,
        )

    print(f"results: {folder}")
    done = [0]
    started = time.perf_counter()

    def on_record(record: RunRecord) -> None:
        append_record(folder, record)
        done[0] += 1
        if record.mode == "guard":
            note = record.guard_category or "-"
        else:
            tries = len(record.attempts)
            note = f"{tries} attempt{'s' * (tries != 1)}"
        print(
            f"[{done[0]}/{runs}] {record.case_id} #{record.run}: {record.status}"
            f" ({note}, {record.latency_s:.1f}s)"
            + (f" - {record.error}" if record.error and record.status == "error" else ""),
            flush=True,
        )

    records = run_suite(chosen, args.k, run_one, on_record)
    print(f"\n{runs} run(s) in {time.perf_counter() - started:.0f}s\n")
    if args.render:
        _render(records)
    return _summary(folder, records, cases, prices)


if __name__ == "__main__":
    sys.exit(main())
