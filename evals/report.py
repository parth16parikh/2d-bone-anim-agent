"""Writes an eval run's results: metrics.json (machine-readable) and report.md (for people)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from evals.golden import CATEGORIES, GoldenCase
from evals.metrics.expectations import check_run
from evals.metrics.quantitative import Metric
from evals.records import RunRecord

METRICS_FILE = "metrics.json"
REPORT_FILE = "report.md"
STATUSES = ("success", "best_effort", "accepted", "rejected", "error")  # accepted: guard only


def fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "%":
        return f"{value * 100:.1f}%"
    if unit == "s":
        return f"{value:.1f}s"
    if unit == "tokens":
        return f"{value:,.0f}"
    if unit == "$":
        return f"${value:.4f}"
    return f"{value:.4g}"


def fmt_target(metric: Metric) -> str:
    if metric.target is None:
        return "-"
    op = {">=": "≥", "<=": "≤", "=": "="}[metric.target.op]
    return f"{op} {fmt(metric.target.value, metric.unit)}"


def verdict(metric: Metric) -> str:
    return {True: "pass", False: "FAIL", None: "-"}[metric.passed]


def render_report(
    records: Sequence[RunRecord],
    cases: dict[str, GoldenCase],
    metrics: Sequence[Metric],
    title: str,
) -> str:
    guard_only = bool(records) and all(r.mode == "guard" for r in records)
    planners = sorted({r.model for r in records if r.mode == "full"})
    guards = sorted({r.guard_model for r in records if r.guard_model})
    ks = Counter(r.case_id for r in records)
    lines = [
        f"# {title}",
        "",
        "- Mode: guard only (the input guard alone; the planner was not run)"
        if guard_only
        else f"- Planner: {', '.join(planners) or '-'}",
        f"- Guard: {', '.join(guards) or '-'}",
        f"- Cases: {len(ks)}, runs: {len(records)} (k = {max(ks.values(), default=0)})",
        f"- Statuses: {', '.join(f'{s} {n}' for s, n in Counter(r.status for r in records).most_common())}",
        "",
        "## Metrics (LLD 4.2)",
        "",
        "Pass/fail only where the LLD sets a target. `-` means not measured (see Notes) or no target.",
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
    for category in CATEGORIES:
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
            failures = check_run(r, cases[r.case_id]).failures
            if failures:
                failed.append(f"- `{r.case_id}` run {r.run} ({r.category}): " + "; ".join(failures))
    lines += [
        "",
        f"## Failed expectations ({len(failed)} runs)",
        "",
        "Seeds the failure taxonomy (LLD 4.3).",
        "",
    ]
    lines += failed or ["None."]
    return "\n".join(lines) + "\n"


def write_results(
    folder: str | Path,
    records: Sequence[RunRecord],
    cases: dict[str, GoldenCase],
    metrics: Sequence[Metric],
    title: str,
) -> tuple[Path, Path]:
    directory = Path(folder)
    metrics_path, report_path = directory / METRICS_FILE, directory / REPORT_FILE
    payload = [asdict(m) | {"passed": m.passed} for m in metrics]
    metrics_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_report(records, cases, metrics, title), encoding="utf-8")
    return metrics_path, report_path
