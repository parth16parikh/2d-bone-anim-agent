# Commands

Run everything from the repository folder (the one with `pyproject.toml`). For installation, the API key and Unity setup, see the [README](README.md). `uv run rig-agent <command> --help` lists every option.

## Which command?

| I want to... | Run | API key? |
|---|---|---|
| Turn a description into a validated rig | `run` | yes |
| See the spec the model would write, without building | `plan` | yes |
| Rebuild a rig from a spec (for example after editing it) | `build` | no |
| Look at the rigs in `out/` | `view` | no |
| Remove rigs from `out/` | `delete` | no |
| Build a rig in the open Unity Editor | `run --unity` or `unity-apply` | `run` only |
| Build every rig in `out/` in Unity | `unity-apply-all` | no |
| Check the Unity connection | `unity-check` | no |
| Score the agent on the golden set | `python -m evals.run` | yes |
| Draw rigs to PNG files | `python -m evals.render_skeleton` | no |
| Animate a rig from a description | `animate` | yes |
| Animate a rig with chosen settings | `animate-build` | no |
| Put a clip on its rig in Unity | `unity-apply-anim` or `animate-build --unity` | no |

## Status and exit codes

`run` ends with one of these statuses:

| Status | Exit | Meaning |
|---|---|---|
| `success` | 0 | Passed validation; files written. |
| `best_effort` | 1 | Repairs or budget ran out; the best attempt is written with a failing report. Not import-ready. |
| `rejected` | 1 | The input guard refused the request; the reason and a suggested rephrasing are printed. |
| `error` | 2 | Missing key, model failure, or a spec that can't be read or built. |

