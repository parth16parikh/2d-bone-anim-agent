"""Q1-Q13 (LLD 4.2) computed from saved run records, overall and per view.

Only targets written in the LLD get a pass/fail; the few extra numbers reported alongside them
(precision, pass@1, ...) have target None and are shown for information. A metric that cannot be
measured from the given runs (no side-view rigs, k=1 for consistency, no prices for cost, no
Unity for Q13) has value None, and its `detail` says why, rather than a misleading 0 or 100%.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from evals.golden import GoldenCase
from evals.metrics.expectations import Checks, check_run
from evals.records import AttemptRec, RunRecord

VIEWS = ("front", "side")
FATAL_CODES = {"no_root", "multiple_roots", "cycle", "orphan_bone", "duplicate_name"}
GUARD_METRICS = ("Q9 recall", "Q9 precision", "Q9 clamp", "Q9 false-reject")
BUCKETS = ((4.0, "<=4"), (6.5, "4-6.5"), (float("inf"), ">6.5"))  # heads tall (Q10)


@dataclass(frozen=True)
class Target:
    op: str  # ">=", "<=" or "="
    value: float

    def met(self, value: float) -> bool:
        if self.op == ">=":
            return value >= self.value - 1e-12
        if self.op == "<=":
            return value <= self.value + 1e-12
        return abs(value - self.value) <= 1e-12


@dataclass(frozen=True)
class Prices:
    """US dollars per million tokens. Not built in: prices change and differ per model."""

    input_per_mtok: float
    output_per_mtok: float

    def cost(self, record: RunRecord) -> float:
        return (
            record.input_tokens * self.input_per_mtok + record.output_tokens * self.output_per_mtok
        ) / 1e6


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    unit: str  # "%" (value is a 0-1 fraction), "" (a plain number), "s", "tokens" or "$"
    value: float | None
    target: Target | None = None
    by_view: dict[str, float | None] = field(default_factory=dict)
    n: int = 0  # how many runs (or cases) the value is over
    detail: str = ""

    @property
    def passed(self) -> bool | None:
        if self.target is None or self.value is None:
            return None
        return self.target.met(self.value)


Values = Callable[[Sequence[RunRecord]], tuple[float | None, int]]


def _rate(runs: Sequence[RunRecord], ok: Callable[[RunRecord], bool]) -> tuple[float | None, int]:
    return (sum(1 for r in runs if ok(r)) / len(runs), len(runs)) if runs else (None, 0)


def _mean(
    runs: Sequence[RunRecord], value: Callable[[RunRecord], float]
) -> tuple[float | None, int]:
    return (statistics.fmean(value(r) for r in runs), len(runs)) if runs else (None, 0)


def _metric(
    id: str,
    name: str,
    unit: str,
    runs: Sequence[RunRecord],
    values: Values,
    target: Target | None = None,
    detail: str = "",
    per_view: bool = True,
) -> Metric:
    value, n = values(runs)
    by_view = {v: values([r for r in runs if r.view == v])[0] for v in VIEWS} if per_view else {}
    return Metric(id, name, unit, value, target, by_view, n, detail)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def _attempt_metric(attempt: AttemptRec | None, name: str) -> float:
    return attempt.metrics.get(name, 0.0) if attempt else 0.0


def _structure_ok(attempt: AttemptRec | None) -> bool:
    return (
        attempt is not None
        and attempt.bone_count is not None
        and not FATAL_CODES & set(attempt.issue_codes)
    )


def _bucket(heads_tall: float) -> str:
    return next(label for limit, label in BUCKETS if heads_tall <= limit)


def compute_metrics(
    records: Sequence[RunRecord], cases: dict[str, GoldenCase], prices: Prices | None = None
) -> list[Metric]:
    records = [r for r in records if r.case_id in cases]
    checks: dict[int, Checks] = {id(r): check_run(r, cases[r.case_id]) for r in records}

    def outcome(r: RunRecord) -> str:
        return cases[r.case_id].expect.outcome

    valid = [r for r in records if outcome(r) == "accept"]  # everything but the adversarial set
    planned = [r for r in records if r.attempts]  # the planner returned at least one spec
    delivered = [r for r in records if r.status == "success"]
    m: list[Metric] = []

    # Q1: the first RigSpec the model produced parsed, i.e. was not sent back by the schema
    accepted = [r for r in records if r.guard_accepted]
    m.append(
        _metric(
            "Q1",
            "First-pass schema validity",
            "%",
            accepted,
            lambda rs: _rate(rs, lambda r: r.first is not None and not r.first.output_retries),
            Target(">=", 0.95),
        )
    )

    # Q2: valid requests that end in success (a wrong rejection counts as a failure here too)
    m.append(
        _metric(
            "Q2",
            "Final validity rate",
            "%",
            valid,
            lambda rs: _rate(rs, lambda r: r.status == "success"),
            Target(">=", 0.98),
        )
    )

    # Q3-Q5 on delivered rigs (guaranteed by the validator) and on first attempts (raw quality)
    m.extend(_integrity("", "delivered rigs", delivered, lambda r: r.final))
    m.extend(_integrity(" first", "first attempts", planned, lambda r: r.first))

    m.append(
        _metric(
            "Q6",
            "Symmetry error (mean, /H)",
            "",
            delivered,
            lambda rs: _mean(rs, lambda r: _attempt_metric(r.final, "symmetry_error")),
            Target("<=", 0.01),
        )
    )
    side = [r for r in delivered if r.view == "side"]
    m.append(
        _metric(
            "Q6b",
            "Depth-order correctness (side view)",
            "%",
            side,
            lambda rs: _rate(rs, lambda r: _attempt_metric(r.final, "depth_order_correct") >= 1.0),
            Target("=", 1.0),
            per_view=False,
        )
    )
    m.append(
        _metric(
            "Q7",
            "Proportion error (mean)",
            "",
            delivered,
            lambda rs: _mean(rs, lambda r: _attempt_metric(r.final, "proportion_error")),
            Target("<=", 0.10),
        )
    )

    # Q8: prompt adherence, over the runs whose case asks for each attribute
    def sub(attr: str, categories: tuple[str, ...] | None = None) -> list[RunRecord]:
        return [
            r
            for r in valid
            if getattr(checks[id(r)], attr) is not None
            and (categories is None or cases[r.case_id].category in categories)
        ]

    def flag(attr: str) -> Values:
        return lambda rs: _rate(rs, lambda r: bool(getattr(checks[id(r)], attr)))

    m.append(
        _metric(
            "Q8 view",
            "Spec accuracy: view",
            "%",
            sub("view_ok"),
            flag("view_ok"),
            Target(">=", 0.95),
        )
    )
    m.append(
        _metric(
            "Q8 style",
            "Spec accuracy: style descriptor",
            "%",
            sub("proportions_ok", ("standard", "stylized")),
            flag("proportions_ok"),
            Target(">=", 0.90),
        )
    )
    m.append(
        _metric(
            "Q8 modifier",
            "Spec accuracy: override direction",
            "%",
            sub("proportions_ok", ("modifier",)),
            flag("proportions_ok"),
        )
    )
    m.append(
        _metric(
            "Q8 extras",
            "Spec accuracy: extra-bone F1",
            "",
            sub("extras_f1"),
            lambda rs: _mean(rs, lambda r: checks[id(r)].extras_f1 or 0.0),
            Target(">=", 0.85),
        )
    )
    m.append(
        _metric(
            "Q8 bones", "Spec accuracy: bone count in range", "%", sub("bones_ok"), flag("bones_ok")
        )
    )
    m.append(
        _metric(
            "Q8 assumption",
            "Spec accuracy: assumption recorded (vague prompts)",
            "%",
            sub("assumption_ok"),
            flag("assumption_ok"),
        )
    )

    # Q9: the guardrail on the adversarial set, and false rejections of valid prompts
    must_reject = [r for r in records if outcome(r) == "reject"]
    rejected = [r for r in records if r.status == "rejected"]
    right_category = sum(1 for r in must_reject if checks[id(r)].outcome_ok)
    m.append(
        _metric(
            "Q9 recall",
            "Guardrail recall (should-reject rejected)",
            "%",
            must_reject,
            lambda rs: _rate(rs, lambda r: r.status == "rejected"),
            Target(">=", 0.95),
            detail=f"{right_category}/{len(must_reject)} also with the expected category",
            per_view=False,
        )
    )
    m.append(
        _metric(
            "Q9 precision",
            "Guardrail precision (rejections that were right)",
            "%",
            rejected,
            lambda rs: _rate(rs, lambda r: outcome(r) != "accept"),
            per_view=False,
        )
    )
    clamp = [r for r in records if outcome(r) == "reject_or_clamp"]
    m.append(
        _metric(
            "Q9 clamp",
            "Rejected or clamped (reject_or_clamp cases)",
            "%",
            clamp,
            lambda rs: _rate(rs, lambda r: checks[id(r)].outcome_ok),
            per_view=False,
        )
    )
    m.append(
        _metric(
            "Q9 false-reject",
            "False-reject rate (valid prompts)",
            "%",
            valid,
            lambda rs: _rate(rs, lambda r: r.status == "rejected"),
            Target("<=", 0.02),
            per_view=False,
        )
    )

    # Q9b: first attempts that broke a rule only code caught (schema retry, or validation errors)
    def broke(r: RunRecord) -> bool:
        return r.first is not None and (bool(r.first.output_retries) or not r.first.passed)

    rules: Counter[str] = Counter()
    for r in planned:
        assert r.first is not None
        rules.update(f"schema: {msg}" for msg in r.first.output_retries)
        rules.update(f"validator: {code}" for code in set(r.first.error_codes))
    top = "; ".join(f"{rule} x{n}" for rule, n in rules.most_common(5))
    m.append(
        _metric(
            "Q9b",
            "Prompt-guardrail adherence (first attempts caught by code)",
            "%",
            planned,
            lambda rs: _rate(rs, broke),
            Target("<=", 0.05),
            detail=top,
        )
    )

    m.extend(_consistency(delivered))

    # Q11: convergence
    m.append(
        _metric(
            "Q11",
            "Convergence: mean iterations to success",
            "",
            delivered,
            lambda rs: _mean(rs, lambda r: float(r.final_iteration or 0)),
            Target("<=", 1.5),
        )
    )
    m.append(
        _metric(
            "Q11 pass@1",
            "pass@1 (success on the first attempt)",
            "%",
            valid,
            lambda rs: _rate(rs, lambda r: r.status == "success" and r.final_iteration == 1),
        )
    )
    m.append(
        _metric(
            "Q11 pass@3",
            "pass@3 (success within 3 attempts)",
            "%",
            valid,
            lambda rs: _rate(rs, lambda r: r.status == "success"),
        )
    )

    m.extend(_efficiency([r for r in records if r.status in ("success", "best_effort")], prices))

    # Q13: Unity import, only when the suite ran with --unity
    in_unity = [r for r in delivered if r.unity_status is not None]
    m.append(
        _metric(
            "Q13",
            "Unity import success",
            "%",
            in_unity,
            lambda rs: _rate(rs, lambda r: r.unity_status == "applied"),
            Target("=", 1.0),
            detail="" if in_unity else "not measured: run with --unity",
        )
    )
    if records and all(r.mode == "guard" for r in records):
        return [x for x in m if x.id in GUARD_METRICS]  # nothing else exists without the planner
    return m


def _integrity(
    suffix: str,
    which: str,
    runs: Sequence[RunRecord],
    pick: Callable[[RunRecord], AttemptRec | None],
) -> list[Metric]:
    """Q3 coverage, Q4 structure and Q5 connectivity of one attempt per run (`pick`)."""

    def coverage(rs: Sequence[RunRecord]) -> tuple[float | None, int]:
        return _mean(rs, lambda r: _attempt_metric(pick(r), "required_bone_coverage"))

    def structure(rs: Sequence[RunRecord]) -> tuple[float | None, int]:
        return _rate(rs, lambda r: _structure_ok(pick(r)))

    def connected(rs: Sequence[RunRecord]) -> tuple[float | None, int]:
        return _rate(rs, lambda r: _attempt_metric(pick(r), "joint_connectivity") >= 1.0)

    one = Target("=", 1.0)
    return [
        _metric(f"Q3{suffix}", f"Required-bone coverage ({which})", "", runs, coverage, one),
        _metric(f"Q4{suffix}", f"Structural integrity ({which})", "%", runs, structure, one),
        _metric(f"Q5{suffix}", f"Joint connectivity ({which})", "%", runs, connected, one),
    ]


def _consistency(delivered: Sequence[RunRecord]) -> list[Metric]:
    """Q10: runs of the same case land in the same heads-tall bucket, with little spread."""
    per_case: dict[str, list[dict[str, float]]] = defaultdict(list)
    views: dict[str, str | None] = {}
    for r in delivered:
        derived = r.final.derived() if r.final else None
        if derived:
            per_case[r.case_id].append(derived)
            views[r.case_id] = r.view
    groups = {case: runs for case, runs in per_case.items() if len(runs) >= 2}

    def agreement(ids: list[str]) -> float | None:
        if not ids:
            return None
        same = sum(1 for c in ids if len({_bucket(d["heads_tall"]) for d in groups[c]}) == 1)
        return same / len(ids)

    def spread(ids: list[str]) -> float | None:
        if not ids:
            return None
        per = []
        for c in ids:
            ratios = [
                [1 / d["heads_tall"] for d in groups[c]],
                [d["leg_ratio"] for d in groups[c]],
                [d["arm_ratio"] for d in groups[c]],
            ]
            per.append(statistics.fmean(statistics.pstdev(values) for values in ratios))
        return statistics.fmean(per)

    ids = sorted(groups)
    detail = "" if ids else "not measured: needs k >= 2 delivered runs of the same case"
    by = {v: [c for c in ids if views[c] == v] for v in VIEWS}
    return [
        Metric(
            "Q10 bucket",
            "Consistency: same heads-tall bucket across runs",
            "%",
            agreement(ids),
            Target(">=", 0.90),
            {v: agreement(by[v]) for v in VIEWS},
            len(ids),
            detail,
        ),
        Metric(
            "Q10 sigma",
            "Consistency: std-dev of proportion ratios",
            "",
            spread(ids),
            Target("<=", 0.05),
            {v: spread(by[v]) for v in VIEWS},
            len(ids),
            detail,
        ),
    ]


def _efficiency(rigs: Sequence[RunRecord], prices: Prices | None) -> list[Metric]:
    """Q12: latency, tokens and cost per delivered rig (p50, p95, mean)."""

    def pct(value: Callable[[RunRecord], float], q: float) -> Values:
        return lambda rs: (_percentile([value(r) for r in rs], q), len(rs)) if rs else (None, 0)

    def tokens(r: RunRecord) -> float:
        return float(r.input_tokens + r.output_tokens)

    metrics = [
        _metric(
            "Q12 p50 latency", "Latency per rig, p50", "s", rigs, pct(lambda r: r.latency_s, 0.5)
        ),
        _metric(
            "Q12 p95 latency",
            "Latency per rig, p95",
            "s",
            rigs,
            pct(lambda r: r.latency_s, 0.95),
            Target("<=", 30.0),
        ),
        _metric("Q12 p50 tokens", "Tokens per rig, p50", "tokens", rigs, pct(tokens, 0.5)),
        _metric("Q12 p95 tokens", "Tokens per rig, p95", "tokens", rigs, pct(tokens, 0.95)),
    ]
    if prices is None:
        metrics.append(
            Metric(
                "Q12 cost",
                "Cost per rig, mean",
                "$",
                None,
                Target("<=", 0.05),
                detail="not measured: pass --usd-per-mtok-in and --usd-per-mtok-out",
            )
        )
    else:
        metrics.append(
            _metric(
                "Q12 cost",
                "Cost per rig, mean",
                "$",
                rigs,
                lambda rs: _mean(rs, prices.cost),
                Target("<=", 0.05),
            )
        )
    return metrics
