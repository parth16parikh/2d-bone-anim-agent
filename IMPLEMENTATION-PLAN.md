# Implementation Plan: 2D Humanoid Rig Agent (Goal 1: rigs; Goal 2: animation)

| | |
|---|---|
| **Companion documents** | `SYSTEM-DESIGN.md` (the HLD), `LOW-LEVEL-DESIGN.md` (the LLD), both in the repository |
| **Repository** | this one (`2d-bone-anim-agent`), which also holds this plan and the design docs |
| **Status legend** | ✅ done, ⏳ next, blank = not started |

---

## 1. Approach

The design follows one principle from the LLD: **the LLM plans and deterministic code computes.** So we build and prove the deterministic core first (vocabulary, schemas, builder, validator, exporter). A hand-written `RigSpec` must produce a valid `skeleton.json` with **no LLM at all**. Only then do we add the planner agent, the graph and Unity.

The work is split into small coding problems, done one at a time.

## 2. Working agreement

- One step at a time. Each step is small enough to read in one sitting: one or two source files plus one test file.
- A step is done when its tests pass, `uv run ruff check .` and `uv run mypy src` are clean, and the module docstring names the LLD section it implements.
- Tests are pytest, deterministic and offline. LLM code is tested with Pydantic AI's `TestModel` (LLD §4.5).
- Commit per step, only when asked.
- If a step exposes a gap in the LLD, fix the LLD first, then the code.

## 3. Defaults

1. Static tables (bones, presets, poses, IK chains) are **frozen dataclasses**. They are constants that only we edit, so they need no validation. Data that crosses a boundary (`RigSpec`, `Skeleton`, `ValidationReport`, `GuardResult`) is **Pydantic**.
2. Canonical bone names are plain `str` constants and frozensets, with no enum. `RigSpec` uses `Literal` types as in the LLD.
3. NumPy is used only where it helps (vector maths). The rest is plain Python.
4. The LLD and HLD live in the repository (`LOW-LEVEL-DESIGN.md`, `SYSTEM-DESIGN.md`), next to this plan.

---

## 4. Phases

### Phase A: Vocabulary and data contracts (no LLM, no geometry)

| # | Step | Files | Done when | Status |
|---|---|---|---|:-:|
| A1 | Bone table: `BoneDef` (name, required, optional token, view limits), the 14 required and 10 optional bones, `expand_optional(tokens)` | `vocabulary/bones.py`, `tests/test_bones.py` | 14 required, at most 24 canonical; token expansion correct | ✅ |
| A2 | `resolve_parent(bone, present_bones)` and the torso-top rules (LLD §2.3) for absent `chest`, `neck`, `hands`, `shoulders` | `vocabulary/bones.py` | Table-driven tests for every absent-bone combination | ✅ |
| A3 | Preset tables (§2.4.1, §2.4.2) and plausibility bands (§2.4.4) as data | `vocabulary/presets.py`, `tests/test_presets.py` | Four presets present; splits sum to 1; bands cover every base value | ✅ |
| A4 | Rest-pose angles (§2.8) and the IK chain table (§2.9) as data | `vocabulary/poses.py` (new), `tests/test_poses.py` | Angle lookup for every bone and pose; four chains | ✅ |
| A5 | `RigSpec`, `Preset`, `OptionalBone`, `BaseProportions`, `ProportionOverrides`, `ExtraBoneSpec` and the three `RigSpec` validators (§3.5a) | `schemas/rig_spec.py`, `tests/test_rig_spec.py` | Rejects pose/view mismatch, side-view shoulders, front-view toes, and an extra-bone budget over 16 | ✅ |
| A6 | `Skeleton` and `Bone` models, JSON round trip using the LLD §3.5b example | `schemas/skeleton.py`, `tests/test_skeleton_schema.py` | The LLD example parses and re-serialises identically | ✅ |
| A7 | `ValidationReport` (machine-readable errors with codes such as `mirror_coincident`) and `GuardResult` | `schemas/validation.py`, `schemas/guardrail.py` | Model tests pass | ✅ |

### Phase B: Deterministic builder

| # | Step | Files | Done when | Status |
|---|---|---|---|:-:|
| B1 | `resolve_proportions(spec)`: preset, then `base`, then multipliers; absorbed lengths; fixed total height (§2.4) | `builder/proportions.py` (new), `tests/test_proportions.py` | The vertical column sums to H for every preset and override; absorption cases are correct | ✅ |
| B2 | Geometry helpers: angle to vector, world and local conversion, Y-axis mirror, `180° − θ` | `builder/geometry.py`, `tests/test_geometry.py` | World to local to world round trip is exact to 1e-9 | ✅ |
| B3 | Front-view canonical layout (A-pose and T-pose), limb roots at their offsets, optional shoulders | `builder/layout_front.py`, `tests/test_layout_front.py` | Connectivity and mirror symmetry hold | ✅ |
| B4 | Side-view canonical layout: near and far limbs, depth ±1, far-limb offset | `builder/layout_side.py`, `tests/test_layout_side.py` | Depth order and pair equality hold | ✅ |
| B5 | Extra bones: chains, equal split, direction, naming, mirroring per view, depth inheritance, `layer` | `builder/extras.py` (new), `tests/test_extras.py` | Naming, twin angle, budget and minimum segment length are correct | ✅ |
| B6 | `build_skeleton(spec)`: assemble, assign ids and parent ids, local transforms, depth, `ik_chain`, `mirror_of` | `builder/skeleton_builder.py`, `tests/test_builder.py` | Golden test: the LLD example spec yields a valid `Skeleton` | ✅ |

### Phase C: Validator

| # | Step | Files | Done when | Status |
|---|---|---|---|:-:|
| C1 | Structure checks: one root, acyclic, no orphans, unique names, required bones, bone caps | `validator/structure.py`, `tests/test_validator_structure.py` | Every failure has a broken-skeleton test | ✅ |
| C2 | Geometry checks: connectivity (with the limb-root and jaw exceptions), symmetry, depth order, bounding box, minimum segment length | `validator/geometry_checks.py` | Same | ✅ |
| C3 | Plausibility bands and `mirror_coincident` | `validator/geometry_checks.py` | Same | ✅ |
| C4 | `validate(skeleton, spec)` assembling a `ValidationReport` | `validator/report.py` | Every builder output from Phase B passes | ✅ |

### Phase D: Export and the first end-to-end slice (no LLM)

| # | Step | Files | Done when | Status |
|---|---|---|---|:-:|
| D1 | Exporter: versioned `skeleton.json` and `validation_report.json` | `export/json_exporter.py`, `tests/test_exporter.py` | Files are written and can be reloaded | ✅ |
| D2 | CLI `rig-agent build --spec spec.json`: spec, skeleton, validate, export | `cli.py` | A hand-written spec produces a valid `skeleton.json` | ✅ |

> **Milestone 1 (end of Phase D):** front and side rigs from a hand-written `RigSpec`, validated, with no LLM involved. ✅ **Reached.** `uv run rig-agent build --spec examples/knight_side.json` produces a validated `skeleton.json`.

### Phase E: Planner agent

| # | Step | Files | Status |
|---|---|---|:-:|
| E1 | Pure tools: `list_vocabulary`, `get_preset`, `get_view_rules`, `describe_proportions`, `dry_run_validate`, `list_existing_bones` | `agent/tools.py` | ✅ |
| E2 | Guardrail rules and the prompt-block renderer | `guardrails/rules.yaml`, `guardrails/prompt_blocks.py` | ✅ |
| E3 | System prompt builder (§3.9) with few-shot examples | `agent/system_prompt.py` | ✅ |
| E4 | Planner: Pydantic AI agent with `output_type=RigSpec`, tools and `UsageLimits`, tested with `TestModel` | `agent/planner.py` | ✅ |
| E5 | Input guard classifier and its code checks (length limit, tag escaping) | `guardrails/input_guard.py` | ✅ |