`plan` and `build` use the same exit codes: 0 when the spec or rig passes, 1 when the request is rejected or validation (or `plan`'s dry run) fails (`build` still writes the files), 2 on errors.

## Making rigs

### `run`: description → rig

```bash
uv run rig-agent run "chibi knight with a big sword" --out out/knight
uv run rig-agent run "ninja for my platformer" --view side --out out/ninja
```

It guards, plans, builds and validates, and repairs up to 3 times within a budget of 12 model calls, 15 tool calls, 60 s and 150,000 tokens. `--view front|side` forces the view (otherwise it's inferred; the default is front). `--out` is a **folder** (default `out`). It writes `skeleton.json` and `validation_report.json`. Running again into the same folder replaces the rig, with a printed note. Add `--unity` to also build the rig in Unity (see [Unity](#unity)).

### `plan` and `build`: change a rig by hand

```bash
uv run rig-agent plan "tall elf archer with a long cape" --out spec.json   # the model's RigSpec
# edit spec.json, e.g. "overrides": {"leg_scale": 1.2} or an extra bone's "direction_deg"
uv run rig-agent build --spec spec.json --out out/elf                      # no model, instant
```

`plan` runs the guard and one planner pass, with no repair loop, and writes a **file** (or prints it if you leave out `--out`). `build` needs no key; `--prompt "..."` records a source prompt. Editing the spec is the supported way to change a rig; don't hand-edit `skeleton.json`. The bundled specs are `examples/knight_side.json`, `examples/elf_front.json` and `examples/chibi_mage_front.json`.

### `delete`

```bash
uv run rig-agent delete out/knight out/elf     # named rigs
uv run rig-agent delete --all --out out        # every rig in out/
```

Removes only `skeleton.json`, `validation_report.json` and `skeleton.png`, plus the folder if that leaves it empty. It refuses folders that aren't rigs, and never touches Unity or prefabs.

## Unity

Setup is in the [README](README.md#unity-setup-one-time): Unity 6000.4.0f1 with Android Build Support, the platform switched to Android, and the MCP server started.

```bash
uv run rig-agent unity-check                                   # is Unity ready? (run this first)
uv run rig-agent run "a samurai with a katana" --view side --out out/samurai --unity
uv run rig-agent unity-apply out/knight/skeleton.json          # send an existing rig
uv run rig-agent unity-apply-all                               # every rig in out/, side by side
uv run rig-agent unity-install                                 # refresh the C# scripts (usually automatic)
```

| Option (for `unity-apply`, `unity-apply-all`, `run --unity`) | Meaning |
|---|---|
| `--prefab-dir Assets/Prefabs/Rigs` | Save each verified, passing rig as `<dir>/<rig>/<rig>.prefab`. Or set `UNITY_PREFAB_DIR` in `.env`. |
| `--overwrite-prefab` | Replace an existing prefab (by default it's kept, since you may have edited it). |
| `--no-ik` | Build the bones without IK solvers. |
| `--out DIR` | (`unity-apply-all`) Folder of rigs, default `out`. |

- **How it works:** each delivery writes `Assets/Rigs/skeleton.json`, runs *Tools → Rig Agent → Import Latest Skeleton*, and checks what Unity built against the JSON (bones, parents, positions). Only a small allowlist of MCP calls is used.
- **In the scene:** rigs appear under `RigAgent_Output`; `unity-apply-all` names each rig after its folder. *Tools → Rig Agent → Clear Output* removes them.
- **IK:** arms (with hands) and legs get a Limb solver. Drag the targets under `IK/`, not the bones. Weapons and toes follow the hand or foot rigidly.
- **Generated assets:** each rig's placeholder sprite and skeleton asset go in `Assets/Rigs/Generated/<rig>/`, or next to its prefab. They're rewritten on every import.
- **Exit codes:** 0 built and verified, 1 import or verification failed, 2 Unity unreachable (or, for `unity-apply-all`, no rigs found). With `run --unity`, an unreachable Unity doesn't fail the run: the JSON is already written.

## Animation

**From a description** (needs an API key; the planner chooses the clip and its settings):

```bash
uv run rig-agent animate out/knight "a heavy, tired walk"          # -> out/knight/animations/heavy_tired_walk.json
uv run rig-agent animate out/knight "an energetic jog" --unity     # ...and put it on the rig in Unity
uv run rig-agent animate out/knight "sneaking past a guard" --name sneak
```

It guards the request, plans an AnimationSpec (it previews each draft on your rig), bakes, validates and repairs up to 3 times, then writes the clip. Supported motions are **idle, walk, run and a standing backflip** (walk, run and backflip need a side-view rig):
- anything else (front flip, jump, attack, dance) is refused, with a suggested alternative;
- a walk, run or backflip on a front-view rig stops with a message, because those need a side-view rig.

Exit codes are as for `run`, plus 1 when `--unity` was asked and the Unity import failed.

**By hand** (no model):

```bash
uv run rig-agent animate-build --rig out/knight --clip walk            # idle (both views); walk, run, backflip (side view)
uv run rig-agent animate-build --rig out/knight --spec heavy.json --name heavy_walk
uv run rig-agent animate-build --rig out/knight --clip run --unity      # ...and put it on the rig in Unity
uv run rig-agent unity-apply-anim out/knight/animations/walk.json       # send an existing clip
```

- **Backflip:** plays once and starts and ends in the rest pose. The jump is always high enough for the whole body (and anything held) to clear the floor; `bounce` adds height, `knee_lift` tightens the tuck. In Unity its Animator plays it once when you press Play (tick *Loop Time* on the clip to repeat it).
- **What it does:** bakes an in-place clip onto the rig: bone rotations, the hip bob and the IK targets for every frame. Then it validates the clip: planted feet don't slide, nothing goes below the ground, knees and elbows bend the right way, and the loop closes. It writes `out/<rig>/animations/<name>.json` and a `.report.json`.
- **Spec file:** `--spec` is an AnimationSpec, for example `{"clip": "walk", "style": "heavy", "speed": 0.7, "stride": 1.2, "bounce": 0.5, "arm_swing": 1.0, "knee_lift": 1.0, "lean_deg": 8, "fps": 24}`. Every knob is bounded, and 1.0 (0 for lean) is neutral.
- **Ground speed:** the clip records a `ground_speed` (units/s). Move the character at that speed in the game and the feet stay planted.
- **In Unity** (the rig must be imported first): the clip becomes `<clip>.anim` in the rig's generated folder. The rig gets an Animator whose default state is the latest clip, so press **Play**. The check samples frames and also lets Unity's own IK re-solve from the animated targets; both must match the clip. Rigs imported now also get **placeholder capsules** on every bone, so motion is visible without art.
- **Viewer:** choose a rig, then a clip in the **Animation** panel. It has play/pause (Space), a frame slider (`,` `.`), onion skin, and a moving ground, whose hatch marks a planted foot should stay locked to.
- **Exit codes:** as for `build`. With `--unity`, an unreachable Unity doesn't fail the command.

## Viewer

```bash
uv run rig-agent view --open        # http://127.0.0.1:8000, lists every rig in out/ (--out DIR, --port N)
```

- **Using it:** pick a rig from the list; it reloads when the rig's files change.
- **Without the server:** open `viewer/index.html` and drop a `skeleton.json` (and its report) onto the page.
- **Colours:** by side, by depth (blue behind, orange in front) or by IK chain. Bones named in the report get a red ring.
- **Controls:** scroll to zoom, drag to pan, click a bone for its details. Keys: `F` fit, `L` labels, `Esc` deselect.
- **URL options:** `&select=hand_R`, `&color=depth|ik`, `&labels=0`.

## Evals and PNG renders

```bash
uv run python -m evals.run --category accessory --k 1           # small live run
uv run python -m evals.run                                      # all 58 prompts x 3 (174 live runs)
uv run python -m evals.run --case std_villager --case adv_horse # specific cases
uv run python -m evals.run --rescore evals/results/<run>        # recompute metrics, no model calls
uv run python -m evals.run --guard-only                         # only the input guard (cheap)
uv run python -m evals.run --guard-only --guard-model gpt-5.4-nano   # compare another guard model
```

| Option | Meaning |
|---|---|
| `--k N` | Runs per prompt (default 3; the consistency metric needs 2 or more). |
| `--case ID`, `--category C`, `--limit N` | Run a subset (ids and categories are in `evals/golden.yaml`). |
| `--render` | Also draw each rig to `skeleton.png`. |
| `--unity` | Also build each rig in Unity (Unity import metric). |
| `--usd-per-mtok-in X --usd-per-mtok-out Y` | Prices per million tokens, for the cost metric. |
| `--guard-only`, `--guard-model M` | Only the input guard; try another guard model. |
| `--yes` | Don't ask before a live (paid) run. |

A live run asks before starting. Results go to `evals/results/<timestamp>/`:
- `report.md`: the metrics against their targets, plus every failed expectation;
- `metrics.json`;
- `records.jsonl`, which `--rescore` reads;
- `rigs/`.

```bash
uv run python -m evals.render_skeleton out/knight               # -> out/knight/skeleton.png
uv run python -m evals.render_skeleton --all out --dest renders  # every rig -> renders/<rig>.png
```

Render options: `--color side|depth|ik`, `--no-labels`, `--size N`. Rendering needs no model and no Unity.

## Checking the code

| Command | What |
|---|---|
| `uv run pytest -q` | 999 offline tests, including the viewer's Node tests |
| `uv run pytest -m live` | 3 tests against the real API (needs a key; costs cents) |
| `uv run pytest -m unity` | 6 tests against a running Unity with the MCP server (they add rigs to the scene) |
| `uv run ruff check .` / `uv run ruff format .` | Lint / format |
| `uv run mypy src evals` | Type check |
| `uv run python scripts/make_viewer_samples.py` | Regenerate the viewer's built-in samples after changing the builder |

## Output files

| File | Made by | Used by |
|---|---|---|
| `spec.json` | `plan` | `build` (you can edit it) |
| `out/<rig>/skeleton.json` | `run`, `build` | viewer, Unity importer |
| `out/<rig>/validation_report.json` | `run`, `build` | viewer, you |
| `out/<rig>/skeleton.png` | `evals.render_skeleton` | you, evals |
| `evals/results/<timestamp>/` | `evals.run` | you (`report.md`), `--rescore` |

## Troubleshooting

| You see | Fix |
|---|---|
| `No API key is set` | Put `OPENAI_API_KEY=sk-...` in `.env` in the repository folder. |
| `Request not accepted (...)` | The guard refused the request. Describe a two-legged character in the front or side view. |
| `command not found: uv` | Install uv (https://docs.astral.sh/uv/). |
| Unity Hub asks to upgrade the project, or picks another version | Install and open with **6000.4.0f1** exactly. |
| No **Android** in *Build Profiles*, or it says "not installed" | Unity Hub → *Installs* → 6000.4.0f1 → *Add modules* → Android Build Support (with OpenJDK and SDK & NDK). |
| No *Window → MCP for Unity* menu | The package didn't download: install `git`, then reopen the project (or *Window → Package Manager → Refresh*). |
| MCP window says "uv not found" | Install uv, or point the window at the `uv` executable (*Choose UV Install Location*). |
| `cannot reach the Unity MCP server` | Unity is closed or the server is stopped: *Window → MCP for Unity → Start Local HTTP Server*. The URL must end in `/mcp`. |
| `UNITY_PROJECT_PATH is not set` or `is not a Unity project` | Set `UNITY_PROJECT_PATH=unity-project` in `.env`, and open **that** folder in Unity (not a copy). |
| Unity delivery `failed` with compile errors | Check the Unity Console, fix them, then run again. |
| Prefab not replaced | Existing prefabs are kept on purpose; add `--overwrite-prefab`. |
| Viewer shows no rig list | You opened the HTML file directly. Use `uv run rig-agent view --open`. |
