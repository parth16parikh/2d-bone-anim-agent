# Commands: what to run, when, and what you get

All commands run from the project folder (the one that contains `pyproject.toml`):

```bash
cd "/Users/parth/AI Cohort/Capstone Project/Project/2d-bone-anim-agent"
```

## 0. One-time setup

```bash
uv sync --all-extras     # install everything
```

**API key** (needed only by `run` and `plan`). Use one of these:

| Way | How |
|---|---|
| `.env` file (recommended) | Edit `.env` in this folder: `OPENAI_API_KEY=sk-...` (no quotes, no spaces). The file is git-ignored. |
| Shell variable | `export OPENAI_API_KEY=sk-...` in the terminal you run commands from. |

Optional: `ANTHROPIC_API_KEY` adds a failover provider. See `.env.example` for every setting.

`build`, the viewer and all tests need **no key**.

---

## 1. Which command do I want?

| I want to... | Run | Needs key? | Calls the model? |
|---|---|---|---|
| Go from a text description to a validated rig | `run` | yes | yes (a few cents) |
| Only see what spec the model would write | `plan` | yes | yes |
| Rebuild a rig after editing a spec by hand | `build` | no | no |
| Replace an existing rig in `out/` | just `run`/`build` with the same `--out` folder | same as above | same as above |
| Remove one or more rigs from `out/` | `delete` | no | no |
| Look at any rig in `out/` | `view` | no | no |
| Build the rig in my open Unity Editor | `run --unity` or `unity-apply` | `run`: yes; `unity-apply`: no | `run`: yes |
| Build **every** rig of `out/` in Unity, side by side | `unity-apply-all` | no | no |
| Save verified rigs as prefabs | add `--prefab-dir Assets/...` to any Unity command | no | no |
| Check the Unity connection | `unity-check` | no | no |
| Check that the code still works | `pytest`, `ruff`, `mypy` | no | no |

---

## 2. The pipeline commands

### `run`: description in, validated rig out (the full pipeline)

```bash
uv run rig-agent run "chibi knight with a big sword" --out out/knight
uv run rig-agent run "ninja for my platformer" --view side --out out/ninja
```

| Part | Meaning |
|---|---|
| `"..."` | The character description (max 1,000 characters). |
| `--view front\|side` | Force the view. Without it, the planner infers it (default front). |
| `--out DIR` | Output **folder** (default `out`). |
| `--unity` | After a passing rig is exported, also build it in the open Unity Editor and verify it (see `run --unity` below). Needs `UNITY_PROJECT_PATH`. |

**What it does:** input guard, then plan, build and validate. If validation fails, the errors go back to the planner and it tries again, up to 3 attempts, within a budget of 12 model calls, 15 tool calls, 60 seconds and 150,000 tokens.

**Output files** (in `--out`):

| File | Contents |
|---|---|
| `skeleton.json` | The rig: every bone with world and local transforms, depth, layer, IK chain. |
| `validation_report.json` | `passed`, the list of issues, and metrics (connectivity, symmetry, proportion error). |

**On the terminal** (progress goes to stderr, the result to stdout):

```
[guard] Input guard (gpt-5.4-nano) ...
[guard] accepted
[plan 1/3] Planner (gpt-5.4-mini) ...
  [  2.1s] -> list_vocabulary()
  [  2.1s] <- list_vocabulary: ok
[plan 1/3] done: 4 model calls, 3 tool calls, 5,210 tokens in, 890 out
[build] 21 bones
[validate] attempt 1: PASSED (0 errors, 0 warnings, score 1.00)
[export] wrote out/knight/skeleton.json and validation_report.json
Finished in 13.6s: 1 attempt(s) (scores 1.00), 4 model calls, 3 tool calls, 6,100 tokens
Status: success
skeleton: out/knight/skeleton.json
report:   out/knight/validation_report.json
```

**Status and exit code:**

| Status | Exit code | Meaning |
|---|---|---|
| `success` | 0 | Passed validation. Files exported. |
| `best_effort` | 1 | Repairs or budget ran out. The best attempt is exported with a **failing** report. Not import-ready. |
| `rejected` | 1 | The input guard refused the request (reason and suggestion printed). No files. |
| `error` | 2 | Missing key, model failure, or nothing could be built. |