### Phase F: Orchestration

| # | Step | Files | Status |
|---|---|---|:-:|
| F1 | `RigState`, `AttemptRecord`, `UnityResult` | `schemas/state.py` | ✅ |
| F2 | Nodes: guard, plan, build, validate, export, best_effort, reject | `graph/nodes.py` | ✅ |
| F3 | LangGraph wiring with the bounded repair loop and budgets | `graph/build_graph.py` | ✅ |
| F4 | CLI `rig-agent run "prompt"` | `cli.py` | ✅ |
| F5 | Provider failover and settings | `config.py` | ✅ |

> **Milestone 2 (end of Phase F):** a prompt produces a validated `skeleton.json` with a real model. ✅ **Code-complete and tested with scripted models.** It has not run against the real API yet, because no key is configured.

### Phase G: Unity

| # | Step | Files | Status |
|---|---|---|:-:|
| G1 | `RigImporter.cs` (bones in id order, depth and layer sorting) and `BoneGizmo.cs` | `unity/editor/*.cs` | ✅ |
| G2 | `FacingController` and the side-view flip | `unity/editor/` | ✅ |
| G3 | MCP client with the `RigAgent_Output` allowlist; `unity_apply` and `unity_verify` nodes | `unity/mcp_client.py`, `graph/nodes.py` | ✅ |

### Phase H: Evals and observability

| # | Step | Files | Status |
|---|---|---|:-:|
| H1 | Logfire tracing | `observability/tracing.py` | ✅ |
| H2 | `evals/render_skeleton.py` (Pillow) | `evals/render_skeleton.py` | ✅ |
| H3 | Golden set of about 50 prompts | `evals/golden.yaml` | ✅ |
| H4 | Metrics Q1 to Q13 and the eval runner | `evals/metrics/` | ✅ (two full live runs) |

### Phase M: Motion (Goal 2: animation clips)

Called A1–A4 while it was being built. The same principle as Goal 1: the LLM plans a small, bounded
`AnimationSpec`; code bakes every frame and validates it.

| # | Step | Files | Status |
|---|---|---|:-:|
| M1 | Deterministic core: `AnimationSpec`/`AnimationClip`, FK, two-bone IK, idle/walk/run templates, baker, clip validator, `animate-build`, viewer playback | `schemas/animation.py`, `animation/`, `export/animation_exporter.py`, `viewer/` | ✅ |
| M2 | Unity: clip import (`RigAnimImporter.cs`), Animator, placeholder capsules (`RigShapes.cs`), delivery and IK re-solve check, `unity-apply-anim` | `unity/csharp/Editor/`, `unity/animation.py`, `unity/delivery.py` | ✅ |
| M3 | Animation planner and pipeline: motion guard, planner agent with `preview_clip`, LangGraph flow, `animate` | `guardrails/anim_guard.py`, `agent/anim_*.py`, `graph/anim_graph.py` | ✅ |
| M3b | Backflip (side view): per-rig jump height, whole-body floor check, steady wrists for held items | `animation/templates.py`, `animation/baker.py`, `animation/validator.py` | ✅ |
| M4 | Animation golden set and metrics | `evals/` | |

---

## 5. Notes from Phases B to D

