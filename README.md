# 2d-bone-anim-agent

An agent that turns a short text description of a humanoid character (e.g. *"chibi knight with a big sword"*) into a valid, anatomically plausible 2D bone hierarchy for Unity — exported as `skeleton.json` and, optionally, built live in an open Unity Editor via Unity MCP.

Design docs: [`HLD_2D_Humanoid_Rig_Agent.md`](../../HLD_2D_Humanoid_Rig_Agent.md) (architecture overview) and [`LLD_2D_Humanoid_Rig_Agent.md`](../../LLD_2D_Humanoid_Rig_Agent.md) (schemas, prompts, evals).

## Stack

- **Agent**: [Pydantic AI](https://ai.pydantic.dev/) (ReAct planner, typed `RigSpec` output, Anthropic + OpenAI)
- **Orchestration**: [LangGraph](https://langchain-ai.github.io/langgraph/) (guard → plan → build → validate → repair → export → Unity)
- **Validation**: Pydantic v2
- **Geometry**: plain Python `math` (NumPy is installed but not needed so far)
- **Observability**: Logfire
- **Unity**: 2D Animation package, C# Editor importer, Unity MCP

## Project layout

```
src/rig_agent/
  schemas/       RigSpec, Skeleton, GuardResult, ValidationReport, RigState
  vocabulary/     canonical bone table, style presets, view rules
  guardrails/     shared rules.yaml, input classifier, prompt guardrail blocks
  agent/          planner system prompt, tools, Pydantic AI agent
  builder/        RigSpec -> Skeleton geometry (front/side layout)
  validator/      structure + geometry checks -> ValidationReport
  export/         skeleton.json + validation_report.json writer
  graph/          LangGraph nodes and StateGraph wiring
  unity/          MCP client, delivery, batch import, prefabs, and the C# scripts (unity/csharp/)
  viewer_server.py  local server for the viewer (`rig-agent view`)
  observability/  Logfire tracing setup
evals/            golden.yaml, offline skeleton renderer, Q1-Q13 metrics
examples/         hand-written RigSpec files for `rig-agent build`
viewer/           browser viewer for skeleton.json (index.html, viewer.js, samples.js)
unity-project/    the Unity project the rigs are built in (Assets/, Packages/, ProjectSettings/)
scripts/          make_viewer_samples.py
tests/            pytest unit tests
```

## Setup

```bash
uv sync --all-extras   # installs core + eval + dev dependency groups
# put your key in .env (git-ignored): OPENAI_API_KEY=sk-...   (see .env.example)
uv run pytest
```

## Usage

> Every command, when to run it and what it produces: see [`COMMANDS.md`](COMMANDS.md).

Status: the deterministic core, the planner agent, the LangGraph repair loop, the browser viewer and the Unity delivery are done. The evals (Phase H) are not built yet.

**Everything in one command** (needs an API key in `.env`):

```bash
uv run rig-agent run "chibi knight with a big sword" --out out/knight
uv run rig-agent run "ninja for my platformer" --view side --out out/ninja
```

It checks the request, plans a `RigSpec`, builds and validates the rig, and if validation fails it sends the errors back to the planner and tries again (up to 3 attempts, within a budget of 12 model calls, 15 tool calls, 60 seconds and 150,000 tokens). If the attempts run out, the best one is exported with a failing report. Progress goes to stderr. Exit code: 0 success, 1 rejected request or best-effort rig, 2 error (missing key, model failure).

If you set both `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, the second provider is used automatically when the first returns an API error. Set `PRIMARY_PROVIDER=anthropic` to switch the order.

The two commands below run the same steps separately.

**1. Plan a spec from a description** (needs `OPENAI_API_KEY` in `.env`; uses `gpt-5.4-nano` as the input guard and `gpt-5.4-mini` as the planner):

```bash
uv run rig-agent plan "chibi knight with a big sword" --out spec.json
uv run rig-agent plan "a ninja for my platformer" --view side --out ninja.json
```

Progress goes to stderr: the input guard, then the planner with each tool call and its result (with elapsed seconds), then the token counts and the dry-run result. The RigSpec itself goes to `--out`, or to stdout if you omit it. Exit code: 0 when the spec passes the dry run, 1 when the request is rejected or the dry run fails, 2 on a missing key or a failed model run.

**2. Build the rig from a spec** (no LLM; works with a planned or hand-written spec):

```bash
uv run rig-agent build --spec spec.json --out out/knight
uv run rig-agent build --spec examples/knight_side.json --out out/knight
```

This writes `out/knight/skeleton.json` and `out/knight/validation_report.json`. Running either `run` or `build` again with the same `--out` folder replaces what's there (there is no separate "override" command; a note is printed when it does). Exit code: 0 when the rig passes validation, 1 when it does not (files are still written), 2 when the spec cannot be read or built.

**3. Remove rigs you don't want:**

```bash
uv run rig-agent delete out/knight out/elf   # one or more named rigs
uv run rig-agent delete --all --out out      # every rig under out/
```

Removes only `skeleton.json` and `validation_report.json` (and the folder itself, if that leaves it empty); anything else you put in that folder is left alone. Never touches Unity.

**Live tests** call the real API and are opt-in: `uv run pytest -m live`.

## Unity delivery

`rig-agent` can build the rig in your open Unity Editor and verify it. It talks to the [MCP for Unity](https://github.com/CoplayDev/unity-mcp) server over HTTP, so Unity must be open with that server running. Only a few read-only calls and three menu items (import, import all, save prefabs) are allowed (see `rig_agent/unity/mcp_client.py`), so it cannot delete scripts or assets.

**One-time setup**

1. In Unity, open **Window > MCP for Unity** and start the server (HTTP). The default endpoint is `http://127.0.0.1:8080/mcp`.
2. The Unity project lives in `unity-project/` inside this repository. Open **that** folder in Unity Hub (*Add > Add project from disk*), not a copy elsewhere, and set `UNITY_PROJECT_PATH=unity-project` in `.env` (already in `.env.example`). A relative path is taken from the repository root; an absolute path also works. Optionally set `UNITY_MCP_URL`.
   If you move the project, close Unity first, move the folder, update `UNITY_PROJECT_PATH`, reopen it from the new place and restart the MCP server: a running editor keeps working on the old path.
3. The project needs the **2D Animation** package (`com.unity.2d.animation`, already in this project); `unity-check` and `unity-install` say so if it is missing.
4. `uv run rig-agent unity-check` should show *ready*, *all 5 tools present*, and the project path.

**Use it**

```bash
uv run rig-agent run "chibi knight with a big sword" --view side --unity   # whole pipeline, then Unity
uv run rig-agent unity-apply out/knight/skeleton.json                      # send an existing rig
uv run rig-agent unity-apply-all --out out                                 # send every rig in out/
uv run rig-agent unity-apply-all --out out --prefab-dir Assets/Prefabs/Rigs  # ...and save prefabs
```

The first delivery installs six C# scripts into `Assets/RigAgent/` (or run `rig-agent unity-install`) and waits for Unity to compile them. Each delivery writes `Assets/Rigs/skeleton.json`, runs **Tools > Rig Agent > Import Latest Skeleton**, and then compares the Transforms Unity actually created (read back into `Assets/Rigs/last_import.json`) with the JSON: bone count, names, parents, depth, layer and positions within 1e-3.

The rig appears under a `RigAgent_Output` object in the open scene. Its bones are drawn by **Unity's own 2D Animation package** (white bones with pivots in the Scene view, while the rig is selected). For that, each rig gets a fully transparent **placeholder sprite** that carries the bones, a `SpriteRenderer` and `SpriteSkin` on the rig root, and a **skeleton asset** (`SkeletonAsset`, the type the PSD and Aseprite importers take as *Main Skeleton*). A `BoneGizmo` component on each bone only holds metadata (depth, layer, IK chain, mirror link, extra flag); it draws nothing. **Arms and legs get 2D IK:** a Limb solver and a target per chain (`IK/<chain>/target_<hand or foot>`), so **drag the target, not the bone**, and the limb bends and stays connected (dragging a bone directly only moves that bone, which is how Unity bones behave, IK or not). A weapon or a toe past the hand/foot (`extra_sword`, `toe_L`/`toe_R`) is a rigid child, not part of the solved chain — it turns with the hand or foot through ordinary parenting. The elbow or knee bends the way `ik_chains[].bend_side` in `skeleton.json` says. Turn it off with `--no-ik`. Side-view rigs also get a `FacingController` (`Face(false)` flips it to face left). The scene is left unsaved. **Tools > Rig Agent > Clear Output** removes the rigs. If Unity is not reachable the run still succeeds and reports `unity: unavailable`, because `skeleton.json` is already delivered.

**Everything in `out/` at once.** `unity-apply-all` finds every `out/<folder>/skeleton.json`, clears the rigs from the previous import under `RigAgent_Output`, and builds them in a row, side by side, each named after its folder (so two runs of the same prompt do not replace each other). Each rig is verified like a single one. A `skeleton.json` that cannot be read is skipped and reported.

**Where the assets go.** Every rig's placeholder sprite and skeleton asset are written into a folder of their own and rewritten on each import (treat them as generated): `Assets/Rigs/Generated/<rig>/` normally, or `<prefab folder>/<rig>/` when the rig gets a prefab, so the folder then holds `<rig>.prefab`, `<rig>_placeholder.png` and `<rig>_skeleton.asset`. (The skeleton is a `.asset` file: Unity does not let a script create a real `.skeleton` file, and the importers accept the asset either way.)

**Prefabs.** With `--prefab-dir Assets/Some/Folder` (or `UNITY_PREFAB_DIR` in `.env`), every rig that was **verified in Unity and passed validation** is saved as `<folder>/<rig name>/<rig name>.prefab`, with its root at the origin. This works with `unity-apply`, `unity-apply-all` and `run --unity`. The folder must be inside `Assets/`. An existing prefab is **kept, not overwritten**, because you may have added sprites or components to it; pass `--overwrite-prefab` to replace it. Rigs that failed validation (or have no report) get no prefab. `--prefab-dir ""` switches it off when the environment variable is set.

Opt-in tests against a real Unity: `uv run pytest -m unity`.

## Viewer (see the rig)

`viewer/` is a small browser app that draws a `skeleton.json` so you can check a rig by eye. It has no dependencies and no build step.

**Quick look:** open `viewer/index.html` in a browser, then drop `skeleton.json` (and `validation_report.json`) on the page, or use *Choose files*. The *Load a sample* menu shows three built-in rigs.

**Pick a rig from `out/` (recommended):** run the viewer's own server and open it. The sidebar has a *Rigs in out/* list of every rig found (view, bone count and whether it passed validation); choose one and the picture, report and hierarchy update. The list refreshes by itself, and the chosen rig reloads whenever its file changes, so each `rig-agent run` or `build` shows up on its own.

```bash
uv run rig-agent view --open       # http://127.0.0.1:8000/  (--out DIR, --port N)
```

The server listens on `127.0.0.1` only and serves just `viewer/` and `out/`, nothing else in the project (not `.env`).

**Without the server:** `python3 -m http.server 8000` in the project root also works with `http://localhost:8000/viewer/index.html?src=/out/knight/skeleton.json`, but has no rig list and serves the whole folder, including `.env`, so prefer `rig-agent view`.

What it shows: every bone as a bone shape from pivot to tip, in the same draw order as the Unity importer (depth, shifted by layer). Colour by left/right/center/extra, by depth (blue behind, orange in front) or by IK chain. Dashed lines show where a bone starts away from its parent's tail (limb roots, the hip, the jaw). Optional layers: labels, pivots, grid, the validator's bounding box, extras, and *Face left* (the Unity flip). Click a bone (or a row in the hierarchy) for its head, tail, length, angle, depth, layer, IK chain and local transform. Bones named in the validation report get a red ring, and clicking an issue selects them. *Save PNG* exports the current view.

Mouse: scroll to zoom, drag to pan, click to select. Keys: `F` fit, `L` labels, `Esc` deselect.

URL options: `?sample=knight_side`, `?src=/out/knight/skeleton.json` (with `rig-agent view`), `&select=hand_R`, `&color=depth` (or `ik`), and `&labels=0` (also `joints`, `links`, `grid`, `bounds`, `depth`, `extras`, `flip`, with `0` or `1`).

The samples are generated from `examples/*.json` by `uv run python scripts/make_viewer_samples.py`; a test fails if they go stale. The viewer's logic has its own tests: `node --test viewer/viewer.test.js` (also run by `pytest`).

Checks used during development: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy src`.
