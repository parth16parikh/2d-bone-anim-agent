# Input guard: gpt-5.4-nano vs gpt-5.4-mini

**Decision: the input guard uses `gpt-5.4-mini`** (`guard_model` in `src/rig_agent/config.py`).
With the same instructions and the same 174 prompts, nano wrongly rejected 3.3% of valid
requests (target ≤ 2%) while mini rejected none, and both caught every out-of-scope request.
Latency is practically the same.

Measured on 2026-09-27.

## Why this was measured

The first full eval (`evals/results/20260927-185506`: planner gpt-5.4-mini, guard gpt-5.4-nano)
passed guard recall (100%) but failed the **false-reject rate: 8.5%** (13 of 153 valid runs,
target ≤ 2%). That alone pulled the final validity rate (Q2) down to 91.5% (target ≥ 98%).

| Prompt | Rejected as | Runs |
|---|---|---|
| a fox girl with pointed ears and a fluffy tail | non_humanoid | 3/3 |
| a demon with two horns, bat wings and a long tail | non_humanoid | 3/3 |
| a cat warrior with ears, a tail and a spear | non_humanoid | 3/3 |
| a goblin with very short legs | non_humanoid | 2/3 |
| a toddler | non_humanoid / ambiguous | 2/3 |

11 of the 13 were **people with animal traits**. The guard's instructions caused this more than
the model did: `non_humanoid` was defined as "animals…", every rejection example was an animal,
and nothing said that animal ears, a tail, wings or horns on a person are fine (the rigs support
them as extra bones). Every model reads those instructions, so the instructions were fixed first
and the models compared afterwards.

## What changed before the comparison

- **Guard instructions** (`src/rig_agent/guardrails/rules.yaml`, `input_guard.py`):
  - accept any age (children included), fantasy races (goblins, orcs, demons, angels) and people
    with animal ears, tails, wings or horns;
  - `non_humanoid` now means "a body that is not a person on two legs", and says outright that
    animal traits on a person don't count;
  - new examples: "a wolf-eared ranger with a bushy tail" → ok, "an orc brute with tusks" → ok,
    "a small child with a backpack" → ok, "a wolf" → non_humanoid.
- **No leaks between the guard and the eval:** four golden prompts were word-for-word copies of
  the guard's own examples, which flattered recall. They were reworded with the same intent (for
  example "a centaur warrior" → "a centaur archer with a longbow"). A test now fails if any golden
  prompt appears verbatim in the guard prompt, and the new examples above deliberately differ
  from the golden prompts.

## Method

The guard alone was run on the golden set (`evals/golden.yaml`: 58 prompts × 3 runs = 174 per
model; 153 valid and 21 out of scope). Both runs used the same fixed instructions:

```bash
uv run python -m evals.run --guard-only --guard-model gpt-5.4-nano
uv run python -m evals.run --guard-only --guard-model gpt-5.4-mini
```

`--guard-only` calls only the input guard (no planner, no rigs), so a comparison costs cents.
Metrics follow LLD 4.2 (Q9).

## Results

| Guard | Recall (target ≥ 95%) | False rejections (target ≤ 2%) | Precision | Median latency | p95 latency |
|---|---|---|---|---|---|
| gpt-5.4-nano | 100% (21/21) | **3.3%** (5/153), FAIL | 80.8% | 1.09 s | 1.50 s |
| gpt-5.4-mini | 100% (21/21) | **0%** (0/153), pass | 100% | 1.14 s | 1.91 s |

- **Recall:** both models rejected every out-of-scope prompt with the expected category, 3/3 runs
  each: horse, centaur and spider as non_humanoid, the story as off_topic, isometric as
  unsupported_view, the 500-bones request and the prompt leak as manipulation.
- **Precision:** the share of all rejections that were right. Nano's five false rejections cost
  it here (21 right out of 26).
- **Latency:** 171 of the 174 prompts reached the model; three were stopped by the deterministic
  pre-checks first.

### Nano's remaining false rejections

| Prompt | Rejected as | Runs |
|---|---|---|
| an explorer for a metroidvania game, seen from the side | unsupported_view | 2/3 |
| a fashion-illustration model | ambiguous | 1/3 |
| a very long-legged dancer | ambiguous | 1/3 |
| a cat warrior with ears, a tail and a spear | non_humanoid | 1/3 |

The instruction fix did most of the work on nano. False rejections fell from 8.5% to 3.3%: the
fox girl, demon, goblin and toddler went from repeated rejections to none, and the cat warrior
from 3/3 to 1/3. What remains doesn't follow a pattern that a further instruction change would
clearly fix. The prompts are unambiguous, and nano rejects them only in some runs.

## Cost

The guard is one short request per user prompt, while the planner (already mini) makes several
longer ones with tool calls, so the guard is a small part of a rig's cost either way. Guard tokens
aren't currently recorded (`UsageTotals` only counts the guard's request), so the exact
difference isn't measured here.

## Raw results

Timestamped runs in the git-ignored `evals/results/` folder. Each has `report.md`,
`metrics.json` and `records.jsonl`, and `--rescore` recomputes the metrics without model calls.

- `evals/results/20260927-185506/`: the first full eval (old instructions, nano)
- `evals/results/guard-nano/20260927-210901/`: guard only, fixed instructions, nano
- `evals/results/guard-mini/20260927-210903/`: guard only, fixed instructions, mini

## Still to do

A full eval (`uv run python -m evals.run`) with the new guard, to confirm Q2 ≥ 98% end to end.
The only full run so far predates both the instruction fix and the switch to mini.