- **LLD fixes made first** (per the working agreement): `spine_2` takes 25% of the spine and chest shares; the `root` is a 2.5%-of-H placement marker; the far-limb offset is 1.5% of H toward −X; the `hip` joins the parent-tail exceptions (limb roots, jaw); the thigh and upper-arm plausibility bands were widened so the bias range alone never leaves them.
- **Extra modules** beyond the plan: `builder/errors.py` (`BuildError`), `builder/column.py` (torso column and limb chains shared by both layouts), and `tests/layout_helpers.py` (shared test builders; `tests` is on pytest's `pythonpath`).
- **Extra issue codes:** `unknown_bone`, `wrong_parent`, `hip_misplaced`.
- **Validator reports, not raises:** an unbuildable spec (for example no room for a torso) becomes a `proportion_out_of_band` issue in `validate()`, so the repair loop can use it.
- **Examples:** `examples/knight_side.json`, `examples/elf_front.json`, `examples/chibi_mage_front.json`.

## 6. Notes from Phase E

- **Order:** E5 (input guard) was built before E3 and E4, because the planner's user message wraps the description with the guard's `wrap_description`.
- **Models and key:** the planner runs on `gpt-5.4-mini` and the guard on `gpt-5.4-nano` through `OpenAIChatModel` (base URL `https://api.openai.com/v1`). The API key lives only in the git-ignored `.env` file (`OPENAI_API_KEY=`); it is empty until you add it, and nothing calls the API without it.
- **Tested without the API:** the agents are tested with `FunctionModel`, and the OpenAI request path is tested against a fake HTTP transport that answers in the Chat Completions format (`tests/test_openai_wire.py`). The three live tests (`tests/test_live.py`) are opt-in: `uv run pytest -m live`.
- **Not yet verified against the real API:** answer quality, whether the model follows the decision guide, and the real token cost per rig. That is the first thing to check once the key is in.
- **Guardrails:** `guardrails/rules.yaml` holds every rule once; each rule names its code check, and a test resolves every name. The `too_long` guard category was added, and the LLD text on vague prompts was reconciled (a vague but readable prompt such as "a hero" is accepted with defaults).
- **A prompt bug caught by a test:** the first few-shot example had a staff pointing down from a low hand, which the validator's bounds check rejected. The staff now points up, and the decision guide warns about long downward items.
- **New CLI command:** `rig-agent plan "chibi knight" [--view side] [--out spec.json]` runs the guard and the planner and dry-runs the result; `rig-agent build` turns the spec into a rig.
- **Extra issue code:** `unbuildable`, returned when a spec cannot be built at all.

## 7. Notes from Phase F

- **Graph:** `input_guard → plan → build → validate`, then `export` on a pass or back to `plan` on a failure, up to 3 attempts. Extra nodes: `best_effort`, `reject` and `fail`. `rig-agent run "prompt"` runs it.
- **Budgets per request:** 12 model calls, 15 tool calls, 60 seconds, 150,000 tokens (all in `config.py`). Each planner run gets only what is left, and the time left becomes its per-call timeout.
- **Best effort:** when repairs or budget run out, the highest-scoring attempt is exported with a failing report. The score is `1 − 0.1 × errors − 0.01 × warnings`, and 0 for an unbuildable spec. If nothing could be built the request ends in `error` with no files.
- **Failover (F5):** `build_model()` returns the primary provider's model, or a `FallbackModel` when both `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are set. The fallback applies to API errors only, after each SDK's own two retries with backoff. The Anthropic models default to `claude-sonnet-5` (planner) and `claude-haiku-4-5-20251001` (guard). Failover is tested with fake models; it has not run against the real APIs.
- **Unity:** `unity_mode` is accepted and reported as `unavailable` until Phase G adds the Unity nodes.
- **State fields added to the LLD:** `view`, `out_dir`, `started_at`, `usage`, `error`.
- **A design decision worth knowing:** the input guard's call counts as one model call against the budget, but only when the request is accepted, because a deterministic rejection makes no call.
- **Test structure:** `tests/graph_helpers.py` holds the scripted planner, guard and clock; `tests/test_graph_integration.py` runs the graph with the real `plan()` on a scripted model.

## Notes from Phase G (Unity)

- **Set up first:** the Unity project (originally `.../Project/2d-bone-anim`, now `unity-project/` inside the repository; Unity 6000.4.0f1) already had MCP for Unity 10.2.0. The MCP server was started from **Window > MCP for Unity**, and the agent connects at `http://127.0.0.1:8080/mcp`. Registering the server with Claude Code was not needed: the Python agent is the real consumer.
- **Python client:** the MCP SDK 2.x `Client` (URL in production, an in-process `MCPServer` in tests). SDK 2.x changed names (`server_info`, `streamable_http_client`, `MCPServer`) and ships its own `httpx2`, so unreachable servers are detected by exception class name.
- **Safety:** a hard allowlist of 5 tools and one menu item, enforced before anything is sent. A test proves a forbidden call (for example `delete_script`) never reaches the server.
- **Verification is real:** the importer reads the actual Transforms back into `last_import.json`, and Python compares that with the JSON (Q13).
- **Live acceptance:** the whole chain ran against real Unity and the real model: `run "chibi knight with a big sword" --view side --unity` took 13 s, one attempt, 20 bones built and verified (max error 8e-7). The model put the sword on `hand_R`, the near hand.
- **Tests:** 714 offline tests, plus 5 opt-in tests against the real Unity (`pytest -m unity`).
- **Observation:** that run used about 46,000 input tokens over 5 model calls, because the large system prompt and tool results are re-sent on each call. Worth optimising in the eval phase (cost target Q12).
- **Unity project changes:** only `Assets/RigAgent/` (scripts) and `Assets/Rigs/` (exchange files). Imported rigs live under `RigAgent_Output` in the open scene, which is left unsaved.

### Correction found by review of a real output (side-view near/far)

- **Bug in the design, not the code:** LLD §2.2 said a right-facing character shows its *left* side to the camera (`_L` near, `_R` far). That is backwards: a character facing right shows its **right** side. The output looked wrong (right leg and arm behind the left) and the user's review caught it.
- **Fix:** facing right, `_R` limbs are near (depth +1, in front) and `_L` limbs are far (depth −1, offset 1.5% of H toward −X). Changed in the LLD (§2.2, §2.6, §2.9, Q6), the side layout, extras naming (the near twin of a center-parent extra is `_R`), the validator's offset, symmetry and depth-order checks, the tool and prompt text, the ninja and knight examples (held items go on `hand_R`), the viewer samples and 12 tests, plus a new test that pins the convention.
- **Unchanged:** the front view (facing the camera, the character's left is screen right), rest-pose angles, and every front-view example.
- **Old outputs:** side-view rigs built before this change have the sides swapped. Rebuild them.

### Additions after Phase G: batch import, prefabs, viewer picker

- **Asked for:** (1) put everything in `out/` into Unity, (2) save a properly created rig as a prefab at a path in the project, (3) a file selector in the viewer that lists `out/` and updates the picture on click.
- **Viewer:** `rig-agent view` runs a small server (`rig_agent/viewer_server.py`) and the sidebar gets a *Rigs in out/* list (`/api/rigs`). A plain `python3 -m http.server` cannot list a folder for the page and serves the whole project including `.env`, so the new server binds to `127.0.0.1` and serves only `viewer/` and `out/` (tested against `..`, encoded traversal and dotfiles). Verified in headless Chrome: picking a rig swaps the drawing, and the 4 s list refresh does not reset the selection.
- **Batch:** `unity-apply-all` (new menu item **Import All Rigs**, manifest `Assets/Rigs/batch.json`, report `last_batch.json`). Rigs are named after their **folder**, because runs of the same prompt share a `rig_name` and would replace each other. The row is laid out by bounding box (0.4 gap). The batch clears the previous rigs under `RigAgent_Output` first, so the layout is deterministic.
- **Prefabs (decision):** the request said the user makes the prefab; we automated it as an option, `--prefab-dir` (or `UNITY_PREFAB_DIR`), because the path is theirs to choose. Only rigs that were verified in Unity **and** passed validation get one. An existing prefab is **kept unless `--overwrite-prefab`**, since it may already carry sprites. The root is saved at the origin. Also available for `unity-apply` and `run --unity`. The allowlist grew from one to three menu items, and prefab assets are the one thing written outside `Assets/RigAgent` and `Assets/Rigs`.
- **Live check:** all 5 rigs of `out/` imported and verified (5 of 5), 5 prefabs created in `Assets/Prefabs/Rigs`, the second run kept them all, prefab roots at (0, 0, 0), single-rig `unity-apply --prefab-dir` also worked.
- **Tests:** 786 offline (was 714) and 6 opt-in Unity tests.

### Unity project moved into the repository

- The Unity project now lives in `unity-project/` in the repo. `UNITY_PROJECT_PATH=unity-project` in `.env`; a relative path is resolved from the repository root (so it works from any directory), and `.env` itself is now found from any directory too.
- `.gitignore` ignores Unity's generated folders (`Library`, `Temp`, `Logs`, `UserSettings`, `*.csproj`, `*.sln`) but keeps `Assets`, `Packages` and `ProjectSettings`. Ruff and pytest skip `unity-project/`.
- **Caveat found:** a Unity Editor that was already running kept using the old path. It must be closed and reopened from `unity-project/`, and the MCP server restarted, before deliveries reach the moved project.

### `ik_chains` added to skeleton.json (schema 1.1)

- **Why:** the Unity IK experiment (Limb solver on the arm) worked, but the elbow bent the wrong way without a `flip`. The knowledge of which way an elbow or knee bends belongs in the exporter, not in the engine scripts.
- **What:** `ik_chains: [{name, root, joint, effector|null, bend_side}]` (originally a world `bend_direction` vector; replaced, see the IK section below), built from one table in `vocabulary/poses.py` (`ik_chain_defs`, `bend_direction`). Side view: elbows back, knees forward. Front view: elbows outward and down, knees outward (a default we chose; change it in one place).
- **Compatibility:** `schema_version` is now `1.1`. `1.0` files still load in Python and in the importer (checked live: 5 old and 1 new rig imported together). The viewer ignores the new field.
- **Validation:** new issue code `invalid_ik_chain` (missing or unknown chain, wrong roles, chain bones not connected, wrong bend side for the view, bone tags that disagree with the chains).
- **Not done yet:** the importer parses `ik_chains` but does not build IK solvers yet. That comes with the skinned-sprite and skeleton-asset change.
- **Tests:** 814 offline (was 791).

### Native bones: placeholder sprite, skeleton asset, per-rig folders

- **Trigger:** the custom `BoneGizmo` drawing was replaced by Unity's own 2D Animation bones. A user-added `SpriteSkin` failed with "Sprite has no Bind Poses": the package draws bones only for a sprite that carries them (bind poses and per-vertex weights).
- **Built (checked live in Unity):** a fully transparent placeholder sprite per rig, written through the Sprite Editor data providers (bones as `SpriteBone`, one weighted quad), a `SpriteRenderer` and `SpriteSkin` on the rig root, and a `SkeletonAsset`. `SpriteSkin` reports `Ready`; the bones draw in the Scene view. `BoneGizmo` is metadata only.
- **Finding:** `.skeleton` cannot be created from a script (`CreateAsset` refuses the extension and loads it as a `DefaultAsset`), so the skeleton is `<rig>_skeleton.asset`. The importers' *Main Skeleton* field takes it either way.
- **Layout:** one folder per rig: `<prefab folder>/<rig>/` holds the prefab, `<rig>_placeholder.png` and `<rig>_skeleton.asset`; rigs without a prefab use `Assets/Rigs/Generated/<rig>/`. Existing prefabs are still kept unless `--overwrite-prefab`.
- **Verification:** the Transform readback is unchanged. New: the report's `skin` block must show state `Ready`, sprite bones and bind poses equal to the bone count, weights present, and a skeleton asset. The installer now requires the 2D Animation package.
- **Cleaned up:** all old rigs and prefabs were deleted at the user's request (including the user's edited `elf.prefab`); fresh `1.1` rigs were built from the examples; the throwaway experiment scripts were removed.
- **Not done yet:** IK solvers (the importer parses `ik_chains` but does not use them), so dragging a hand still detaches it. That is the next step.
- **Tests:** 833 offline (was 814) and 6 live Unity tests.

### IK in Unity (Limb solvers from `ik_chains`)

- **Problem:** dragging a bone (for example `hand_R`) in the Scene view detached it from its forearm. That is how Unity bones work without IK (its move tool translates only the selected bone), not a setup error: the live hierarchy was correct.
- **Built:** `RigIk.cs`: per chain that has an effector, a `LimbSolver2D` and a target (`IK/<chain>/target_<effector>`) under an `IK` object on the rig root, driven by an `IKManager2D`. On by default; `--no-ik` on `unity-apply`, `unity-apply-all` and `run` turns it off.
- **Design change found while reading the solver:** `flip` chooses the **side of the root-to-target line** the joint sits on, not a world direction. `bend_direction` was replaced by `bend_side` (`left` or `right`), decided in `vocabulary/poses.py`. (A front-view A-pose arm's "outward and down" is the arm's own direction, so a vector could not decide the side.)
- **Bug caught by verification:** the solver's `constrainRotation` (on by default) forces the effector to its target's world rotation. My first targets had no rotation, so every hand and foot snapped to point right (errors up to 2.4 units). Each target is now created with the effector's position and rotation.
- **Checked live in Unity:** for a side-view arm and leg and a front-view arm, moving the target put the effector on it (error 0.0000), the root did not move, the forearm and hand kept their local positions (still attached), the joint sat on the side the JSON asks for, and putting the target back restored the rest pose exactly.
- **Also fixed:** the Unity client crashed when Unity returned an empty state during a recompile (`"data": null`); it now waits.
- **Not touched:** the prefabs already in the project were made before IK and are kept as they are (use `--overwrite-prefab` to regenerate them). A prefab was open in Unity's Prefab Mode during the work, so nothing in it was changed.
- **Tests:** 847 offline (was 833) and 6 live Unity tests, which now also verify real solvers.

### IK reverted: only protects the effector, not the bones you actually drag

- **User's report:** "upper_arm_R and forearm_R are not properly connected, it is visible if I only move forearm_R. Same applies to legs and Left side as well." then, after the explanation below, "I think it is even worse. lets revert it to previous state. it was better then this."
- **Diagnosis, checked live in Unity before reverting (not just reasoned from the source):** a Limb solver only ever adjusts *rotations*, driven by its target; it never resets a bone's *position*. Translating `forearm_R` directly (e.g. with Unity's Move tool) by 0.15 and then calling `manager.UpdateManager()` (what the next `LateUpdate` tick would do) left the elbow gap at a full **0.15** — completely uncorrected. Moving the *target* instead correctly re-posed the limb (elbow gap ~0.04, only because that particular target was slightly beyond the rig's actual reach). So IK was working exactly as coded; it just didn't fix the interaction the user was actually using (dragging bones with Move), and having both a working-but-narrow target system *and* still-breakable bones alongside it was judged worse than the pre-IK state.
- **Reverted:** `RigIk.cs` deleted; `RigImporter.cs`'s IK wiring (`ImportOptions.ik`, `BatchManifest.ik`, `ImportReport.ik`, the `RigIk.Attach` call and its `bool ik` parameter threading) removed, back to the `RigSkin`-only state. Python: `UnityDelivery`'s `ik` parameter, `compare_import`'s `expect_ik`/`_check_ik`, the `--no-ik` CLI flag, and `default_deps`'s `ik` parameter all removed. Kept as-is (a separate, earlier, still-valid step): the `ik_chains`/`bend_side` schema field in `skeleton.json` and its C# acceptance — that's descriptive metadata, not something that builds live solvers, and wasn't part of the complaint.
- **Also removed:** the throwaway `Assets/_Spike/` scripts used to diagnose this (including the final `IkDragCheck.cs` that produced the numbers above).
- **Not yet done:** the user will describe the IK problem in more depth before any redesign; no new IK approach has been decided.
- **Tests:** 859 offline (was 869; the drop is the ~10 IK-only tests removed, not a loss of the planner-guidance or delete-command tests added in between); the 6 live Unity tests no longer assert on IK solvers.

### Planner guidance: explicit size ratios ("head at least 2x the body")

- **Trigger:** `run "Create a monster rig where head is atleast 2x bigger then body..."` produced a head only 26% of the height (ratio 0.35:1), even though the assumptions said "head is intended to be much larger than the body." Reverse-engineered the actual chosen values from the skeleton geometry (the RigSpec itself was not saved): preset `stylized`, `heads_tall` only nudged from its 6.0 default to about 5.0, `head_scale` pushed to about 1.4, but `leg_ratio`/`arm_ratio` left untouched at the preset defaults (0.42/0.40) instead of being pulled down too. A single-lever nudge, not the coupled push the ratio needed.
- **First (wrong) conclusion:** tested only the `chibi` preset and concluded literal 2:1 was mathematically impossible (ceiling ≈1.22:1). **Corrected after checking all four presets:** dropping `neck` folds its length into the head bone, and how much depends on the preset's `neck_hu` (chibi 0.10, realistic 0.30, stylized 0.20, **heroic 0.35**, biggest). With `heroic` and `heads_tall`/`leg_ratio`/`arm_ratio` all at their floor (2.0/0.25/0.25) and neck dropped, the head reaches **2.08x** the rest of the body — verified with `build_skeleton` + `validate`, a clean pass with no warnings. Literal 2x *is* reachable; it just needs the right preset, not just the right numbers.
- **Fixed:** `describe_proportions` (`agent/tools.py`) now also returns a `ratios` block (`head_to_rest_of_body`, `leg_to_arm`, `leg_to_torso`, `arm_to_torso`), computed from the same lengths it already reports, so the model can read the actual achieved ratio instead of estimating it by eye.
- **System prompt (`agent/system_prompt.py`):** a new "Explicit ratios and extreme requests" paragraph teaches that every proportion field is a *share* of one fixed height, so an extreme request needs every relevant lever moved together (heads_tall + leg_ratio + arm_ratio to their floor for a big head, dropping neck, preferring the preset with the biggest `neck_hu`), not a single nudge; the tool policy now says to keep adjusting against `describe_proportions`' ratios, not just until `dry_run_validate` stops erroring. A 5th few-shot example (the monster, using `heroic`, reaching 2.08x) demonstrates the full pattern end to end.
- **Tests:** 853 offline (was 847): new `ratios` tests in `test_tools.py`, the 5th example covered in `test_system_prompt.py`.
- **Not yet verified:** this is prompt guidance, not code the graph enforces; whether the real model actually follows the new recipe on a fresh "big head" prompt is untested (would need a live `run`, not done here to avoid an unasked-for model call).

### A `delete` command for out/

- **Asked for:** "override existing skeleton in out", "create skeleton in unity", "delete some skeleton as well." Checked each against what already existed: `run`/`build` already replace an existing `--out` folder silently (no new command needed, just a printed note added: `[export] note: replacing the rig already at ...`), and `unity-apply`/`unity-apply-all` already cover pushing one or every rig into Unity. The only real gap was **delete**.
- **Built:** `rig-agent delete <folder> [<folder> ...]` and `rig-agent delete --all --out DIR`. `delete_rig()` (`export/json_exporter.py`) removes only `skeleton.json` and `validation_report.json`, and removes the folder itself only if that leaves it empty; a folder with neither file is refused (`NotARigFolderError`) rather than silently doing nothing, and anything else in the folder (your own notes, a `spec.json` copy) is left alone. `--all` reuses `unity-apply-all`'s own rig discovery (`collect_rigs`), so it skips and reports unreadable folders the same way. Deliberately `out/`-only, per the user's choice; never touches Unity or prefabs.
- **Tests:** 869 offline (was 853): `delete_rig` unit tests, `delete` CLI tests (single, multiple, `--all`, empty `--all`, bad args, unreadable rigs skipped, refuses a non-rig folder), and tests for the new "replacing" note on `build` and `run`.

## 8. Open items

### IK reimplemented, with explicit chains for the knight

- **Asked for:** "these are the IK chains -> upper_arm_L->forearm_L->hand_L, upper_arm_R->forearm_R->hand_R->extra_sword, thigh_L->shin_L->foot_L->toe_L, thigh_R->shin_R->foot_R->toe_R. This all should be IK chain in Knight. And IK constraint need to be defined properly."
- **Checked before implementing (to avoid a second wrong guess):** read `CCDSolver2D.cs`/`CCD2D.cs` directly — Unity's 2D IK package has **no per-joint angle-limit constraint** on any solver type (Limb, CCD, FABRIK). Asked the user two clarifying questions rather than assume: (1) should `extra_sword`/`toe_L`/`toe_R` be literal solved links (needs CCD/FABRIK, since `LimbSolver2D.transformCount` is hardcoded to exactly 3) or rigid followers of the hand/foot; (2) what "constraint" meant. Answers: rigid followers, and "constraint" meant `constrainRotation` (the effector takes its target's rotation) — i.e. exactly what the original `RigIk.cs` already did, not a new joint-limit feature.
- **Built:** re-created `RigIk.cs` and the `RigImporter.cs`/Python/test wiring exactly as they were before the revert (833 → 872 offline tests again, byte-for-byte the same count as when IK first passed). `extra_sword` and `toe_L`/`toe_R` were never part of `ik_chains` to begin with (only canonical `upper_arm/forearm/hand` and `thigh/shin/foot` triples are), so no chain-length change was needed at all — the user's own answer confirmed the existing design already matched what they wanted.
- **Verified live on the actual knight example** (`examples/knight_side.json`: `extra_sword` on `hand_R`, `toe_L`/`toe_R` present) — the specific check the user asked for: dragging the `arm_R` and `leg_R` targets kept the elbow/knee gap at **0.00000**, reach error **0.00000**, and left the sword's and toe's offset from their parent **completely unchanged** before and after (0.198 and 0.275 respectively, identical to 5 decimal places) — i.e. no stretch, no detachment. Reset to rest exactly.
- **Tests:** 872 offline (was 859), matching the original IK implementation's count.

### IK still didn't move for the user: `LateUpdate` never fires for our managers

- **Reported:** two screenshots — dragging `hand_R` directly (already-explained: translating a bone bypasses IK, expected), and dragging the IK target circle in the Scene view, which also did not bend the limb. Asked which interaction they used: confirmed they dragged the small target circle directly (Unity's `IKGizmos.DoTargetGUI`), not select-then-Move.
- **Traced precisely, not guessed:** `DoTargetGUI` (package `IK/Editor/IKGizmos.cs`) only ever does `chain.target.position = newPosition;` on each drag event — it never itself triggers a solve. The only thing meant to notice and re-bend the limb is `IKManager2D.LateUpdate()` (`[ExecuteInEditMode]`, unconditionally calls `UpdateManager()`). Ruled out a tilted-drag-plane theory first (every bone rotation we emit is Z-axis-only, so a target's `forward` always stays aligned with the camera; not the cause).
- **Confirmed live with a throwaway diagnostic** (`Assets/_Spike/Editor/LateUpdateCheck.cs`): `alwaysUpdate=True`, `solver.isValid=True`, both components enabled — yet moving `chain.target.position` directly and waiting up to **3 full seconds** across multiple editor ticks never moved the effector at all (`hand moved so far = 0.00000` throughout). `LateUpdate` genuinely never fires for a manager `RigIk` creates from a menu item.
- **Fix:** `RigIkTicker.cs` — a small `[InitializeOnLoad]` static class that hooks `EditorApplication.update` and calls `manager.UpdateManager()` on every `IKManager2D` found under `RigAgent_Output`, once per editor frame, independent of why `LateUpdate` doesn't fire. Deliberately re-scans the scene each tick rather than keeping a static list of managers: a list would go stale across every script recompile (the components persist in the open scene; a plain static field does not survive the domain reload), which would silently stop ticking existing rigs after any `unity-apply` that needed to recompile.
- **Re-verified live, this time with zero explicit solve calls anywhere in the test:** same diagnostic script, after installing the ticker — moving the target by (0.1, -0.1) resolved to `hand moved so far = 0.14142` (the exact full magnitude) within 0.5s and stayed there. Repeated the full knight check (elbow/knee gap, reach error, sword/toe offset) purely by moving targets and waiting, with no `UpdateManager()` call anywhere in the test script: gap 0.00000, reach error 0.00000, sword/toe offsets unchanged (0.198, 0.275) — identical to the earlier manually-triggered numbers.
- **Tests:** 873 offline (was 872): the shipped-script count and list (5 → 6 Editor/Runtime `.cs` files) and a new test pinning the ticker's design (`[InitializeOnLoad]`, re-scan not a list, skips Play mode).

### Phase H1: Logfire tracing

- **Built:** `observability/tracing.py` — `configure()` (calls `logfire.configure(token=settings.logfire_token, send_to_logfire="if-token-present", console=False)` then `logfire.instrument_pydantic_ai()`, guarded to run once per process) and `traced_node(name, fn)`, which wraps one LangGraph node in a `logfire.span("node {node}", ...)` and attaches whichever of the guard verdict, running usage totals, validation report, Unity result, or final status the node actually returned. Wired in two places: `cli.py`'s `main()` calls `configure_tracing()` first, and `build_graph.py` wraps every node with `traced_node(name, ...)` instead of the bare `getattr(nodes, name)`.
- **Optional by construction, same pattern as the API keys:** `send_to_logfire="if-token-present"` means nothing is ever sent anywhere unless `LOGFIRE_TOKEN` is set in `.env`; `logfire.instrument_pydantic_ai()` then covers every planner/guard model call (tools, tokens, latency) for free, and `traced_node` covers the steps that never call a model (build, validate, export, the Unity steps) — together the full list LLD 3.9 asks for (tool calls, tokens, latency, validation failures).
- **A real gap found and fixed along the way:** spans created before `configure()` runs (which is what most of the test suite does, deliberately, since it never calls it) are inert, not an error — but Logfire still prints a "not configured" warning for each one. Added `[tool.logfire]\nignore_no_config = true` to `pyproject.toml` (confirmed this is exactly the file/section Logfire's own config loader reads) to silence it project-wide instead of forcing every test to call `configure()` first.
- **A mypy overload error found and fixed:** `graph.add_node(name, traced_node(name, getattr(nodes, name)))` failed type-checking because LangGraph's `add_node` infers its state type from a `Protocol` match on the exact callable passed in, which mypy cannot do through a named wrapper function — the original unwrapped call had always been silently accepted as `Any`. Fixed by typing `traced_node`'s return as `Callable[..., Any]` rather than the precise node alias, with a docstring note explaining why.
- **Tests:** `tests/test_tracing.py` (8 new tests) using Logfire's own `capfire` pytest fixture (`logfire.testing`), which turned out to auto-register via Logfire's own pytest entry-point plugin — no import or `conftest.py` needed (a first attempt at an explicit `pytest_plugins = ["logfire.testing"]` in `conftest.py` raised "Plugin already registered under a different name"; removing the file and the redundant `from logfire.testing import capfire` import fixed it cleanly). Assertions inspect real emitted spans, not just "it doesn't crash": every node that ran gets its own named span, the `plan` span carries the running usage totals, `validate` carries pass/fail and error/warning counts, a rejected prompt's `input_guard`/`reject` spans carry the guard's verdict, and `traced_node` is confirmed to be a pure passthrough (same return value, same call count) so tracing can never change graph behaviour.
- **Verified:** 881 offline tests passing (was 873), `ruff check .` and `uv run mypy src` both clean. Two live smoke checks outside pytest: a normal `rig-agent build` run confirmed `configure_tracing()` in `main()` doesn't disturb ordinary CLI usage, and a raw `python -c` script calling `configure()` then `run_rig(...)` with a fake planner produced clean output (`status: success`) with no warning leakage to a real terminal.

### Phase H2: offline PNG renderer

- **Decided first: Pillow, not Unity screenshots.** Asked whether the renders should come from Unity. They are for the eval harness (about 50 golden rigs per run, scored by people and by a vision model), and for that Pillow wins. It needs no running Unity or MCP server, and it is deterministic: the same rig gives the same bytes, which makes runs comparable. It is also fast, and the picture is designed for the judge (labels, left/right colours, a pass/fail header). A Unity screenshot would need the Scene view (the sprite is transparent and bones are editor overlays, so a Game-camera shot is empty), would depend on the editor's state, and would need a tool outside our MCP allowlist. An optional Unity screenshot mode for spot checks is possible later but was not built.
- **Built:** `evals/render_skeleton.py`: a pure `render(skeleton, report, options) -> PIL.Image`, `render_folder()` (writes `<rig>/skeleton.png`, or `<dest>/<rig>.png`), and a command line, `uv run python -m evals.render_skeleton FOLDER... | --all OUT_DIR [--dest DIR] [--color side|depth|ik] [--no-labels] [--size N]`. The drawing is ported from `viewer/viewer.js`, so the PNG and the viewer agree. Diamond bones run from pivot to tip. Draw order is by depth, shifted by the extra layer as in Unity. Joint dots and dashed links mark bones that don't start on their parent's tail. Red rings mark bones the report names (a spec name like `extra_cape` covers `extra_cape_1..3`). There are three colour modes and the same label placement as the viewer. It adds a header (rig name, PASSED/FAILED with counts, view, rest pose, bone count, height, style, the prompt) and a legend. Drawn at 2x and scaled down, because Pillow's lines are not anti-aliased.
- **`rig-agent delete` also removes `skeleton.png`** (`RENDER_FILE` in `export/json_exporter.py`). The render is drawn from `skeleton.json`, so leaving it behind would be stale and would keep the folder from being removed. A folder holding only a render is still not a rig folder and is refused.
- **Checked by eye on all 7 rigs in `out/`.** The knight and the elf match the viewer. `monster3`'s spike hammer shows as a tiny 0.12-unit bone overlapping `foot_L`, which is accurate: it's a real flaw in that rig (the validator passes it), and exactly what the vision judge is meant to catch. One renderer fix came out of this: grid tick labels collided in the bottom-left corner and were cut off at the edges, so those are now skipped.
- **Setup:** `pyproject.toml`'s pytest `pythonpath` gained `"."` so the root-level `evals` package imports in tests. The tests `importorskip` Pillow, so the core suite still runs without the `eval` extra.
- **Tests:** 903 offline (was 881). There are 20 renderer tests: the drawing rules against the knight example (sword in front, cape behind, jaw link), determinism (identical PNG bytes), red only when the report fails, each option changing the image, file placement with and without `--dest`, a missing report, `--all` skipping a broken rig with exit code 1, and argument errors with exit code 2. There are also 2 new `delete_rig` tests. `ruff check`, `ruff format --check`, and `mypy src evals` are clean.

### Phases H3 and H4: golden set, Q1-Q13 and the eval runner

- **Golden set (`evals/golden.yaml`, loaded and validated by `evals/golden.py`):** 58 cases, exactly the LLD 4.1 table's counts (standard 10, view selection 8, stylized 10, modifier 8, accessory 10, ambiguous 5, adversarial 7). The LLD says "around 50" but its own table adds up to 58. Each case lists **expected attributes**, never coordinates:
  - an outcome (`accept`, `reject` with allowed guard categories, or `reject_or_clamp`)
  - a view
  - `[min, max]` ranges on the rig's *derived* proportions (heads_tall, leg_ratio, arm_ratio, shoulder_width_hu)
  - a bone-count range
  - accessory chains by semantic group
  - "assumption recorded"

  The standard, stylized, modifier and accessory categories pass an explicit `view` to split evenly between front and side (a test enforces this, per LLD 4.1). Six of the eight view-selection cases leave the view to the agent. The loader refuses unknown proportion names or groups, duplicate ids, and expectations that contradict each other (a rejected case can't also expect a view).
- **Why proportion ranges, not "leg_scale > 1.1":** the planner can reach "very long legs" through `base.leg_ratio`, `overrides.leg_scale` or a different preset. The derived proportion is what the user actually gets, so that is what's checked. The thresholds are written next to the realistic-preset defaults in the YAML so they can be reviewed.
- **Extra-bone F1 (`evals/metrics/extras.py`):** extra bone names are sorted into 10 groups (hair, headwear, shield, held, gear, cloth, wings, horns, ears, tail) by whole-word matching. A first substring version would have filed `extra_cape` under headwear via "cap"; a test now pins that case, along with ponytail→hair and earring→other. F1 is computed over group counts, and a mirrored chain counts as two.
- **Runner (`evals/runner.py`, CLI `evals/run.py`):** the same graph as `rig-agent run`. Only its injectable `plan` dependency is wrapped, to keep each planner call's schema retries, which Q1 and Q9b need and the graph state doesn't hold. A crash is recorded as an `error` run instead of ending the suite. Each record is appended to `records.jsonl` as soon as its run ends, so an interrupted, paid-for suite keeps its data. `--rescore DIR` recomputes everything from that file with no model calls. Before a live run it asks for confirmation, and it refuses to start non-interactively without `--yes`.
- **One agent change:** `PlanResult.output_retries` holds the reason for each RigSpec the schema sent back (Pydantic AI `RetryPromptPart`s on the `final_result` output tool). A knowledge tool called with bad arguments doesn't count; a test proves that such a retry really happened and was still not counted.
- **Metrics (`evals/metrics/quantitative.py`, `expectations.py`):** Q1–Q13, each overall and per view. Q3–Q5 are reported twice: on delivered rigs, where the validator guarantees them, and on first attempts, as raw model quality (LLD 4.2). Pass/fail appears only where the LLD sets a target. Extra numbers (Q9 precision, pass@1, the modifier and bone-count rates) have no target and are shown for information. A metric that can't be measured shows `-` with the reason and never 0% or 100%: Q6b without side-view rigs, Q10 with k=1, Q12 cost without prices, Q13 without `--unity`. `report.md` also lists every failed expectation per run, which seeds the LLD 4.3 failure taxonomy.
- **Cost (Q12) takes prices as flags** (`--usd-per-mtok-in/out`); none are built in, because they change and differ per model. This is a first step toward the deferred per-rig cost item below, which is still open for `rig-agent run` itself. Also note that the guard's tokens are not in `UsageTotals` (the input_guard node only counts its request), so cost is planner-only until that is added.
- **Not built:** the LLM-as-judge and the human rubric (LLD 4.3; the H2 renders are their input), and the model comparison (LLD 4.4). The latter is two runs, one per provider, via `PRIMARY_PROVIDER`.
- **Verified offline only.** An end-to-end smoke run of 6 cases × k=2 through the real graph with a fake planner (which always returns the same front-view chibi knight) gave exactly the hand-checkable numbers: Q8 view 75% (only the side-view ninja is wrong), Q8 style 50% (chibi passes, the realistic villager doesn't), Q9 recall 0% (the fake guard accepts the horse), and Q6b/Q13 reported as not measured. `--rescore` reproduced `metrics.json` byte for byte. **No live run has been made yet:** it calls the real models 174 times at k=3, so it waits for the user.
- **Setup:** `evals/results/` is git-ignored, and ruff's `src` gained `"."` so `evals` sorts as first-party.
- **Tests:** 987 offline (was 903): 20 golden-set tests (LLD counts, view balance, consistency, loader errors, `select`), 20 extras tests, 23 metrics/report tests on hand-made records, 18 runner/CLI tests (repair, best effort, rejections, crashes, schema-retry capture, Unity status, `--rescore`, `--render`, and no live run without `--yes`), and 3 planner tests. `ruff check`, `ruff format --check` and `mypy src evals` are clean.

### First full eval: false rejections, a guard fix, and `--guard-only`

- **The user ran the full eval** (`evals/results/20260927-185506`: 174 runs, gpt-5.4-mini planner, gpt-5.4-nano guard). Q9 recall was 100% (18/18, right category every time). But the **false-reject rate was 8.5% (13/153, target ≤ 2%)**, and that alone pulled Q2 down to 91.5%. The user suggested moving the guard to mini.
- **Diagnosed before switching models:** 11 of the 13 were people with animal traits (fox girl with ears and a tail, demon with horns and wings, cat warrior), all rejected as `non_humanoid`, 3/3 runs each. The other two were a goblin (2/3) and a toddler (2/3). The cause is in the guard's own instructions: `non_humanoid` was defined as "animals…", every rejection example was an animal, and nothing said that animal traits *on a person* are fine, although the rigs handle them as extra bones. Every model reads those instructions, so switching to mini alone wouldn't remove the ambiguity.
- **Fixed (`guardrails/rules.yaml`, `input_guard.py`):** the accept rule now names any age (children included), fantasy races (goblins, orcs, demons, angels) and people with animal ears, tails, wings or horns. `non_humanoid` is now "a body that is not a person on two legs", stating that animal traits on a person don't count. New examples: "a wolf-eared ranger with a bushy tail" → ok, "an orc brute with tusks" → ok, "a small child with a backpack" → ok, "a wolf" → non_humanoid. They are deliberately *not* the golden prompts.
- **Found while testing that: four golden prompts were verbatim copies of the guard's examples** (`a centaur warrior`, `write me a poem about knights`, `an isometric 3/4 view rogue`, `a character`), so part of that 100% recall was the guard recognising its own examples. I reworded them with the same intent and expectations (`a centaur archer with a longbow`, `write me a short story about pirates`, `a rogue drawn in isometric three-quarter view`, `just some character`). A test now forbids any golden prompt from appearing verbatim in the guard prompt. The 20260927 run is therefore not directly comparable on those four cases.
- **Built `--guard-only` and `--guard-model`:** a guard-only run calls just the input guard per prompt (status `accepted`/`rejected`), costing a few cents instead of a full run, and reports only the four Q9 metrics. `accepted` counts as correct for valid prompts and for `reject_or_clamp`, since the planner's schema limits clamp the latter. `--guard-model` swaps the primary provider's guard model on a copy of the settings, so the config is untouched; it also works for full runs. Records now carry `mode` and `guard_model`, and the report header names the planner and the guard.
- **Measured (guard only, all 58 prompts × 3, fixed instructions; `evals/results/guard-nano/20260927-210901`, `guard-mini/20260927-210903`):**

  | Guard | Recall (≥ 95%) | False rejections (≤ 2%) | Precision | Median latency |
  |---|---|---|---|---|
  | gpt-5.4-nano | 100% | **3.3%** (5/153) FAIL | 80.8% | 1.09 s |
  | gpt-5.4-mini | 100% | **0%** (0/153) pass | 100% | 1.14 s |

  The instruction fix alone brought nano from 8.5% to 3.3%: the fox girl, demon, goblin and toddler are gone, and the cat warrior dropped from 3/3 to 1/3. Nano's remaining misses look erratic rather than a pattern in the instructions: `view_metroidvania` 2/3 as unsupported_view despite "seen from the side", and `sty_fashion_model` and `mod_long_legged_dancer` 1/3 each as ambiguous. Mini made no mistakes at practically the same latency.
- **Decision (the agreed rule): `guard_model` is now `gpt-5.4-mini`** (`config.py`; `.env.example`, README, COMMANDS and the tests that pin the default updated). A full `evals.run` is still needed to confirm Q2 with the new guard; the 20260927-185506 full run predates the fix.
- **Tests:** 999 offline (was 987). Guard-only runner/CLI tests cover metrics, rescoring, refusing `--render`/`--unity`, no live run without `--yes`, and the model swap leaving the settings unchanged. Other new tests: an expectation test for `accepted`, two guard-prompt tests (the animal-traits line and no golden prompt copied), and the model label in full records.

### HLD brought in line with the final implementation (2026-09-27)

- **Checked against the code, and still accurate:** structure, scope, the LLD references (§2.5, §3.8), the front-view default, the 14 required bones, and every metric and target (they match Q1–Q13 as `evals/metrics` computes them).
- **Updated (kept concise, no new sections):**
  - Output now mentions IK chains in the JSON, and native 2D bones, limb IK and prefabs in Unity.
  - The diagram gained the best-effort path and a "rejection + suggested rephrasing" label; the guard never asks clarifying questions.
  - The input guard is described as code checks followed by a small classifier.
  - New Orchestrator row (3 attempts, budgets, best-effort fallback) and Viewer row.
  - Exporter and Unity delivery rows describe IK and the install/verify/prefab flow; the IK row says "each limb that ends in a hand or foot", since hands are optional.
  - Observability is "optional tracing (Logfire)".
  - The test set is "58 prompts" instead of "about 60".
  - The model paragraph and the LLM row state the current choice (OpenAI primary, gpt-5.4-mini for planner and guard, Anthropic fallback; guard chosen by eval, linked to `GUARD_MODEL_COMPARISON.md`), and say the cross-provider comparison is still to run.
  - New Logfire framework row.
- **Still stale:** `HLD_2D_Humanoid_Rig_Agent.pdf` (see below). `pandoc` isn't installed, so it wasn't regenerated.

### README and COMMANDS simplified; Unity install guide added (2026-09-27)

- **README (179 → 86 lines):** what it is, requirements, a 4-command quick start, a new **Unity setup (one time)** guide, building a skeleton in Unity, evals, layout, and development commands.
- **The Unity setup guide covers:**
  - installing Unity **6000.4.0f1** (from `ProjectVersion.txt`) via Unity Hub with the **Android Build Support** module (OpenJDK, SDK & NDK);
  - opening `unity-project/` from the repo (MCP for Unity comes from GitHub, so `git` is required);
  - switching the platform to Android (*File → Build Profiles*); this is a per-machine step, because the active build target lives in `Library/`, not the committed settings;
  - `UNITY_PROJECT_PATH`;
  - starting the MCP for Unity HTTP server (Start Local HTTP Server via `uv`, Start Bridge);
  - `unity-check`.
- **COMMANDS (399 → 170 lines):** now the single reference: a command-picker table, one shared status/exit-code table, and short sections per command. The Unity options are in one table, and troubleshooting has new rows for the Unity version, the Android module, the MCP menu (git) and uv. Nothing is explained at length in both files.
- **Stale facts fixed:** 999 offline tests (was "about 600"), 6 live Unity tests, 6 C# scripts (the list named 4), and the dropped internals (placeholder sprite, IK ticker) are left to the LLD.
- The Android switch and the server start are Editor steps; they are documented, not executed here.

### Second full eval, with the fixed guard on gpt-5.4-mini (2026-09-28)

`evals/results/20260928-193441` (58 prompts × 3). The two targets the first run missed now pass:
**Q2 final validity 100%** (was 91.5%) and **Q9 false rejections 0%** (was 8.5%). Q1 first-pass validity 100%, view accuracy 100%, extras F1 0.986, recall and precision 100%, pass@1 100%, p95 latency 10.0 s, about 41k tokens per rig.

Still missed: **Q8 style match 83.3%** (target ≥ 90%) and **Q10 same heads-tall bucket 80.4%** (≥ 90%). Diagnosed as planner-prompt gaps, not code (fixes deferred, see below):
- "a bodybuilder with a tiny head" sets `heads_tall = 2` (the biggest head) in 3/3 runs: the model misreads heads_tall, possibly primed by the monster few-shot example.
- neutral prompts (wizard, pirate, samurai, angel) flip between `realistic` (7.5 heads) and `stylized` (6), right across the 6.5 bucket line;
- descriptors are not mapped to proportions: cartoon kid, fashion model and lanky elf all get the stylized 6 heads.

One failure is the golden set's: `acc_cat_warrior` (side view) expects one ear, and the planner reasonably gives a pair.

### Phase M1: animation core (no model, no Unity)

- **Spec and clip:** `AnimationSpec` has a clip type plus bounded knobs (speed, stride, bounce, arm swing, knee lift, lean, fps). `AnimationClip` (`animation.json`) holds, per frame, every animated bone's local rotation, the hip position and every IK target's position and rotation. Clips are in place, and a gait records the `ground_speed` a game should move the character at so planted feet don't slide.
- **Motion:** periodic, phase-based templates. The baker solves the legs with two-bone IK using the rig's own `bend_side` (the same convention as Unity's `LimbSolver2D.flip`), lowers the hip if a leg can't reach, and reads the IK targets off the final pose. So rotation curves and targets describe the same motion; FK reproduces `skeleton.json` to 1e-6.
- **Validator:**
  - IK targets on their effectors;
  - knees and elbows bend only their own way;
  - torso and ankles in range;
  - planted feet move at the ground speed;
  - nothing goes below the floor;
  - a loop's closing frame equals its first.
- **Two bugs found by sweeping every knob combination:** the ground speed ignored whole-frame rounding of the cycle (fast runs slid 0.65%/frame), and a heuristic loop check misfired on correct 12 fps clips. It was replaced by an exact closing frame.
- **Also built:** `animate-build`; clips in `<rig>/animations/`, which `delete` also removes; and viewer playback (Animation panel: play, scrub, onion skin, a moving ground to judge foot slip). The viewer's JS forward kinematics is cross-checked against Python to 1e-9.

### Phase M2: animation in Unity

- **`RigAnimImporter.cs`** builds an AnimationClip from a flattened request (JsonUtility can't read dictionaries). It uses linear keys, bone rotation curves, hip position curves and IK target curves. It saves the `.anim` beside the rig's generated assets and adds an Animator Controller and an Animator (the clip imported last is the default state).
- **The check:** at 4 frames it samples the clip, then lets Unity's own IK re-solve from the targets, and Python compares both with its FK. Live on the knight's walk: the curves match to 1.2e-4 and the IK re-solve to 3.5e-6. A deliberately broken clip (a foot target 0.1 off) is caught on every sampled frame.
- **`RigShapes.cs`:** placeholder capsules on every bone but the root (coloured by side, sorted by depth, 9-sliced so the ends stay round), so motion is visible without art. Confirmed with Play-mode screenshots.
- **Also:** `unity-apply-anim`, and `animate-build --unity`. One new MCP menu item was allowlisted.

### Phase M3: animation planner and pipeline (`rig-agent animate`)

- **Guard:** the same code checks as the rig guard, plus a motion classifier with a new `unsupported_motion` category. It needs its own prompt because the rig guard asks "is this a humanoid?".
- **Planner:** a Pydantic AI agent with the rig as its dependency. `preview_clip` bakes and validates a draft on the real rig and reports it in numbers. The settings table in the prompt is generated from the schema's own bounds. The worked examples are checked to bake and pass.
- **Pipeline:** a LangGraph flow like `run`, with shared budgets (`graph/budget.py`) and tracing.
- **Decisions (user):** a walk, run or backflip on a front-view rig stops with a clear message (nothing is swapped in); unsupported motions are refused with a suggestion; files are named from the description.
- **Live check:** heavy walk, energetic jog, sneaking and a front-view idle all passed first time, the front-view walk stopped as intended, and a backflip (then unsupported) was refused. About 4,300 tokens and 4–7 s per request. Two bugs found and fixed: `animate --unity` exited 0 when the Unity import failed, and a missing rig produced noisy errors.
- **Observed:** the planner copies its worked examples verbatim for close prompts, so the animation golden set must avoid their wording; "energetic jog" came out as a fast run.

### Phase M3b: backflip

- **The motion:** crouch → take off → one 360° backward turn about the hip with the knees tucked → land and absorb. It's side view only, plays once, stays in place, and starts and ends at rest. In the air the feet are placed relative to the turning body, so Unity's IK reproduces them.
- **Jump height per rig:** a fixed jump let chibi heads and the knight's sword go through the floor. The baker now bakes once, measures how far each airborne frame dips below the floor, and raises the arc's peak just enough (one correction suffices, because the lift is uniform per frame).
- **Whole-body floor check:** props already on the floor at rest (the mage's staff) are exempt, because they would stay planted.
- **Steady wrists:** a hand holding an accessory turns against the arm's swing, capped at 70°, in every clip. This fixes the sword sweeping into the floor in the crouch and over the head in the run.
- **Tried and reverted:** capping the ankle in the baker (it pushed toes into the floor).
- **Result:** every clip at default settings passes on 7 rigs, and every backflip passes across all knob combinations. In Unity the upside-down frame matches to 1.9e-4 after IK re-solve.

### Deferred (decided to do later)

- ~~**Skeleton preview**~~ **Done as a browser viewer** (`viewer/`, see the README). It loads `skeleton.json` and `validation_report.json`, auto-reloads a served file, and supports depth and IK colouring, selection, and PNG export. The offline Python renderer for the eval harness is H2, now done (see *Phase H2* above).
- **Natural-language edit** (`rig-agent edit spec.json "make the legs longer"`). It can reuse the repair machinery: current spec plus an instruction.
- **Validate command for a skeleton file**, so a hand-edited `skeleton.json` can be checked.
- **Plausibility warning for held items that cross the body** (found in a real model run: a sword swung across the center line). Candidate for the eval phase.
- **Report the dollar cost of a rig, not just token counts.** `run` already prints `X model calls, Y tool calls, Z tokens` (`UsageTotals` in `schemas/state.py`: `requests`, `tool_calls`, `input_tokens`, `output_tokens` separately, and `Skeleton.metadata.model` already records which model produced it) — what's missing is a $-per-token price table (input and output differ, and differ again between `gpt-5.4-mini`/`gpt-5.4-nano` and the Anthropic fallback `claude-sonnet-5`/`claude-haiku-4-5-20251001`) to turn that usage into an actual dollar figure per skeleton. Natural home: a `pricing.py` (or a section of `config.py`) with a per-model rate table, a small `estimate_cost(usage, model) -> float` helper, and print it alongside the existing usage line in `run`'s summary; consider also writing it into `metadata` or a sibling field in `skeleton.json` so a rig's own cost travels with it. Directly serves the LLD's Q12 cost-per-rig target (≤ $0.05/rig) — a natural candidate to build as part of the Phase H eval work, but useful standalone too.
- **Editing today:** change the `RigSpec` (`spec.json`) and re-run `rig-agent build`. Editing `skeleton.json` directly is not supported.
- **Rig planner prompt fixes** (from the second full eval):
  - state that a smaller heads_tall means a bigger head;
  - default to `realistic` unless the prompt signals stylization;
  - add a descriptor → heads_tall table (toddler 3–4, child 4.5–5.5, adult 7–8, heroic 8, fashion 8.5–9);
  - change `acc_cat_warrior`'s golden expectation to two ears.
- **Animation:** M4 evals (avoid the planner examples' wording); a slower default for "jog"; the `style` label should describe the motion; a prefab saved before a clip lacks the Animator, and re-importing a rig replaces its Animator; a chibi side-view run at extreme knee lift trips the ankle limit (repair lowers it).


- **Front-view foot direction.** LLD §2.8 currently makes the foot point sideways. You may prefer it to point down. Decide before B3.
- **HLD PDF.** The old `HLD_2D_Humanoid_Rig_Agent.pdf` is gone; if a PDF is needed, generate it from `SYSTEM-DESIGN.md`.

## 9. Verification

- **Every step:** `uv run pytest -q`, `uv run ruff check .` and `uv run mypy src`.
- **Milestone 1:** `uv run rig-agent build --spec examples/knight_side.json` produces a `skeleton.json` and a passing report. Repeat for a front-view spec.
- **Milestone 2:** `uv run rig-agent run "chibi knight with a big sword"` with a live API key.
- **Unity:** import the JSON with the menu item and rotate limbs in the Scene view.
