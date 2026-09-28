# Eval report: 20260928-193441

- Planner: openai:gpt-5.4-mini
- Guard: openai:gpt-5.4-mini
- Cases: 58, runs: 174 (k = 3)
- Statuses: success 153, rejected 21

## Metrics (LLD 4.2)

Pass/fail only where the LLD sets a target. `-` means not measured (see Notes) or no target.

| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |
|---|---|---:|---:|---:|---|:-:|---:|---|
| Q1 | First-pass schema validity | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 153 |  |
| Q2 | Final validity rate | 100.0% | 100.0% | 100.0% | ≥ 98.0% | pass | 153 |  |
| Q3 | Required-bone coverage (delivered rigs) | 1 | 1 | 1 | = 1 | pass | 153 |  |
| Q4 | Structural integrity (delivered rigs) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 153 |  |
| Q5 | Joint connectivity (delivered rigs) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 153 |  |
| Q3 first | Required-bone coverage (first attempts) | 1 | 1 | 1 | = 1 | pass | 153 |  |
| Q4 first | Structural integrity (first attempts) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 153 |  |
| Q5 first | Joint connectivity (first attempts) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 153 |  |
| Q6 | Symmetry error (mean, /H) | 9.51e-19 | 0 | 2.021e-18 | ≤ 0.01 | pass | 153 |  |
| Q6b | Depth-order correctness (side view) | 100.0% | - | - | = 100.0% | pass | 72 |  |
| Q7 | Proportion error (mean) | 4.307e-07 | 4.21e-07 | 4.415e-07 | ≤ 0.1 | pass | 153 |  |
| Q8 view | Spec accuracy: view | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 138 |  |
| Q8 style | Spec accuracy: style descriptor | 83.3% | 80.0% | 86.7% | ≥ 90.0% | FAIL | 60 |  |
| Q8 modifier | Spec accuracy: override direction | 79.2% | 66.7% | 91.7% | - | - | 24 |  |
| Q8 extras | Spec accuracy: extra-bone F1 | 0.9857 | 1 | 0.9714 | ≥ 0.85 | pass | 30 |  |
| Q8 bones | Spec accuracy: bone count in range | 96.7% | 93.3% | 100.0% | - | - | 30 |  |
| Q8 assumption | Spec accuracy: assumption recorded (vague prompts) | 100.0% | 100.0% | - | - | - | 15 |  |
| Q9 recall | Guardrail recall (should-reject rejected) | 100.0% | - | - | ≥ 95.0% | pass | 18 | 18/18 also with the expected category |
| Q9 precision | Guardrail precision (rejections that were right) | 100.0% | - | - | - | - | 21 |  |
| Q9 clamp | Rejected or clamped (reject_or_clamp cases) | 100.0% | - | - | - | - | 3 |  |
| Q9 false-reject | False-reject rate (valid prompts) | 0.0% | - | - | ≤ 2.0% | pass | 153 |  |
| Q9b | Prompt-guardrail adherence (first attempts caught by code) | 0.0% | 0.0% | 0.0% | ≤ 5.0% | pass | 153 |  |
| Q10 bucket | Consistency: same heads-tall bucket across runs | 80.4% | 85.2% | 75.0% | ≥ 90.0% | FAIL | 51 |  |
| Q10 sigma | Consistency: std-dev of proportion ratios | 0.00806 | 0.004147 | 0.01246 | ≤ 0.05 | pass | 51 |  |
| Q11 | Convergence: mean iterations to success | 1 | 1 | 1 | ≤ 1.5 | pass | 153 |  |
| Q11 pass@1 | pass@1 (success on the first attempt) | 100.0% | 100.0% | 100.0% | - | - | 153 |  |
| Q11 pass@3 | pass@3 (success within 3 attempts) | 100.0% | 100.0% | 100.0% | - | - | 153 |  |
| Q12 p50 latency | Latency per rig, p50 | 7.4s | 7.3s | 7.7s | - | - | 153 |  |
| Q12 p95 latency | Latency per rig, p95 | 10.0s | 9.5s | 10.1s | ≤ 30.0s | pass | 153 |  |
| Q12 p50 tokens | Tokens per rig, p50 | 41,438 | 40,350 | 50,810 | - | - | 153 |  |
| Q12 p95 tokens | Tokens per rig, p95 | 61,718 | 63,374 | 60,318 | - | - | 153 |  |
| Q12 cost | Cost per rig, mean | - | - | - | ≤ $0.0500 | - | 0 | not measured: pass --usd-per-mtok-in and --usd-per-mtok-out |
| Q13 | Unity import success | - | - | - | = 100.0% | - | 0 | not measured: run with --unity |

## Runs by category

| Category | Runs | success | best_effort | accepted | rejected | error |
|---|---:|---:|---:|---:|---:|---:|
| standard | 30 | 30 | 0 | 0 | 0 | 0 |
| view_selection | 24 | 24 | 0 | 0 | 0 | 0 |
| stylized | 30 | 30 | 0 | 0 | 0 | 0 |
| modifier | 24 | 24 | 0 | 0 | 0 | 0 |
| accessory | 30 | 30 | 0 | 0 | 0 | 0 |
| ambiguous | 15 | 15 | 0 | 0 | 0 | 0 |
| adversarial | 21 | 0 | 0 | 0 | 21 | 0 |

## Failed expectations (19 runs)

Seeds the failure taxonomy (LLD 4.3).

- `std_fisherman` run 2 (standard): 21 bones, expected [14, 20]
- `sty_toddler` run 2 (stylized): heads_tall 6 not in [-, 5]
- `sty_lanky_elf` run 1 (stylized): heads_tall 6.28 not in [7.5, -]; leg_ratio 0.461 not in [0.48, -]
- `sty_lanky_elf` run 2 (stylized): heads_tall 6.29 not in [7.5, -]; leg_ratio 0.46 not in [0.48, -]
- `sty_lanky_elf` run 3 (stylized): heads_tall 6.28 not in [7.5, -]; leg_ratio 0.461 not in [0.48, -]
- `sty_fashion_model` run 1 (stylized): heads_tall 6 not in [8, -]
- `sty_fashion_model` run 2 (stylized): heads_tall 6 not in [8, -]
- `sty_fashion_model` run 3 (stylized): heads_tall 7.28 not in [8, -]
- `sty_cartoon_kid` run 1 (stylized): heads_tall 6 not in [-, 5.5]
- `sty_cartoon_kid` run 2 (stylized): heads_tall 6 not in [-, 5.5]
- `sty_cartoon_kid` run 3 (stylized): heads_tall 6 not in [-, 5.5]
- `mod_broad_shoulders` run 1 (modifier): shoulder_width_hu 2.3 not in [2.4, -]
- `mod_big_head` run 2 (modifier): heads_tall 7.5 not in [-, 6]
- `mod_tiny_head` run 1 (modifier): heads_tall 2 not in [8.5, -]
- `mod_tiny_head` run 2 (modifier): heads_tall 2.21 not in [8.5, -]
- `mod_tiny_head` run 3 (modifier): heads_tall 2 not in [8.5, -]
- `acc_cat_warrior` run 1 (accessory): extras F1 0.86: expected ears x1, held x1, tail x1; got ears x2, held x1, tail x1
- `acc_cat_warrior` run 2 (accessory): extras F1 0.86: expected ears x1, held x1, tail x1; got ears x2, held x1, tail x1
- `acc_cat_warrior` run 3 (accessory): extras F1 0.86: expected ears x1, held x1, tail x1; got ears x2, held x1, tail x1
