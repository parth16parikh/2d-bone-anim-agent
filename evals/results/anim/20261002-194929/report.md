# Animation eval report: 20261002-194929

- Planner: openai:gpt-5.4-mini
- Guard: openai:gpt-5.4-mini
- Cases: 13, runs: 39 (k = 3)
- Statuses: success 30, error 9

## Metrics

Pass/fail only where a target is set. `-` means not measured (see Notes) or no target.

| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |
|---|---|---:|---:|---:|---|:-:|---:|---|
| A1 | First-pass schema validity | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 39 |  |
| A2 | Final validity (valid requests end in a passing clip) | 100.0% | 100.0% | 100.0% | ≥ 98.0% | pass | 30 |  |
| A3 | Clip accuracy (the planner chose the expected clip) | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 39 |  |
| A4 | Setting directions (each expected up/down/same) | 96.3% | - | 96.3% | ≥ 90.0% | pass | 27 |  |
| A4 runs | Runs with every setting direction right | 95.8% | - | 95.8% | - | - | 24 |  |
| A5 recall | Guard recall (unsupported and adversarial refused) | - | - | - | ≥ 95.0% | - | 0 | 0/0 also with the expected category |
| A5 false-reject | False rejections (valid requests refused) | 0.0% | 0.0% | 0.0% | ≤ 2.0% | pass | 39 |  |
| A6 | View rule (front-view walk/run/backflip stopped, nothing swapped or written) | 100.0% | 100.0% | - | = 100.0% | pass | 9 |  |
| A7 pass@1 | Passed on the first attempt | 100.0% | 100.0% | 100.0% | - | - | 30 |  |
| A7 attempts | Mean attempts to a passing clip | 1 | 1 | 1 | ≤ 1.5 | pass | 30 |  |
| A7 slip | Worst foot slip of a delivered clip (share of height per frame) | 3.821e-06 | 8.467e-09 | 3.821e-06 | - | - | 30 |  |
| A7 floor | Worst body depth below the floor, delivered clips (share of height) | 0 | 0 | 0 | - | - | 30 |  |
| A8 clip | Consistency: the same clip across runs | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 13 |  |
| A8 directions | Consistency: the same direction verdict across runs | 88.9% | - | 88.9% | ≥ 90.0% | FAIL | 13 |  |
| A9 p50 latency | Latency per request, p50 | 4.0s | 3.9s | 4.1s | - | - | 39 |  |
| A9 p95 latency | Latency per request, p95 | 6.9s | 4.9s | 6.9s | ≤ 30.0s | pass | 39 |  |
| A9 p50 tokens | Tokens per request, p50 | 4,712 | 4,651 | 4,732 | - | - | 39 |  |
| A9 p95 tokens | Tokens per request, p95 | 7,336 | 7,237 | 7,385 | - | - | 39 |  |
| A9 cost | Cost per request, mean | - | - | - | ≤ $0.0500 | - | 0 | not measured: pass --usd-per-mtok-in and --usd-per-mtok-out |

## Runs by category

| Category | Runs | success | best_effort | rejected | error |
|---|---:|---:|---:|---:|---:|
| modifier | 24 | 24 | 0 | 0 | 0 |
| view_rule | 15 | 6 | 0 | 0 | 9 |

## Failed expectations (1 runs)

- `mod_lean_back` run 2 (modifier, "walk upright, leaning slightly back"): lean_deg -2 is not down [chose walk: speed 1, stride 1, bounce 0.8, arms 0.8, knees 1, lean -2]
