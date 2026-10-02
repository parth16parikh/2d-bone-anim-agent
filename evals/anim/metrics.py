"""Animation eval metrics (Goal 2, M4), computed from saved run records, overall and per rig view.

Pass/fail only where a target is set; other numbers are shown for information. A metric that the
runs cannot measure (no side-view runs, k=1 for consistency, no prices for cost) is None with the
reason in `detail`, never a made-up 0 or 100%."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from evals.anim.golden import AnimCase, direction_ok
from evals.anim.records import AnimRunRecord
from evals.metrics.quantitative import Metric, Prices, Target

VIEWS = ("front", "side")
Values = Callable[[Sequence[AnimRunRecord]], tuple[float | None, int]]


@dataclass(frozen=True)
class AnimChecks:
    outcome_ok: bool
    clip_ok: bool | None = None
    directions: tuple[tuple[str, bool], ...] = ()  # (setting, moved the expected way?)
    failures: tuple[str, ...] = ()


def check_anim_run(record: AnimRunRecord, case: AnimCase) -> AnimChecks:
    expect = case.expect
    failures: list[str] = []
    rejected = record.status == "rejected"

    if expect.outcome == "reject":
        ok = rejected and (not expect.categories or record.guard_category in expect.categories)
        if not rejected:
            failures.append(
                f"should be refused ({'/'.join(expect.categories)}), got {record.status}"
            )
        elif not ok:
            failures.append(
                f"refused as {record.guard_category}, expected {'/'.join(expect.categories)}"
            )
        return AnimChecks(outcome_ok=ok, failures=tuple(failures))

    planned = record.planned
    clip_ok = None if planned is None else planned.clip == expect.clip
    if clip_ok is False:
        assert planned is not None
        failures.append(f"clip: expected {expect.clip}, the planner chose {planned.clip}")

    if expect.outcome == "wrong_view":
        ok = record.stopped_for_view and not record.clip_written and bool(clip_ok)
        if rejected:
            failures.append(f"refused as {record.guard_category}; it should reach the view check")
        elif not record.stopped_for_view:
            failures.append(f"should stop for the view, ended {record.status}")
        if record.clip_written:
            failures.append("a clip was written although the rig cannot play it")
        return AnimChecks(outcome_ok=ok, clip_ok=clip_ok, failures=tuple(failures))

    ok = record.status == "success"
    if rejected:
        failures.append(f"refused as {record.guard_category}, but it is a valid request")
    elif not ok:
        failures.append(f"ended {record.status}" + (f": {record.error}" if record.error else ""))
    spec = record.final_spec or planned
    directions = []
    if spec is not None:
        for setting, wanted in expect.directions.items():
            value = getattr(spec, setting)
            good = direction_ok(setting, value, wanted)
            directions.append((setting, good))
            if not good:
                failures.append(f"{setting} {value:g} is not {wanted}")
    return AnimChecks(
        outcome_ok=ok, clip_ok=clip_ok, directions=tuple(directions), failures=tuple(failures)
    )


def _rate(
    runs: Sequence[AnimRunRecord], ok: Callable[[AnimRunRecord], bool]
) -> tuple[float | None, int]:
    return (sum(1 for r in runs if ok(r)) / len(runs), len(runs)) if runs else (None, 0)


def _metric(
    id: str,
    name: str,
    unit: str,
    runs: Sequence[AnimRunRecord],
    values: Values,
    target: Target | None = None,
    detail: str = "",
) -> Metric:
    value, n = values(runs)
    by_view = {v: values([r for r in runs if r.rig_view == v])[0] for v in VIEWS}
    return Metric(id, name, unit, value, target, by_view, n, detail)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def compute_anim_metrics(
    records: Sequence[AnimRunRecord], cases: dict[str, AnimCase], prices: Prices | None = None
) -> list[Metric]:
    records = [r for r in records if r.case_id in cases]
    checks = {id(r): check_anim_run(r, cases[r.case_id]) for r in records}

    def outcome(r: AnimRunRecord) -> str:
        return cases[r.case_id].expect.outcome

    accept = [r for r in records if outcome(r) == "accept"]
    valid = [r for r in records if outcome(r) != "reject"]  # accept + wrong_view
    m: list[Metric] = []

    planned = [r for r in records if r.plan_calls]
    m.append(
        _metric(
            "A1",
            "First-pass schema validity",
            "%",
            planned,
            lambda rs: _rate(rs, lambda r: not r.first_plan_retries),
            Target(">=", 0.95),
        )
    )
    m.append(
        _metric(
            "A2",
            "Final validity (valid requests end in a passing clip)",
            "%",
            accept,
            lambda rs: _rate(rs, lambda r: r.status == "success"),
            Target(">=", 0.98),
        )
    )
    with_clip = [r for r in valid if checks[id(r)].clip_ok is not None]
    m.append(
        _metric(
            "A3",
            "Clip accuracy (the planner chose the expected clip)",
            "%",
            with_clip,
            lambda rs: _rate(rs, lambda r: bool(checks[id(r)].clip_ok)),
            Target(">=", 0.95),
        )
    )

    def direction_share(rs: Sequence[AnimRunRecord]) -> tuple[float | None, int]:
        results = [good for r in rs for _, good in checks[id(r)].directions]
        return (sum(results) / len(results), len(results)) if results else (None, 0)

    directed = [r for r in accept if checks[id(r)].directions]
    m.append(
        _metric(
            "A4",
            "Setting directions (each expected up/down/same)",
            "%",
            directed,
            direction_share,
            Target(">=", 0.90),
        )
    )
    m.append(
        _metric(
            "A4 runs",
            "Runs with every setting direction right",
            "%",
            directed,
            lambda rs: _rate(rs, lambda r: all(g for _, g in checks[id(r)].directions)),
        )
    )

    must_refuse = [r for r in records if outcome(r) == "reject"]
    right = sum(1 for r in must_refuse if checks[id(r)].outcome_ok)
    m.append(
        _metric(
            "A5 recall",
            "Guard recall (unsupported and adversarial refused)",
            "%",
            must_refuse,
            lambda rs: _rate(rs, lambda r: r.status == "rejected"),
            Target(">=", 0.95),
            detail=f"{right}/{len(must_refuse)} also with the expected category",
        )
    )
    m.append(
        _metric(
            "A5 false-reject",
            "False rejections (valid requests refused)",
            "%",
            valid,
            lambda rs: _rate(rs, lambda r: r.status == "rejected"),
            Target("<=", 0.02),
        )
    )
    wrong_view = [r for r in records if outcome(r) == "wrong_view"]
    m.append(
        _metric(
            "A6",
            "View rule (front-view walk/run/backflip stopped, nothing swapped or written)",
            "%",
            wrong_view,
            lambda rs: _rate(rs, lambda r: checks[id(r)].outcome_ok),
            Target("=", 1.0),
        )
    )

    delivered = [r for r in accept if r.status == "success"]
    m.append(
        _metric(
            "A7 pass@1",
            "Passed on the first attempt",
            "%",
            accept,
            lambda rs: _rate(rs, lambda r: r.status == "success" and r.final_iteration == 1),
        )
    )
    m.append(
        _metric(
            "A7 attempts",
            "Mean attempts to a passing clip",
            "",
            delivered,
            lambda rs: (
                (statistics.fmean(r.final_iteration or 0 for r in rs), len(rs)) if rs else (None, 0)
            ),
            Target("<=", 1.5),
        )
    )

    def worst(name: str) -> Values:
        def values(rs: Sequence[AnimRunRecord]) -> tuple[float | None, int]:
            finals = [a for r in rs for a in r.attempts if a.iteration == r.final_iteration]
            return (
                (max(a.metrics.get(name, 0.0) for a in finals), len(finals))
                if finals
                else (None, 0)
            )

        return values

    m.append(
        _metric(
            "A7 slip",
            "Worst foot slip of a delivered clip (share of height per frame)",
            "",
            delivered,
            worst("max_foot_slip"),
        )
    )
    m.append(
        _metric(
            "A7 floor",
            "Worst body depth below the floor, delivered clips (share of height)",
            "",
            delivered,
            worst("max_body_below_floor"),
        )
    )

    m.extend(_consistency(valid, checks))
    m.extend(_efficiency([r for r in records if r.plan_calls], prices))
    return m


def _consistency(valid: Sequence[AnimRunRecord], checks: dict[int, AnimChecks]) -> list[Metric]:
    """The same prompt, run k times: the same clip, and the same verdict for each expected direction."""
    by_case: dict[str, list[AnimRunRecord]] = defaultdict(list)
    for r in valid:
        if r.planned is not None:
            by_case[r.case_id].append(r)
    groups = {c: rs for c, rs in by_case.items() if len(rs) >= 2}
    detail = "" if groups else "not measured: needs k >= 2 runs of the same case"

    def same_clip(ids: list[str]) -> float | None:
        if not ids:
            return None
        return sum(
            1 for c in ids if len({r.planned.clip for r in groups[c] if r.planned}) == 1
        ) / len(ids)

    def same_direction(ids: list[str]) -> float | None:
        verdicts = []
        for c in ids:
            per_run = [dict(checks[id(r)].directions) for r in groups[c]]
            for setting in per_run[0]:
                verdicts.append(len({d.get(setting) for d in per_run}) == 1)
        return sum(verdicts) / len(verdicts) if verdicts else None

    ids = sorted(groups)
    by = {v: [c for c in ids if groups[c][0].rig_view == v] for v in VIEWS}
    return [
        Metric(
            "A8 clip",
            "Consistency: the same clip across runs",
            "%",
            same_clip(ids),
            Target(">=", 0.95),
            {v: same_clip(by[v]) for v in VIEWS},
            len(ids),
            detail,
        ),
        Metric(
            "A8 directions",
            "Consistency: the same direction verdict across runs",
            "%",
            same_direction(ids),
            Target(">=", 0.90),
            {v: same_direction(by[v]) for v in VIEWS},
            len(ids),
            detail,
        ),
    ]


def _cost(record: AnimRunRecord, prices: Prices) -> float:
    return (
        record.input_tokens * prices.input_per_mtok + record.output_tokens * prices.output_per_mtok
    ) / 1e6


def _efficiency(runs: Sequence[AnimRunRecord], prices: Prices | None) -> list[Metric]:
    def pct(value: Callable[[AnimRunRecord], float], q: float) -> Values:
        return lambda rs: (_percentile([value(r) for r in rs], q), len(rs)) if rs else (None, 0)

    def tokens(r: AnimRunRecord) -> float:
        return float(r.input_tokens + r.output_tokens)

    metrics = [
        _metric(
            "A9 p50 latency", "Latency per request, p50", "s", runs, pct(lambda r: r.latency_s, 0.5)
        ),
        _metric(
            "A9 p95 latency",
            "Latency per request, p95",
            "s",
            runs,
            pct(lambda r: r.latency_s, 0.95),
            Target("<=", 30.0),
        ),
        _metric("A9 p50 tokens", "Tokens per request, p50", "tokens", runs, pct(tokens, 0.5)),
        _metric("A9 p95 tokens", "Tokens per request, p95", "tokens", runs, pct(tokens, 0.95)),
    ]
    if prices is None:
        metrics.append(
            Metric(
                "A9 cost",
                "Cost per request, mean",
                "$",
                None,
                Target("<=", 0.05),
                detail="not measured: pass --usd-per-mtok-in and --usd-per-mtok-out",
            )
        )
    else:
        metrics.append(
            _metric(
                "A9 cost",
                "Cost per request, mean",
                "$",
                runs,
                lambda rs: (
                    (statistics.fmean(_cost(r, prices) for r in rs), len(rs)) if rs else (None, 0)
                ),
                Target("<=", 0.05),
            )
        )
    return metrics
