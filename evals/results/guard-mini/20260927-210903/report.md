# Eval report: 20260927-210903

- Mode: guard only (the input guard alone; the planner was not run)
- Guard: openai:gpt-5.4-mini
- Cases: 58, runs: 174 (k = 3)
- Statuses: accepted 153, rejected 21

## Metrics (LLD 4.2)

Pass/fail only where the LLD sets a target. `-` means not measured (see Notes) or no target.

| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |
|---|---|---:|---:|---:|---|:-:|---:|---|
| Q9 recall | Guardrail recall (should-reject rejected) | 100.0% | - | - | ≥ 95.0% | pass | 18 | 18/18 also with the expected category |
| Q9 precision | Guardrail precision (rejections that were right) | 100.0% | - | - | - | - | 21 |  |
| Q9 clamp | Rejected or clamped (reject_or_clamp cases) | 100.0% | - | - | - | - | 3 |  |
| Q9 false-reject | False-reject rate (valid prompts) | 0.0% | - | - | ≤ 2.0% | pass | 153 |  |

## Runs by category

| Category | Runs | success | best_effort | accepted | rejected | error |
|---|---:|---:|---:|---:|---:|---:|
| standard | 30 | 0 | 0 | 30 | 0 | 0 |
| view_selection | 24 | 0 | 0 | 24 | 0 | 0 |
| stylized | 30 | 0 | 0 | 30 | 0 | 0 |
| modifier | 24 | 0 | 0 | 24 | 0 | 0 |
| accessory | 30 | 0 | 0 | 30 | 0 | 0 |
| ambiguous | 15 | 0 | 0 | 15 | 0 | 0 |
| adversarial | 21 | 0 | 0 | 0 | 21 | 0 |

## Failed expectations (0 runs)

Seeds the failure taxonomy (LLD 4.3).

None.
