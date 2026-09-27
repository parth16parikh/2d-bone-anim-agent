"""Checks one run against its golden case's expected attributes (LLD 4.1). Q8 and Q9 are rates
over these checks, and the report lists every failed one to seed the failure taxonomy (LLD 4.3)."""

from __future__ import annotations

from dataclasses import dataclass

from evals.golden import GoldenCase, in_range
from evals.metrics.extras import chains_by_group, extras_f1
from evals.records import RunRecord

DELIVERED = ("success", "best_effort")
GUARD_PASSED = "accepted"  # guard-only runs: the guard let it through (the planner never ran)


def _fmt_range(bounds: tuple[float | None, float | None]) -> str:
    low, high = bounds
    return f"[{'-' if low is None else f'{low:g}'}, {'-' if high is None else f'{high:g}'}]"


def _fmt_groups(counts: dict[str, int]) -> str:
    return ", ".join(f"{g} x{n}" for g, n in sorted(counts.items()) if n) or "none"


@dataclass(frozen=True)
class Checks:
    """Each check is None when the case does not ask for it (or the run has nothing to check)."""

    outcome_ok: bool
    view_ok: bool | None = None
    proportions_ok: bool | None = None
    bones_ok: bool | None = None
    extras_f1: float | None = None
    assumption_ok: bool | None = None
    failures: tuple[str, ...] = ()


def check_run(record: RunRecord, case: GoldenCase) -> Checks:
    expect = case.expect
    failures: list[str] = []
    rejected = record.status == "rejected"

    if expect.outcome == "reject":
        outcome_ok = rejected and (
            not expect.categories or record.guard_category in expect.categories
        )
        if not rejected:
            failures.append(
                f"should be rejected ({'/'.join(expect.categories) or 'any'}), got {record.status}"
            )
        elif not outcome_ok:
            failures.append(
                f"rejected as {record.guard_category}, expected {'/'.join(expect.categories)}"
            )
        return Checks(outcome_ok=outcome_ok, failures=tuple(failures))
    if expect.outcome == "reject_or_clamp":
        # accepted in a guard-only run also counts: the planner's schema limits then clamp it
        outcome_ok = rejected or record.status in (*DELIVERED, GUARD_PASSED)
        if not outcome_ok:
            failures.append(f"neither rejected nor clamped: {record.status} ({record.error})")
        return Checks(outcome_ok=outcome_ok, failures=tuple(failures))

    outcome_ok = record.status in ("success", GUARD_PASSED)
    if rejected:
        failures.append(f"rejected as {record.guard_category}, but it is a valid request")
    elif not outcome_ok:
        failures.append(f"ended {record.status}" + (f": {record.error}" if record.error else ""))

    final = record.final
    if final is None:  # nothing was delivered: every attribute check is moot
        return Checks(outcome_ok=outcome_ok, failures=tuple(failures))

    view_ok = None
    if expect.view is not None:
        view_ok = final.spec.view == expect.view
        if not view_ok:
            failures.append(f"view: expected {expect.view}, got {final.spec.view}")

    proportions_ok = None
    if expect.proportions:
        derived = final.derived() or {}
        proportions_ok = True
        for name, bounds in expect.proportions.items():
            value = derived.get(name)
            if value is None or not in_range(value, bounds):
                proportions_ok = False
                shown = "n/a" if value is None else f"{value:.3g}"
                failures.append(f"{name} {shown} not in {_fmt_range(bounds)}")

    bones_ok = None
    if expect.bones is not None and final.bone_count is not None:
        bones_ok = in_range(final.bone_count, expect.bones)
        if not bones_ok:
            failures.append(f"{final.bone_count} bones, expected {_fmt_range(expect.bones)}")

    f1 = None
    if expect.extras is not None:
        got = dict(chains_by_group(final.spec.extra_bones))
        f1 = extras_f1(expect.extras, got)
        if f1 < 1.0:
            failures.append(
                f"extras F1 {f1:.2f}: expected {_fmt_groups(expect.extras)}; got {_fmt_groups(got)}"
            )

    assumption_ok = None
    if expect.assumption:
        assumption_ok = bool(final.spec.assumptions)
        if not assumption_ok:
            failures.append("no assumption recorded for a vague prompt")

    return Checks(
        outcome_ok=outcome_ok,
        view_ok=view_ok,
        proportions_ok=proportions_ok,
        bones_ok=bones_ok,
        extras_f1=f1,
        assumption_ok=assumption_ok,
        failures=tuple(failures),
    )
