# Animation eval report: 20261002-174641

- Planner: openai:gpt-5.4-mini
- Guard: openai:gpt-5.4-mini
- Cases: 10, runs: 10 (k = 1)
- Statuses: success 9, rejected 1

## Metrics

Pass/fail only where a target is set. `-` means not measured (see Notes) or no target.

| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |
|---|---|---:|---:|---:|---|:-:|---:|---|
| A1 | First-pass schema validity | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 9 |  |
| A2 | Final validity (valid requests end in a passing clip) | 90.0% | 100.0% | 87.5% | ≥ 98.0% | FAIL | 10 |  |
| A3 | Clip accuracy (the planner chose the expected clip) | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 9 |  |
| A4 | Setting directions (each expected up/down/same) | 100.0% | 100.0% | 100.0% | ≥ 90.0% | pass | 13 |  |
| A4 runs | Runs with every setting direction right | 100.0% | 100.0% | 100.0% | - | - | 9 |  |
| A5 recall | Guard recall (unsupported and adversarial refused) | - | - | - | ≥ 95.0% | - | 0 | 0/0 also with the expected category |
| A5 false-reject | False rejections (valid requests refused) | 10.0% | 0.0% | 12.5% | ≤ 2.0% | FAIL | 10 |  |
| A6 | View rule (front-view walk/run/backflip stopped, nothing swapped or written) | - | - | - | = 100.0% | - | 0 |  |
| A7 pass@1 | Passed on the first attempt | 90.0% | 100.0% | 87.5% | - | - | 10 |  |
| A7 attempts | Mean attempts to a passing clip | 1 | 1 | 1 | ≤ 1.5 | pass | 9 |  |
| A7 slip | Worst foot slip of a delivered clip (share of height per frame) | 2.572e-05 | 8.87e-09 | 2.572e-05 | - | - | 9 |  |
| A7 floor | Worst body depth below the floor, delivered clips (share of height) | 0 | 0 | 0 | - | - | 9 |  |
| A8 clip | Consistency: the same clip across runs | - | - | - | ≥ 95.0% | - | 0 | not measured: needs k >= 2 runs of the same case |
| A8 directions | Consistency: the same direction verdict across runs | - | - | - | ≥ 90.0% | - | 0 | not measured: needs k >= 2 runs of the same case |
| A9 p50 latency | Latency per request, p50 | 4.8s | 4.4s | 5.0s | - | - | 9 |  |
| A9 p95 latency | Latency per request, p95 | 9.7s | 4.7s | 10.4s | ≤ 30.0s | pass | 9 |  |
| A9 p50 tokens | Tokens per request, p50 | 4,699 | 4,594 | 4,699 | - | - | 9 |  |
| A9 p95 tokens | Tokens per request, p95 | 4,715 | 4,616 | 4,715 | - | - | 9 |  |
| A9 cost | Cost per request, mean | - | - | - | ≤ $0.0500 | - | 0 | not measured: pass --usd-per-mtok-in and --usd-per-mtok-out |

## Runs by category

| Category | Runs | success | best_effort | rejected | error |
|---|---:|---:|---:|---:|---:|
| mood | 10 | 9 | 0 | 1 | 0 |

## Failed expectations (1 runs)

- `mood_childlike` run 1 (mood, "a happy kid skipping along"): refused as unsupported_motion, but it is a valid request