**When to use it:** normal use. It is the only command that repairs mistakes automatically.

---

### `plan`: description in, RigSpec out (no rig built)

```bash
uv run rig-agent plan "chibi knight with a big sword" --out spec.json
uv run rig-agent plan "ninja" --view side            # prints the spec instead of saving it
```

| Part | Meaning |
|---|---|
| `--out FILE` | Path of a **file** to write the spec to (note: a file, unlike `run` and `build`). Without it, the spec prints to the terminal. |
| `--view` | As in `run`. |

**What it does:** input guard, then one planner run, then a dry run (build and validate in memory). No repair loop.

**Output:** `spec.json`, a `RigSpec`: preset, view, pose, proportions, optional bones, extra bones (hat, cape, weapon) and the model's assumptions.

**Exit code:** 0 if the spec passes the dry run, 1 if the request is rejected or the dry run fails, 2 on a missing key or model failure.

**When to use it:** to see or edit what the model decided before building. Then run `build` on it.

---

### `build`: RigSpec in, rig out (no model, no key)

```bash
uv run rig-agent build --spec spec.json --out out/knight
uv run rig-agent build --spec examples/knight_side.json --out out/knight
```

| Part | Meaning |
|---|---|
| `--spec FILE` | A RigSpec JSON file (required). |
| `--out DIR` | Output **folder** (default `out`). |
| `--prompt "..."` | Text stored in the skeleton's `source_prompt` (optional). |

**Output:** `skeleton.json` and `validation_report.json`, the same as `run`. It always writes both, even when validation fails.

**On the terminal:** four stages (read spec, build, validate, export), then a short result.

**Exit code:** 0 passed, 1 validation failed (files still written), 2 the spec could not be read or built.

**When to use it:** after hand-editing a spec, or to try a hand-written spec. Also for offline work. It takes about 0.01 seconds.

**Bundled example specs:** `examples/knight_side.json` (side view), `examples/elf_front.json` (front, cape), `examples/chibi_mage_front.json` (T-pose, hat, ponytails, staff).

**Replacing a rig:** `run` and `build` always overwrite whatever is already at `--out DIR`; there is no separate "override" command or flag. If `out/DIR/skeleton.json` already exists, both commands print `note: replacing the rig already at out/DIR` before writing, so a replace is never silent.

---

### `delete`: remove one or more rigs from `out/`

```bash
uv run rig-agent delete out/knight                # one rig
uv run rig-agent delete out/knight out/elf         # several, in one call
uv run rig-agent delete --all --out out            # every rig under out/
```

Removes only `skeleton.json` and `validation_report.json` from each folder (never anything else you put there), and removes the folder itself only if that leaves it empty. A folder that has neither file (a typo, or a folder the agent never wrote to) is refused rather than silently skipped, and any other file in it (a `spec.json` copy, your own notes) is left alone and keeps the folder from being removed. `--all` uses the same rig discovery as `unity-apply-all`, so it skips (and reports) a folder whose `skeleton.json` cannot be read, and is a no-op, not an error, when `out/` is already empty. It never touches Unity or your prefabs. **Exit code:** 0 all named folders deleted, 2 a folder did not exist or wasn't a rig folder, or the arguments were wrong (both `--all` and folders, or neither).

---

### `unity-check`: is Unity ready to receive a rig?

```bash
uv run rig-agent unity-check
```

Connects to the MCP for Unity server and prints the server, the Unity version, the open scene, whether the editor is ready, the tools available, whether the 5 tools rig-agent needs are present, the configured project and whether the C# scripts are installed. **Exit code:** 0 ready, 2 unreachable or something missing. **When:** first, whenever a Unity delivery fails, and after starting Unity.

### `unity-install`: put the C# scripts into the Unity project

```bash
uv run rig-agent unity-install                # uses UNITY_PROJECT_PATH
uv run rig-agent unity-install --project "/path/to/unity/project"
```

