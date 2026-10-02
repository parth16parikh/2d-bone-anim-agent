# Animation eval report: 20261002-175453

- Planner: openai:gpt-5.4-mini
- Guard: openai:gpt-5.4-mini
- Cases: 43, runs: 129 (k = 3)
- Statuses: success 99, rejected 27, error 3

## Metrics

Pass/fail only where a target is set. `-` means not measured (see Notes) or no target.

| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |
|---|---|---:|---:|---:|---|:-:|---:|---|
| A1 | First-pass schema validity | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 102 |  |
| A2 | Final validity (valid requests end in a passing clip) | 100.0% | 100.0% | 100.0% | ≥ 98.0% | pass | 93 |  |
| A3 | Clip accuracy (the planner chose the expected clip) | 94.1% | 77.8% | 100.0% | ≥ 95.0% | FAIL | 102 |  |
| A4 | Setting directions (each expected up/down/same) | 95.1% | 83.3% | 96.0% | ≥ 90.0% | pass | 81 |  |
| A4 runs | Runs with every setting direction right | 93.9% | 83.3% | 95.0% | - | - | 66 |  |
| A5 recall | Guard recall (unsupported and adversarial refused) | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 27 | 27/27 also with the expected category |
| A5 false-reject | False rejections (valid requests refused) | 0.0% | 0.0% | 0.0% | ≤ 2.0% | pass | 102 |  |
| A6 | View rule (front-view walk/run/backflip stopped, nothing swapped or written) | 33.3% | 33.3% | - | = 100.0% | FAIL | 9 |  |
| A7 pass@1 | Passed on the first attempt | 100.0% | 100.0% | 100.0% | - | - | 93 |  |
| A7 attempts | Mean attempts to a passing clip | 1 | 1 | 1 | ≤ 1.5 | pass | 93 |  |
| A7 slip | Worst foot slip of a delivered clip (share of height per frame) | 4.695e-05 | 9.72e-09 | 4.695e-05 | - | - | 93 |  |
| A7 floor | Worst body depth below the floor, delivered clips (share of height) | 0 | 0 | 0 | - | - | 93 |  |
| A8 clip | Consistency: the same clip across runs | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 34 |  |
| A8 directions | Consistency: the same direction verdict across runs | 96.3% | 50.0% | 100.0% | ≥ 90.0% | pass | 34 |  |
| A9 p50 latency | Latency per request, p50 | 4.2s | 4.3s | 4.2s | - | - | 102 |  |
| A9 p95 latency | Latency per request, p95 | 6.4s | 5.6s | 7.5s | ≤ 30.0s | pass | 102 |  |
| A9 p50 tokens | Tokens per request, p50 | 4,632 | 4,557 | 4,643 | - | - | 102 |  |
| A9 p95 tokens | Tokens per request, p95 | 7,184 | 7,185 | 4,704 | - | - | 102 |  |
| A9 cost | Cost per request, mean | - | - | - | ≤ $0.0500 | - | 0 | not measured: pass --usd-per-mtok-in and --usd-per-mtok-out |

## Runs by category

| Category | Runs | success | best_effort | rejected | error |
|---|---:|---:|---:|---:|---:|
| neutral | 18 | 18 | 0 | 0 | 0 |
| mood | 30 | 30 | 0 | 0 | 0 |
| modifier | 24 | 24 | 0 | 0 | 0 |
| backflip | 15 | 15 | 0 | 0 | 0 |
| view_rule | 15 | 12 | 0 | 0 | 3 |
| unsupported | 18 | 0 | 0 | 18 | 0 |
| adversarial | 9 | 0 | 0 | 9 | 0 |

## Failed expectations (10 runs)

- `mood_fidgety` run 1 (mood, "nervously fidgeting while waiting"): speed 1 is not up [chose idle: speed 1, stride 1, bounce 0.8, arms 0.6, knees 1, lean 0]
- `mod_short_quick` run 1 (modifier, "walk with short, quick steps"): speed 0.95 is not up [chose walk: speed 0.95, stride 0.7, bounce 0.8, arms 0.8, knees 1.15, lean 2]
- `mod_short_quick` run 2 (modifier, "walk with short, quick steps"): speed 1 is not up [chose walk: speed 1, stride 0.8, bounce 0.9, arms 0.8, knees 1.1, lean 0]
- `mod_short_quick` run 3 (modifier, "walk with short, quick steps"): speed 1 is not up [chose walk: speed 1, stride 0.75, bounce 0.8, arms 0.9, knees 1.2, lean 0]
- `view_walk_front` run 1 (view_rule, "walk forward"): clip: expected walk, the planner chose idle; should stop for the view, ended success; a clip was written although the rig cannot play it [chose idle: speed 1, stride 1, bounce 1, arms 1, knees 1, lean 0]
- `view_walk_front` run 2 (view_rule, "walk forward"): clip: expected walk, the planner chose idle; should stop for the view, ended success; a clip was written although the rig cannot play it [chose idle: speed 1, stride 1, bounce 1, arms 1, knees 1, lean 0]
- `view_walk_front` run 3 (view_rule, "walk forward"): clip: expected walk, the planner chose idle; should stop for the view, ended success; a clip was written although the rig cannot play it [chose idle: speed 1, stride 1, bounce 1, arms 1, knees 1, lean 0]
- `view_run_front` run 1 (view_rule, "run as fast as you can"): clip: expected run, the planner chose idle; should stop for the view, ended success; a clip was written although the rig cannot play it [chose idle: speed 1, stride 1, bounce 1, arms 1, knees 1, lean 0]
- `view_run_front` run 2 (view_rule, "run as fast as you can"): clip: expected run, the planner chose idle; should stop for the view, ended success; a clip was written although the rig cannot play it [chose idle: speed 1, stride 1, bounce 1, arms 1, knees 1, lean 0]
- `view_run_front` run 3 (view_rule, "run as fast as you can"): clip: expected run, the planner chose idle; should stop for the view, ended success; a clip was written although the rig cannot play it [chose idle: speed 1.2, stride 1, bounce 1, arms 0.8, knees 1, lean 0]
