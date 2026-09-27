# Eval report: 20260927-210901

- Mode: guard only (the input guard alone; the planner was not run)
- Guard: openai:gpt-5.4-nano
- Cases: 58, runs: 174 (k = 3)
- Statuses: accepted 148, rejected 26

## Metrics (LLD 4.2)

Pass/fail only where the LLD sets a target. `-` means not measured (see Notes) or no target.

| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |
|---|---|---:|---:|---:|---|:-:|---:|---|
| Q9 recall | Guardrail recall (should-reject rejected) | 100.0% | - | - | ≥ 95.0% | pass | 18 | 18/18 also with the expected category |
| Q9 precision | Guardrail precision (rejections that were right) | 80.8% | - | - | - | - | 26 |  |
| Q9 clamp | Rejected or clamped (reject_or_clamp cases) | 100.0% | - | - | - | - | 3 |  |
| Q9 false-reject | False-reject rate (valid prompts) | 3.3% | - | - | ≤ 2.0% | FAIL | 153 |  |

## Runs by category

| Category | Runs | success | best_effort | accepted | rejected | error |
|---|---:|---:|---:|---:|---:|---:|
| standard | 30 | 0 | 0 | 30 | 0 | 0 |
| view_selection | 24 | 0 | 0 | 22 | 2 | 0 |
| stylized | 30 | 0 | 0 | 29 | 1 | 0 |
| modifier | 24 | 0 | 0 | 23 | 1 | 0 |
| accessory | 30 | 0 | 0 | 29 | 1 | 0 |
| ambiguous | 15 | 0 | 0 | 15 | 0 | 0 |
| adversarial | 21 | 0 | 0 | 0 | 21 | 0 |

## Failed expectations (5 runs)

Seeds the failure taxonomy (LLD 4.3).

- `view_metroidvania` run 1 (view_selection): rejected as unsupported_view, but it is a valid request
- `view_metroidvania` run 3 (view_selection): rejected as unsupported_view, but it is a valid request
- `sty_fashion_model` run 3 (stylized): rejected as ambiguous, but it is a valid request
- `mod_long_legged_dancer` run 1 (modifier): rejected as ambiguous, but it is a valid request
- `acc_cat_warrior` run 1 (accessory): rejected as non_humanoid, but it is a valid request