Copies `RigImporter.cs`, `RigSkin.cs`, `BoneGizmo.cs` and `FacingController.cs` into `Assets/RigAgent/` and creates `Assets/Rigs/`. It only rewrites files that changed. Unity recompiles by itself. **When:** usually not needed, because the first delivery does it automatically; use it after updating rig-agent to refresh the scripts.

### `unity-apply`: deliver an existing rig to Unity

```bash
uv run rig-agent unity-apply out/knight/skeleton.json
```

Writes the skeleton to `Assets/Rigs/skeleton.json`, runs the import menu item, then verifies what Unity built against the file (bone count, names, parents, depth, layer, positions within 1e-3) and checks the console. No model is involved. **Exit code:** 0 applied and verified, 1 the import or verification failed (details printed), 2 Unity unavailable. **When:** to send a rig you already built, or to re-send after clearing the scene.

### `unity-apply-all`: build every rig of `out/` in Unity

```bash
uv run rig-agent unity-apply-all                        # every out/<folder>/skeleton.json
uv run rig-agent unity-apply-all --out out/batch2       # another folder
uv run rig-agent unity-apply-all --prefab-dir Assets/Prefabs/Rigs
```

Finds every `<folder>/skeleton.json` under `out/`, clears the previous rigs under `RigAgent_Output`, and builds them in one row, side by side, each named after its **folder** (`out/knight2` becomes the object `knight2`, so runs of the same prompt do not overwrite each other). Every rig is verified like a single one and printed as a table. Unreadable `skeleton.json` files are skipped and named. **Exit code:** 0 all built, 1 some failed, 2 Unity unavailable or no rigs found.

### IK: `--no-ik` (with `unity-apply`, `unity-apply-all`, `run --unity`)

By default every arm (that has a hand) and every leg gets a Limb IK solver and a target, under an `IK` object on the rig root: `IK/arm_R/target_hand_R` and so on. In the Scene view, **move the target** (not the bone): the arm or leg follows and stays connected, and a foot stays flat as the leg moves. A weapon or a toe past the hand or foot (`extra_sword`, `toe_L`/`_R`) is a rigid child of it, not a separate solved link — it turns along with the hand or foot through ordinary parenting, and stays attached whichever way the limb bends (verified on the knight example: dragging the arm and leg targets left the sword's and toe's offset from their parent unchanged, no stretch or detachment). Each solver is verified (one valid solver per chain, bending to the side the JSON says). `--no-ik` builds the bones without solvers. Prefabs made while IK was off do not have it; add `--overwrite-prefab` to regenerate them (which discards edits you made to them).

Dragging a target does the bending: a small `RigIkTicker` script solves every rig's IK once per editor frame, since Unity's own automatic re-solve (`IKManager2D.LateUpdate`) does not fire reliably for a manager built by a menu item. You should not need to do anything for this; it installs alongside the other scripts.

### Prefabs: `--prefab-dir` (with `unity-apply`, `unity-apply-all`, `run --unity`)

```bash
uv run rig-agent unity-apply-all --prefab-dir Assets/Prefabs/Rigs
uv run rig-agent unity-apply out/elf/skeleton.json --prefab-dir Assets/Prefabs/Rigs --overwrite-prefab
```

After a rig is **verified in Unity**, and only if its `validation_report.json` says it **passed**, it is saved as `<folder>/<rig name>/<rig name>.prefab`, in a folder of its own that also holds the rig's `<rig name>_placeholder.png` and `<rig name>_skeleton.asset` (root at the origin, `SpriteSkin` and `FacingController` included). The folder must be inside `Assets/` and is created if missing. An existing prefab is **kept** (you may have edited it); `--overwrite-prefab` replaces it. Set `UNITY_PREFAB_DIR` in `.env` to make it the default; `--prefab-dir ""` turns it off. In the batch table, the detail says `prefab created`, `updated` or `kept`, or why a rig got none.

### `run --unity`: the whole pipeline, ending in Unity

```bash
uv run rig-agent run "chibi knight with a big sword" --view side --out out/knight --unity
```

