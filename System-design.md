# High-Level Design: 2D Humanoid Rig Agent for Unity

**Target engine:** Unity (2D Animation package)

---

## 1. Problem Statement

Before a 2D character can be animated in Unity, someone has to rig it: build a bone hierarchy and place every joint. This is slow, repetitive work that needs rigging experience, even though most humanoid rigs share the same structure and differ mainly in proportions and a few extra bones (hair, cape, weapon).

> **Given a short text description of a humanoid character, the agent produces a valid, anatomically plausible 2D bone hierarchy for either a front-facing or a side-view (side-scroller) character, in a neutral rest pose, and delivers it to Unity.** (Goal 1)

> **Given such a rig and a short description of a motion, the agent produces a validated animation clip (idle, walk, run or a backflip) and plays it on the rig in Unity.** (Goal 2)

| | |
|---|---|
| **Input** | A text prompt, e.g. *"chibi knight with a big sword"*, and an optional view type (`front` or `side`). Without it, the agent infers the view from the prompt and defaults to front. |
| **Output** | `skeleton.json` (a schema-validated bone hierarchy with its IK chains) and a validation report. Optionally, the same skeleton is built live in an open Unity Editor, with native 2D bones, IK on the arms and legs and placeholder shapes, and saved as a prefab. For Goal 2: an animation clip (`animations/<name>.json`) with its report, and in Unity an `.anim` on the rig's Animator. |
| **In scope** | Bipedal humanoids in two view types (front-facing and side-scroller side view; details in LLD §2.5), free-form character style (presets such as realistic, heroic, stylized and chibi are starting points), optional accessory bones |
| **Out of scope** | Non-humanoids, 3/4 and top-down views, sprite or image generation, skin weights, motions other than idle, walk, run and a standing backflip |

---

## 2. Architecture

### 2.1 System overview

```mermaid
flowchart LR
    U[User prompt] --> IG[Input guardrail]
    IG -->|rejected| RJ[Rejection + suggested rephrasing]
    IG -->|accepted| PA

    subgraph Orchestrator
        PA["Planner agent<br/>(LLM, ReAct)"]
        SB["Skeleton builder<br/>(deterministic)"]
        V["Validator<br/>(deterministic)"]
        EX[Exporter]
        PA --> SB --> V
        V -->|fail, retries left| PA
        V -->|pass| EX
        V -->|retries exhausted| BE[Best-effort rig<br/>marked not import-ready]
    end

    PA <--> T[(Knowledge tools:<br/>vocabulary, presets,<br/>dry-run validation)]
    EX --> J[skeleton.json + report]
    BE --> J
    J --> CI[Unity Editor importer]
    EX -->|Unity mode| UM[Unity MCP]
    UM --> ED[Open Unity Editor]
```

### 2.2 Components

| Component | Responsibility |
|---|---|
| **Input guardrail** | Code checks (empty, too long, prompt injection), then a small LLM classifier. Accepts humanoid rig requests, even vague ones; rejects the rest with a reason and a suggested rephrasing. |
| **Orchestrator** | Runs the flow as a graph: at most 3 planning attempts within budgets (model calls, tokens, tool calls, time); if all fail, returns the best attempt with its report. |
| **Planner agent** | A ReAct agent: it reasons, calls tools and observes the results. It interprets the prompt and returns a rig specification: view type, a style label with a starting preset and proportions, optional and accessory bones, and the assumptions it made. |
| **Knowledge tools** | Give the planner the bone vocabulary, view rules and proportion presets, and let it test a draft specification before answering. This knowledge is only a few KB, so it lives in the prompt and tools; no RAG is needed for Goal 1. |
| **Skeleton builder** | Computes joint positions, bone lengths and parent-relative transforms from the specification, using the layout for the chosen view (mirrored limbs for front view; overlapping, depth-ordered limbs for side view). |
| **Validator** | Checks structure (one root, no cycles, required bones present) and geometry (connected joints, view-appropriate symmetry and draw order, plausible proportions); returns machine-readable errors. |
| **Exporter** | Writes the versioned `skeleton.json` (bones and IK chains) and the validation report. |
| **Unity delivery** | A C# Editor importer builds the bones from the JSON as Unity's native 2D bones, with IK on each limb that ends in a hand or foot. In Unity mode, the orchestrator installs and runs it in the open Editor through Unity MCP, verifies the result and can save a prefab. |
| **Viewer** | A local browser viewer for the rigs in `out/`, for checking a rig by eye. |
| **Observability** | Optional tracing (Logfire) of every run: tool calls, tokens, latency and validation failures. |

