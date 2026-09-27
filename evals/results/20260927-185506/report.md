# Eval report: 20260927-185506

- Model: openai:gpt-5.4-mini
- Cases: 58, runs: 174 (k = 3)
- Statuses: success 140, rejected 34

## Metrics (LLD 4.2)

Pass/fail only where the LLD sets a target. `-` means not measured (see Notes) or no target.

| ID | Metric | Overall | Front | Side | Target | Result | n | Notes |
|---|---|---:|---:|---:|---|:-:|---:|---|
| Q1 | First-pass schema validity | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 140 |  |
| Q2 | Final validity rate | 91.5% | 100.0% | 100.0% | ≥ 98.0% | FAIL | 153 |  |
| Q3 | Required-bone coverage (delivered rigs) | 1 | 1 | 1 | = 1 | pass | 140 |  |
| Q4 | Structural integrity (delivered rigs) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 140 |  |
| Q5 | Joint connectivity (delivered rigs) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 140 |  |
| Q3 first | Required-bone coverage (first attempts) | 1 | 1 | 1 | = 1 | pass | 140 |  |
| Q4 first | Structural integrity (first attempts) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 140 |  |
| Q5 first | Joint connectivity (first attempts) | 100.0% | 100.0% | 100.0% | = 100.0% | pass | 140 |  |
| Q6 | Symmetry error (mean, /H) | 9.329e-19 | 0 | 2.009e-18 | ≤ 0.01 | pass | 140 |  |
| Q6b | Depth-order correctness (side view) | 100.0% | - | - | = 100.0% | pass | 65 |  |
| Q7 | Proportion error (mean) | 4.264e-07 | 4.159e-07 | 4.385e-07 | ≤ 0.1 | pass | 140 |  |
| Q8 view | Spec accuracy: view | 100.0% | 100.0% | 100.0% | ≥ 95.0% | pass | 125 |  |
| Q8 style | Spec accuracy: style descriptor | 84.5% | 80.0% | 89.3% | ≥ 90.0% | FAIL | 58 |  |
| Q8 modifier | Spec accuracy: override direction | 72.7% | 58.3% | 90.0% | - | - | 22 |  |
| Q8 extras | Spec accuracy: extra-bone F1 | 1 | 1 | 1 | ≥ 0.85 | pass | 21 |  |
| Q8 bones | Spec accuracy: bone count in range | 96.7% | 100.0% | 93.3% | - | - | 30 |  |
| Q8 assumption | Spec accuracy: assumption recorded (vague prompts) | 100.0% | 100.0% | - | - | - | 15 |  |
| Q9 recall | Guardrail recall (should-reject rejected) | 100.0% | - | - | ≥ 95.0% | pass | 18 | 18/18 also with the expected category |
| Q9 precision | Guardrail precision (rejections that were right) | 61.8% | - | - | - | - | 34 |  |
| Q9 clamp | Rejected or clamped (reject_or_clamp cases) | 100.0% | - | - | - | - | 3 |  |
| Q9 false-reject | False-reject rate (valid prompts) | 8.5% | - | - | ≤ 2.0% | FAIL | 153 |  |
| Q9b | Prompt-guardrail adherence (first attempts caught by code) | 0.0% | 0.0% | 0.0% | ≤ 5.0% | pass | 140 |  |
| Q10 bucket | Consistency: same heads-tall bucket across runs | 89.1% | 88.0% | 90.5% | ≥ 90.0% | FAIL | 46 |  |
| Q10 sigma | Consistency: std-dev of proportion ratios | 0.004566 | 0.004714 | 0.004391 | ≤ 0.05 | pass | 46 |  |
| Q11 | Convergence: mean iterations to success | 1 | 1 | 1 | ≤ 1.5 | pass | 140 |  |
| Q11 pass@1 | pass@1 (success on the first attempt) | 91.5% | 100.0% | 100.0% | - | - | 153 |  |
| Q11 pass@3 | pass@3 (success within 3 attempts) | 91.5% | 100.0% | 100.0% | - | - | 153 |  |
| Q12 p50 latency | Latency per rig, p50 | 7.7s | 6.9s | 7.8s | - | - | 140 |  |
| Q12 p95 latency | Latency per rig, p95 | 11.8s | 10.8s | 11.9s | ≤ 30.0s | pass | 140 |  |
| Q12 p50 tokens | Tokens per rig, p50 | 40,557 | 40,160 | 40,965 | - | - | 140 |  |
| Q12 p95 tokens | Tokens per rig, p95 | 60,722 | 61,067 | 60,532 | - | - | 140 |  |
| Q12 cost | Cost per rig, mean | - | - | - | ≤ $0.0500 | - | 0 | not measured: pass --usd-per-mtok-in and --usd-per-mtok-out |
| Q13 | Unity import success | - | - | - | = 100.0% | - | 0 | not measured: run with --unity |

