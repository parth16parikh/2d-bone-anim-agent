# 2d-bone-anim-agent

An agent that turns a short description of a humanoid character (*"chibi knight with a big sword"*) into a valid, anatomically plausible 2D bone rig for Unity. It writes `skeleton.json` and can build the rig live in an open Unity Editor, with native 2D bones, IK and prefabs. It can then animate the rig from a description too (*"a heavy, tired walk"*): idle, walk and run cycles and a standing backflip, validated and playable in Unity.

Design: [`SYSTEM-DESIGN.md`](SYSTEM-DESIGN.md) (overview), [`LOW-LEVEL-DESIGN.md`](LOW-LEVEL-DESIGN.md) (details) and [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md) (phases and progress notes). Every command is described in [`COMMANDS.md`](COMMANDS.md).

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- An OpenAI API key (an Anthropic key is optional, as a fallback)
- `git`
- For Unity only: Unity Hub and Unity **6000.4.0f1** (see [Unity setup](#unity-setup-one-time))

## Quick start

```bash
uv sync --all-extras                                             # install
cp -n .env.example .env                                          # then set OPENAI_API_KEY=sk-... in .env
uv run rig-agent run "chibi knight with a big sword" --out out/knight
uv run rig-agent view --open                                     # look at the rig in the browser
```

`run` checks the request, plans the rig, builds and validates it, and repairs it up to 3 times if validation fails. The result is `out/knight/skeleton.json` and `validation_report.json`. Add `--view side` for a side-scroller character.

## Unity setup (one time)

1. **Install Unity.** Install [Unity Hub](https://unity.com/download). In Hub, go to *Installs → Install Editor* and pick **6000.4.0f1** (under *Archive* if it isn't listed). Tick the **Android Build Support** module, including **OpenJDK** and **Android SDK & NDK Tools**.
2. **Open the project.** In Hub, choose *Projects → Add → Add project from disk* and select the `unity-project/` folder **inside this repository** (not a copy). The first open imports the packages, including 2D Animation and MCP for Unity, which Unity fetches from GitHub (so `git` must be installed).
3. **Switch the platform to Android.** In Unity, go to *File → Build Profiles*, select **Android** and click **Switch Platform**. The first switch reimports the assets and takes a few minutes.
4. **Point the agent at the project.** Put `UNITY_PROJECT_PATH=unity-project` in `.env`. It's already in `.env.example`, and a relative path is taken from the repository root.
5. **Start the MCP server.** In Unity, go to *Window → MCP for Unity*, choose the **HTTP** transport and click **Start Local HTTP Server** (it runs through `uv`). If the Unity Bridge shows *Stopped*, click **Start Bridge**. The server listens on `http://127.0.0.1:8080/mcp`.
6. **Check the connection.** `uv run rig-agent unity-check` should report *ready*, all tools present, and your project path.

Leave Unity open with the server running whenever you build rigs in it. Repeat step 5 after restarting Unity.

## Build a skeleton in Unity

```bash
uv run rig-agent run "chibi knight with a big sword" --view side --out out/knight --unity   # plan, build, send
uv run rig-agent unity-apply out/knight/skeleton.json                                        # send an existing rig
uv run rig-agent unity-apply-all --prefab-dir Assets/Prefabs/Rigs                             # every rig in out/, saved as prefabs
```

- The rig appears under `RigAgent_Output` in the open scene. Select it to see Unity's 2D bones.
- Arms and legs have IK: **drag the targets** under `IK/` to pose a limb, not the bones.
- *Tools → Rig Agent → Clear Output* removes the rigs; the scene is left unsaved.

The first delivery installs the agent's C# scripts into `Assets/RigAgent/`. If Unity can't be reached, `run` still writes `skeleton.json` and reports `unity: unavailable`.

## Animate a rig

```bash
uv run rig-agent animate out/knight "a heavy, tired walk" --unity    # plan, bake, validate, put on the rig in Unity
uv run rig-agent animate-build --rig out/knight --clip backflip        # default settings, no model
```

- **Clips:** idle (front and side view), walk, run and backflip (side view only). Anything else is refused with a suggestion; a walk, run or backflip on a front-view rig stops with a message.
- **Output:** `out/<rig>/animations/<name>.json`, named after the description, plus a validation report. The validator checks that planted feet don't slide, nothing goes through the floor, joints bend the right way, and cycles loop cleanly.
- **Watching it:** in the browser, `rig-agent view` has an Animation panel (play, scrub, onion skin, moving ground). In Unity, the clip becomes an `.anim` on the rig's Animator, so press Play. Rigs get placeholder capsules on every bone, so motion is visible without art.
- **Held items:** accessories in a hand (a sword, a staff) stay steady; the wrist turns against the arm's swing.

## Evals

```bash
uv run python -m evals.run --category accessory --k 1    # small live run
uv run python -m evals.run                               # full golden set: 58 prompts x 3
uv run python -m evals.run --guard-only                  # only the input guard (cheap)
uv run python -m evals.anim.run --k 1                    # animation evals: 43 motion prompts
```

Results, including `report.md`, go to `evals/results/<timestamp>/`. Why the guard uses `gpt-5.4-mini`: [`GUARD_MODEL_COMPARISON.md`](GUARD_MODEL_COMPARISON.md).

## Project layout

```
src/rig_agent/
  agent/          rig and animation planners: prompts, tools, Pydantic AI agents
  animation/      clip templates (idle, walk, run, backflip), IK, baker, clip validator
  guardrails/     input guards (rig and animation requests) and shared rules
  builder/        RigSpec -> skeleton geometry (front and side layouts)
  validator/      structure and geometry checks
  graph/          LangGraph pipelines (rig and animation) with the repair loop
  unity/          MCP client, delivery (rigs and clips), prefabs, and the C# scripts (unity/csharp/)
  schemas/, vocabulary/, export/, observability/, viewer_server.py
evals/            golden set, eval runner, metrics, PNG renderer
viewer/           browser viewer
unity-project/    the Unity project the rigs are built in
examples/         hand-written RigSpecs for `rig-agent build`
tests/            pytest tests
```

Stack: Pydantic AI (agent), LangGraph (orchestration), Pydantic (schemas), Logfire (optional tracing), and Unity's 2D Animation package with MCP for Unity.

## Development

```bash
uv run pytest -q          # offline tests (no key, no Unity)
uv run ruff check .
uv run mypy src evals
```