### 2.3 Animation (Goal 2)

The same shape as the rig pipeline, run on a rig that already exists: **the LLM plans a small, bounded motion spec; code bakes every frame and validates it.** The LLM never writes keyframes.

```mermaid
flowchart TD
    D["Motion description<br/>e.g. 'a heavy, tired walk'"] --> G{Motion guardrail}
    R["Rig<br/>out/knight/skeleton.json"] --> P
    G -->|"unsupported: front flip, attack, ..."| RJ[Refused, with a suggested motion]
    G -->|accepted| P["Animation planner (LLM)<br/>returns an AnimationSpec: clip + speed, stride,<br/>bounce, arm swing, knee lift, lean"]
    P <-->|"rehearse: preview_clip(spec)"| PV["Preview on this rig<br/>bake + validate, report numbers"]
    P --> VW{"Clip allowed for<br/>the rig's view?"}
    VW -->|"walk / run / backflip on a front-view rig"| ST[Stop with a clear message]
    VW -->|yes| B

    subgraph B["Clip baker (code): every frame"]
        direction TB
        T["Template: idle, walk, run or backflip<br/>at phase p: hip, torso, arms, feet"] --> H["Hip: lowered to reach planted feet;<br/>backflip jumps high enough to clear the floor"]
        H --> IK["Legs: two-bone IK to the feet<br/>with the rig's own bend sides"]
        IK --> FK["Forward kinematics: the final pose;<br/>IK targets read off the hands and feet"]
    end

    B --> V{"Clip validator<br/>feet slide? floor? joints? loop?"}
    V -->|"fail, attempts left"| P
    V -->|"fail, out of attempts"| BE["Best effort: saved, marked not ready"]
    V -->|pass| OUT["out/knight/animations/heavy_tired_walk.json<br/>+ heavy_tired_walk.report.json"]
    OUT --> VIEW["Browser viewer<br/>play, scrub, onion skin"]
    OUT -->|"--unity"| REQ["Assets/Rigs/animation_request.json<br/>the clip as flat tracks"]
    REQ --> UI["Unity importer, via an MCP menu item<br/>.anim + Animator Controller + Animator"]
    UI --> CHK["Check: sampled frames match the clip,<br/>also after Unity's IK re-solves"]
    CHK --> PLAY([Press Play in Unity])
```

The flow, step by step:
1. **Guard:** the description is checked; unsupported motions are refused with a suggestion.
2. **Plan:** the planner chooses a small recipe, rehearsing it on the actual rig with `preview_clip` until the numbers match the description.
3. **Bake:** the baker turns the recipe into every frame. Templates are code, not stored clips; the baker adds IK for planted feet and the jump height a backflip needs.
4. **Validate:** the validator replays the frames. A failure goes back to the planner, at most 3 attempts.
5. **Deliver:** the clip is saved beside the rig. With `--unity` it becomes an `.anim` on the rig's Animator and is checked in the open Editor.

| Component | Responsibility |
|---|---|
| **Motion guardrail** | Same code checks; a classifier accepts idle, walk, run and backflip requests and refuses other motions with a suggestion. |
| **Animation planner** | Chooses the clip and its settings (speed, stride, bounce, arm swing, knee lift, lean). A tool bakes and validates each draft on the actual rig and reports it in numbers, so the planner can check that "heavy" really came out slow and low. |
| **Clip baker** | Deterministic templates (cycles on the spot; a backflip that plays once) turned into per-frame bone rotations and IK targets that agree with each other, with the rig's own IK bend sides. The jump height adapts to the rig, and held items stay steady. |
| **Clip validator** | Planted feet don't slide, nothing goes through the floor, joints bend only their own way, IK targets sit on the hands and feet, and cycles loop cleanly. |
| **Unity clip import** | Builds an AnimationClip and Animator on the rig, then checks sampled frames, including after Unity's own IK re-solves from the targets. |

A walk, run or backflip needs a side-view rig; on a front-view rig the pipeline stops with a clear message. Details are in LLD §7.

