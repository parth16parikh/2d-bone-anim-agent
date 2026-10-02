"""The animation eval runner's command line (Goal 2, M4).

    uv run python -m evals.anim.run --category mood --k 1          # a small live run
    uv run python -m evals.anim.run                                # all 43 cases, k = 3
    uv run python -m evals.anim.run --rescore evals/results/anim/<run>   # recompute, no model calls

A live run calls the real guard and animation planner for every case, k times, so it costs money;
it asks first unless --yes. Results go to evals/results/anim/<timestamp>/: records.jsonl (written
as each run ends), metrics.json, report.md, and rigs/<case>__<run>/ (the rig and its clip).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from evals.anim.golden import (
    ANIM_CATEGORIES,
    ANIM_GOLDEN_PATH,
    AnimCase,
    load_anim_golden,
    select_cases,
)
from evals.anim.metrics import check_anim_run, compute_anim_metrics
from evals.anim.records import RECORDS_FILE, AnimRunRecord, append_anim_record, load_anim_records
from evals.anim.runner import AnimDepsFactory, run_anim_suite
from evals.metrics.quantitative import Metric, Prices
from evals.report import fmt, fmt_target, verdict
from rig_agent.graph.anim_graph import default_anim_deps
from rig_agent.observability.tracing import configure

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "anim"
STATUSES = ("success", "best_effort", "rejected", "error")


def render_anim_report(
    records: Sequence[AnimRunRecord],
    cases: dict[str, AnimCase],
    metrics: Sequence[Metric],
    title: str,
) -> str:
    ks = Counter(r.case_id for r in records)
    lines = [
        f"# {title}",
        "",
        f"- Planner: {', '.join(sorted({r.model for r in records})) or '-'}",
        f"- Guard: {', '.join(sorted({r.guard_model for r in records})) or '-'}",
        f"- Cases: {len(ks)}, runs: {len(records)} (k = {max(ks.values(), default=0)})",
        f"- Statuses: {', '.join(f'{s} {n}' for s, n in Counter(r.status for r in records).most_common())}",
        "",
        "## Metrics",
        "",
        "Pass/fail only where a target is set. `-` means not measured (see Notes) or no target.",
        "",
        "| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |",
        "|---|---|---:|---:|---:|---|:-:|---:|---|",
    ]
    for m in metrics:
        front, side = (fmt(m.by_view.get(v), m.unit) for v in ("front", "side"))
        lines.append(
            f"| {m.id} | {m.name} | {fmt(m.value, m.unit)} | {front} | {side} | {fmt_target(m)} "
            f"| {verdict(m)} | {m.n} | {m.detail.replace('|', '/')} |"
        )
    lines += [
        "",
        "## Runs by category",
        "",
        "| Category | Runs | " + " | ".join(STATUSES) + " |",
        "|---|---:|" + "---:|" * len(STATUSES),
    ]
    for category in ANIM_CATEGORIES:
        runs = [r for r in records if r.category == category]
        if runs:
            counts = Counter(r.status for r in runs)
            lines.append(
                f"| {category} | {len(runs)} | "
                + " | ".join(str(counts[s]) for s in STATUSES)
                + " |"
            )
    failed = []
    for r in records:
        if r.case_id in cases:
            failures = check_anim_run(r, cases[r.case_id]).failures
            if failures:
                spec = r.final_spec or r.planned
                chose = (
                    f" [chose {spec.clip}: speed {spec.speed:g}, stride {spec.stride:g}, bounce {spec.bounce:g}, "
                    f"arms {spec.arm_swing:g}, knees {spec.knee_lift:g}, lean {spec.lean_deg:g}]"
                    if spec
                    else ""
                )
                failed.append(
                    f'- `{r.case_id}` run {r.run} ({r.category}, "{r.prompt}"): '
                    + "; ".join(failures)
                    + chose
                )
    lines += ["", f"## Failed expectations ({len(failed)} runs)", ""]
    lines += failed or ["None."]
    return "\n".join(lines) + "\n"


def _summary(
    folder: Path,
    records: Sequence[AnimRunRecord],
    cases: dict[str, AnimCase],
    prices: Prices | None,
) -> int:
    metrics = compute_anim_metrics(records, cases, prices)
    payload = [asdict(m) | {"passed": m.passed} for m in metrics]
    (folder / "metrics.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    report = folder / "report.md"
    report.write_text(
        render_anim_report(records, cases, metrics, f"Animation eval report: {folder.name}"),
        encoding="utf-8",
    )
    for m in metrics:
        print(f"  {m.id:<17} {fmt(m.value, m.unit):>10}  {verdict(m):<4}  {m.name}")
    missed = [m.id for m in metrics if m.passed is False]
    print(f"\n{len(missed)} target(s) missed{': ' + ', '.join(missed) if missed else ''}")
    print(f"report: {report}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evals.anim.run", description="Run the animation golden set."
    )
    p.add_argument("--golden", default=str(ANIM_GOLDEN_PATH))
    p.add_argument("--k", type=int, default=3, help="runs per case (default 3)")
    p.add_argument("--case", action="append", default=[], metavar="ID")
    p.add_argument("--category", action="append", default=[], choices=ANIM_CATEGORIES)
    p.add_argument("--limit", type=int)
    p.add_argument("--out", default=str(RESULTS_DIR), help="parent folder for the results")
    p.add_argument("--usd-per-mtok-in", type=float)
    p.add_argument("--usd-per-mtok-out", type=float)
    p.add_argument(
        "--rescore", metavar="DIR", help="recompute metrics for a finished run; no model calls"
    )
    p.add_argument("--yes", action="store_true", help="do not ask before a live (paid) run")
    return p


def main(argv: Sequence[str] | None = None, deps_factory: AnimDepsFactory | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    given = (args.usd_per_mtok_in, args.usd_per_mtok_out)
    if (given[0] is None) != (given[1] is None):
        parser.error("give both --usd-per-mtok-in and --usd-per-mtok-out")
    prices = Prices(args.usd_per_mtok_in, args.usd_per_mtok_out) if given[0] is not None else None
    golden = load_anim_golden(args.golden)
    cases = golden.by_id()

    if args.rescore:
        folder = Path(args.rescore)
        if not (folder / RECORDS_FILE).is_file():
            parser.error(f"no {RECORDS_FILE} in {folder}")
        return _summary(folder, load_anim_records(folder), cases, prices)

    if args.k < 1:
        parser.error("--k must be at least 1")
    try:
        chosen = select_cases(
            golden.cases, ids=args.case, categories=args.category, limit=args.limit
        )
    except ValueError as error:
        parser.error(str(error))
    if not chosen:
        parser.error("no cases match the filters")

    runs = len(chosen) * args.k
    if deps_factory is None:  # live: the real guard and planner
        print(f"{len(chosen)} case(s) x k={args.k} = {runs} run(s), each calling the real models.")
        if not args.yes:
            if not sys.stdin.isatty():
                parser.error("a live run costs money: pass --yes to run it non-interactively")
            if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                print("cancelled")
                return 1
        configure()
    factory: AnimDepsFactory = deps_factory or default_anim_deps

    folder = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RECORDS_FILE).touch()
    print(f"results: {folder}")
    done = [0]
    started = time.perf_counter()

    def on_record(record: AnimRunRecord) -> None:
        append_anim_record(folder, record)
        done[0] += 1
        chose = f", {record.planned.clip}" if record.planned else ""
        print(
            f"[{done[0]}/{runs}] {record.case_id} #{record.run}: {record.status}{chose} ({record.latency_s:.1f}s)",
            flush=True,
        )

    records = run_anim_suite(
        chosen,
        args.k,
        rigs=golden.build_rigs(),
        deps_factory=factory,
        out_root=folder,
        on_record=on_record,
    )
    print(f"\n{runs} run(s) in {time.perf_counter() - started:.0f}s\n")
    return _summary(folder, records, cases, prices)


if __name__ == "__main__":
    sys.exit(main())