## Runs by category

| Category | Runs | success | best_effort | rejected | error |
|---|---:|---:|---:|---:|---:|
| standard | 30 | 30 | 0 | 0 | 0 |
| view_selection | 24 | 24 | 0 | 0 | 0 |
| stylized | 30 | 28 | 0 | 2 | 0 |
| modifier | 24 | 22 | 0 | 2 | 0 |
| accessory | 30 | 21 | 0 | 9 | 0 |
| ambiguous | 15 | 15 | 0 | 0 | 0 |
| adversarial | 21 | 0 | 0 | 21 | 0 |

## Failed expectations (29 runs)

Seeds the failure taxonomy (LLD 4.3).

- `std_nurse` run 3 (standard): 22 bones, expected [14, 20]
- `sty_toddler` run 1 (stylized): rejected as non_humanoid, but it is a valid request
- `sty_toddler` run 3 (stylized): rejected as ambiguous, but it is a valid request
- `sty_lanky_elf` run 1 (stylized): heads_tall 6.28 not in [7.5, -]; leg_ratio 0.461 not in [0.48, -]
- `sty_lanky_elf` run 2 (stylized): heads_tall 6.29 not in [7.5, -]; leg_ratio 0.46 not in [0.48, -]
- `sty_lanky_elf` run 3 (stylized): heads_tall 6.26 not in [7.5, -]; leg_ratio 0.463 not in [0.48, -]
- `sty_fashion_model` run 1 (stylized): heads_tall 6 not in [8, -]
- `sty_fashion_model` run 2 (stylized): heads_tall 6 not in [8, -]
- `sty_fashion_model` run 3 (stylized): heads_tall 6 not in [8, -]
- `sty_cartoon_kid` run 1 (stylized): heads_tall 6 not in [-, 5.5]
- `sty_cartoon_kid` run 2 (stylized): heads_tall 6 not in [-, 5.5]
- `sty_cartoon_kid` run 3 (stylized): heads_tall 6 not in [-, 5.5]
- `mod_long_legged_dancer` run 3 (modifier): leg_ratio 0.428 not in [0.51, -]
- `mod_broad_shoulders` run 1 (modifier): shoulder_width_hu 2.3 not in [2.4, -]
- `mod_narrow_shoulders` run 3 (modifier): shoulder_width_hu 2 not in [-, 1.7]
- `mod_tiny_head` run 1 (modifier): heads_tall 2 not in [8.5, -]
- `mod_tiny_head` run 2 (modifier): heads_tall 2.43 not in [8.5, -]
- `mod_tiny_head` run 3 (modifier): heads_tall 2.62 not in [8.5, -]
- `mod_short_legs` run 1 (modifier): rejected as non_humanoid, but it is a valid request
- `mod_short_legs` run 3 (modifier): rejected as non_humanoid, but it is a valid request
- `acc_fox_ears_tail` run 1 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_fox_ears_tail` run 2 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_fox_ears_tail` run 3 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_demon` run 1 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_demon` run 2 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_demon` run 3 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_cat_warrior` run 1 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_cat_warrior` run 2 (accessory): rejected as non_humanoid, but it is a valid request
- `acc_cat_warrior` run 3 (accessory): rejected as non_humanoid, but it is a valid request