### 2.4 Guardrails

Guardrails work in two layers:

- **Prompt guardrails** are instructions inside the LLM prompts. They reduce how often the model breaks a rule.
- **Code guardrails** are deterministic checks around the LLM. They catch whatever the prompts miss.

The detailed rules for each area are in LLD §3.8.

---

## 3. Evaluation Criteria

**Test set:** 58 prompts, split between front and side views, covering view selection, standard characters, stylized proportions, proportion modifiers, accessories, ambiguous prompts and adversarial or out-of-scope requests. Each prompt is run 3 times per model, and results are reported per view as well as overall.

### 3.1 Quantitative metrics

**1. Does it produce a usable rig?**

- **Final validity rate (≥ 98%):** runs that end with a rig passing all validator checks.
- **First-pass schema validity (≥ 95%):** runs where the LLM's first answer already has the correct format.

**2. Is the skeleton structurally correct?**

- **Structure and required bones (100%):** one root, no loops or disconnected bones, all 14 required bones present.
- **Joint connectivity (100%):** every child bone starts where its parent ends.

**3. Does it look anatomically right?**

- **Symmetry error (≤ 1% of height):** left and right limbs mirror each other (front view) or match (side view).
- **Draw order (100%, side view):** far-side limbs are behind the body, near-side limbs in front.
- **Proportion error (≤ 10%):** body ratios match the values derived from the spec and stay inside plausible bands.

**4. Does it match the request?**

- **View accuracy (≥ 95%):** the correct view is chosen, e.g. "platformer ninja" gets a side view.
- **Style match (≥ 90%):** the proportions match the style descriptor, e.g. a "chibi mage" is 4 or fewer heads tall.
- **Accessory F1 (≥ 0.85):** requested accessory bones are added, with no unrequested extras.
- **Consistency (≥ 90%):** the same prompt gives similar proportions across repeated runs.

**5. Are the guardrails working?**

- **Guardrail recall (≥ 95%):** out-of-scope or malicious prompts are blocked.
- **False rejects (≤ 2%):** valid prompts are not blocked.
- **Prompt-rule adherence (≤ 5% violations):** first attempts rarely break prompt rules that only the code checks catch.

**6. Is it practical?**

- **Latency (p95 ≤ 30 s):** 95% of runs finish within 30 seconds.
- **Cost (≤ $0.05 per rig).**
- **Unity import success (100%):** valid rigs import with no errors and match the JSON.

### 3.2 Qualitative metrics

Rigs are scored 1–5 on four dimensions: **anatomical plausibility**, **prompt fidelity**, **animation readiness** and **rig cleanliness**.

- **Human review:** two reviewers score a sample of rigs each release. Target: average ≥ 4.0 on every dimension. An eval-only script draws each skeleton as an image for review; the agent itself never produces images.
- **Unity hands-on check:** reviewers import sample rigs and rotate limbs to confirm the joints pivot naturally.
- **Failure taxonomy:** failed cases are tagged by cause to guide improvements.

The suite can run on both providers to pick the primary model and the fallback. Currently OpenAI is primary (`gpt-5.4-mini` for the planner and the guard; the guard was chosen by eval, see [`GUARD_MODEL_COMPARISON.md`](GUARD_MODEL_COMPARISON.md)) and Anthropic is the fallback. The cross-provider comparison is still to run.

**Animation (Goal 2):** every clip is checked by the clip validator above. A golden set of motion prompts with expected clip types and setting directions ("heavy" → slower, less bounce) is planned, on the same eval harness.

---

## 4. Framework Justification

| Layer | Choice | Reasoning |
|---|---|---|
| **Agent** | **Pydantic AI** | Gives typed tools and outputs, and retries bad output automatically. |
| **Orchestration** | **LangGraph** | Controls the multi-step flow and the repair loop; runs both the rig and the animation pipelines. |
| **Validation** | **Pydantic** | One schema checks the LLM output and produces the final JSON. |
| **Unity** | **2D Animation package, C# importers, Unity MCP** | The importers work offline; MCP builds and checks rigs and clips in a live Editor. |
| **LLM** | **OpenAI (primary), Anthropic (fallback)** | Both handle tool calls and structured output well; the eval suite decides the primary. |
| **Observability** | **Logfire** | Traces agent calls and graph steps; off unless a token is set. |