The same as `run`, and after a **passing** rig is exported, the `[unity]` stages deliver and verify it. A rig that fails validation is exported but never sent to Unity. If Unity is unreachable the run still ends `success`, with `unity: unavailable`.

**In Unity:** the rig appears under `RigAgent_Output` in the open scene as bones drawn by Unity's 2D Animation package (select the rig to see them), on a transparent placeholder sprite; the sprite and a skeleton asset are written to `Assets/Rigs/Generated/<rig>/` (or beside the prefab). Re-importing a rig with the same name replaces it. **Tools > Rig Agent > Clear Output** removes all rigs, and the scene is left unsaved. Setup: see the README section "Unity delivery".

---

## 3. Looking at a rig (the viewer)

**Pick from `out/` (recommended):**

```bash
uv run rig-agent view --open          # --out DIR (default out), --port N (default 8000)
```

Opens `http://127.0.0.1:8000/`. The sidebar section **Rigs in out/** lists every rig (folder, view, bones, `ok`/`FAILED`/`no report`), newest first. Choose one and the viewer shows it with its validation report. The list refreshes every few seconds and the chosen rig reloads when its files change. The server only serves `viewer/` and `out/` on `127.0.0.1` (not `.env` or the source). Stop it with Ctrl+C.

**Quick look (no server):** open `viewer/index.html` in a browser, then drop `skeleton.json` (and `validation_report.json`) on the page, or use *Choose files*. *Load a sample* shows three built-in rigs.

**Plain http.server (no rig list, serves the whole folder including `.env`, so prefer `view`):**

```bash
python3 -m http.server 8000                  # leave running, in the project folder
```

Open: `http://localhost:8000/viewer/index.html?src=/out/knight/skeleton.json`

Now every `run` or `build` into `out/knight` refreshes the picture within 1.5 seconds and loads the report from the same folder.

Useful URL options: `&select=hand_R`, `&color=depth` (or `ik`), `&labels=0`, `&bounds=1`, `&flip=1`, or `?sample=knight_side`.

Mouse: scroll to zoom, drag to pan, click a bone for details. Keys: `F` fit, `L` labels, `Esc` deselect.

**What to check:** the shape looks like a person, arms and legs are symmetric (front) or stacked near and far (side), accessories point away from the body, dashed lines appear only at the limb roots, hip and jaw, and the red rings mark bones named in validation issues.

---

## 4. Checking the project itself

| Command | Purpose | Takes |
|---|---|---|
| `uv run pytest -q` | All offline tests (about 600), including the viewer's Node tests. | ~3 s |
| `uv run pytest -q tests/test_graph.py` | One test file, for example the repair loop. | <1 s |
| `uv run pytest -m live` | 3 tests that call the **real** API (need a key, cost a few cents). Skipped otherwise. | ~30 s |
| `uv run ruff check .` | Lint. | <1 s |
| `uv run ruff format src tests scripts` | Auto-format. | <1 s |
| `uv run mypy src` | Type check. | ~5 s |
| `node --test viewer/viewer.test.js` | Only the viewer's tests (needs Node). | <1 s |
| `uv run pytest -m unity` | 5 tests against a **real, running Unity** with the MCP server started (skipped if unreachable). They add rigs to the open scene. | ~10 s |

**When to run:** after changing code. `pytest`, `ruff check` and `mypy` should all be clean.

---

## 5. Utilities

| Command | Purpose |
|---|---|
| `uv run python scripts/make_viewer_samples.py` | Regenerate `viewer/samples.js` from `examples/*.json`. Run it after changing the builder or the examples (a test fails if the samples are stale). |
| `uv run python -c "from rig_agent.graph.build_graph import build_graph; print(build_graph().get_graph().draw_mermaid())"` | Print the pipeline graph as a Mermaid diagram. |
| `uv run rig-agent --help` | List the commands. Also `run --help`, `plan --help`, `build --help`. |

---

## 6. Typical workflows

**F. Clean up after trying a few ideas**
```bash
uv run rig-agent delete out/attempt1 out/attempt2   # a couple of rigs you don't want
uv run rig-agent delete --all --out out             # or start out/ over completely
```

**A. Make a rig from an idea (everyday)**
```bash
uv run rig-agent run "tall elf archer with a long cape" --out out/elf
uv run rig-agent view --open          # pick the rig from the list
```

**B. Not happy with the result? Tweak the spec by hand**
```bash
uv run rig-agent plan "tall elf archer with a long cape" --out spec.json
# edit spec.json: e.g. change "direction_deg", add "shoulders" to optional_bones,
# or add "overrides": {"leg_scale": 1.2}
uv run rig-agent build --spec spec.json --out out/elf     # instant, no model
```
Editing the spec is the only supported way to change a rig. Do not hand-edit `skeleton.json`.

**C. The run ended `best_effort` or `FAILED`**
1. Read the issues printed at the end, or open `validation_report.json`.
2. Look at the rig in the viewer (the red rings show the problem bones).
3. Fix the spec (workflow B), or rerun with a clearer description or `--view`.

**E. Put everything from `out/` into Unity and keep the good ones as prefabs**
```bash
uv run rig-agent unity-apply-all --prefab-dir Assets/Prefabs/Rigs
```
Existing prefabs are kept as they are (add `--overwrite-prefab` to replace them).

**D. Working offline or without a key**
```bash
uv run rig-agent build --spec examples/knight_side.json --out out/knight
```

---

## 7. Output files at a glance

| File | Made by | Read by |
|---|---|---|
| `spec.json` (any name) | `plan --out` | `build --spec` (you can edit it) |
| `<out>/skeleton.json` | `run`, `build` | the viewer; the Unity importer |
| `<out>/validation_report.json` | `run`, `build` | the viewer; you |

`skeleton.json` key fields: `view`, `rest_pose`, `height`, and a `bones` list (each with `id`, `name`, `parent_id`, `world_head`, `world_tail`, `local_position`, `local_rotation_deg`, `length`, `depth`, `layer`, `ik_chain`, `mirror_of`), and an `ik_chains` list (schema 1.1) naming each arm and leg chain's root, joint and effector bones and which side of the limb line its elbow or knee bends to (`bend_side`).

---

## 8. Troubleshooting

| You see | Cause and fix |
|---|---|
| `OPENAI_API_KEY is not set` (or `No API key is set`) | Add the key to `.env` in this repository's root, or export it. |
| `the model run failed: ...` | The API returned an error (wrong key, no access to the model, network). The message has the details. |
| `Request not accepted (non_humanoid)` | The guard refused the request. Describe a two-legged humanoid. Only front and side views are supported. |
| Viewer says `Could not load ...` | You opened the page from disk with `?src=`. Use `uv run rig-agent view` instead, or drop the file on the page. |
| No *Rigs in out/* list in the viewer | You opened `viewer/index.html` from disk. Start `uv run rig-agent view` and use the address it prints. |
| `unity-apply-all`: `No rigs found` | `out/` has no `<folder>/skeleton.json`. Pass `--out` with the right folder. |
| Prefab was not replaced | An existing prefab is kept on purpose. Add `--overwrite-prefab` to replace it. |
| Viewer shows an old rig | Check the `?src=` path points at the folder you built into, and that *Auto-reload* is ticked. |
| `cannot reach the Unity MCP server` | Unity is closed or the server is stopped. Open Unity, start **Window > MCP for Unity**, then run `unity-check`. The URL must end in `/mcp`. |
| `UNITY_PROJECT_PATH is not set` | Add `UNITY_PROJECT_PATH=unity-project` to `.env` (the Unity project folder, the one that contains `Assets/`; a relative path is taken from this repository's root). |
| `unity-check` says `is not a Unity project`, or Unity does not react to a delivery | `UNITY_PROJECT_PATH` and the project open in Unity must be the **same folder**. After moving the project, close Unity, reopen it from the new location, restart **Window > MCP for Unity**, and check that `unity-check` shows the new path. |
| Unity delivery says `failed` with compile errors | Open the Unity console. Fix the errors, then rerun (the scripts are re-checked each time). |
| `command not found: uv` | Install uv, or activate the virtual environment: `source .venv/bin/activate` and drop the `uv run` prefix. |
