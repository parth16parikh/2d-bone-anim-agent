"""The animation planner's system prompt, request and repair messages (Goal 2, A3).

The settings table is generated from AnimationSpec's own field bounds, so the prompt can never
advertise a range the schema would reject."""

from annotated_types import Ge, Le

from rig_agent.guardrails.anim_guard import wrap_motion
from rig_agent.guardrails.prompt_blocks import render_anim_planner_guardrails
from rig_agent.schemas.animation import CLIP_TYPES, CLIP_VIEWS, AnimationSpec
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.validation import ValidationReport

SETTING_MEANINGS = {
    "speed": "cycles per second relative to the clip's default: 0.7 is slow and heavy, 1.3 is brisk",
    "stride": "step length (walk, run): 0.7 is short and careful, 1.3 is long and striding",
    "bounce": "how much the hip rises and falls: 0.4 is heavy or smooth, 1.5 is springy",
    "arm_swing": "how far the arms swing: 0.3 is stiff or carrying something, 1.5 is exaggerated",
    "knee_lift": "how high the swinging foot rises (walk, run): 1.3 is high-stepping or tiptoe",
    "lean_deg": "torso lean in degrees, positive = forward (side view only): 8 tired, 12 sprinting",
    "fps": "frames per second of the baked clip: 24 by default; 12 for a choppy, retro look",
}

ROLE = """\
You design 2D game animation clips for a humanoid rig that already exists. You read a short
description of how the character should move and return one AnimationSpec: which clip (idle, walk,
run or backflip) and how its settings should change to match the mood and style. Code bakes every frame and
validates it; you never write keyframes."""

DECISION_GUIDE = """\
How to choose:
- The clip is whatever the description asks for: standing, waiting, breathing -> idle; walking,
  strolling, marching, sneaking, limping along -> walk; jogging, running, sprinting -> run; a
  backflip or back somersault -> backflip. A bare "walk" or "run" means the neutral clip (all
  settings 1.0).
- A backflip plays once, in place. Its settings mean: speed = how fast, bounce = how high the jump
  (the body always clears the floor; bounce adds height), knee_lift = how tight the tuck,
  arm_swing = how hard the arms throw. stride and lean_deg do nothing for it.
- Then move only the settings the description implies, by how much it implies:
  heavy, tired, sad, old -> speed 0.6-0.8, bounce 0.3-0.6, arm_swing 0.4-0.7, lean 6-12;
  sneaky, careful -> speed 0.5-0.7, stride 0.5-0.7, knee_lift 1.2-1.5, bounce 0.2-0.4, arm_swing 0.3;
  energetic, happy, childlike -> speed 1.2-1.5, bounce 1.4-1.8, arm_swing 1.3-1.6;
  confident, proud, marching -> stride 1.1-1.3, arm_swing 1.3-1.6, lean -3 to 0, bounce 0.8;
  sprinting -> run with speed 1.3-1.6, stride 1.3-1.5, knee_lift 1.3, lean 12-18.
- speed is the step rate and stride the step length; they are separate. Quick, hurried or brisk
  steps raise speed (1.2-1.5) even when the steps are short; slow steps lower it even when long.
- style is a short label of the mood (e.g. "heavy, tired"). Record any interpretation you made in
  assumptions."""

TOOL_POLICY = """\
Tools: call list_clip_types if you are unsure which clips this rig allows. Call preview_clip with
your draft spec and check its numbers against the description before you answer; adjust and preview
again if they do not match."""


def _settings_table() -> str:
    rows = []
    for name, meaning in SETTING_MEANINGS.items():
        field = AnimationSpec.model_fields[name]
        low = next(m.ge for m in field.metadata if isinstance(m, Ge))
        high = next(m.le for m in field.metadata if isinstance(m, Le))
        rows.append(f"- {name} ({low} to {high}, default {field.default}): {meaning}")
    return "Settings:\n" + "\n".join(rows)


def _clips_table() -> str:
    return "Clips: " + "; ".join(f"{c} ({', '.join(CLIP_VIEWS[c])} view)" for c in CLIP_TYPES) + "."


EXAMPLES: list[tuple[str, AnimationSpec]] = [
    (
        "a heavy, tired walk",
        AnimationSpec(
            clip="walk",
            style="heavy, tired",
            speed=0.7,
            stride=0.85,
            bounce=0.5,
            arm_swing=0.6,
            knee_lift=0.8,
            lean_deg=8.0,
        ),
    ),
    (
        "sneaking on tiptoes",
        AnimationSpec(
            clip="walk",
            style="sneaky",
            speed=0.6,
            stride=0.6,
            bounce=0.3,
            arm_swing=0.3,
            knee_lift=1.4,
            lean_deg=12.0,
        ),
    ),
    (
        "an all-out sprint",
        AnimationSpec(
            clip="run",
            style="sprint",
            speed=1.4,
            stride=1.4,
            bounce=1.2,
            arm_swing=1.5,
            knee_lift=1.3,
            lean_deg=12.0,
        ),
    ),
    (
        "standing guard, calm and still",
        AnimationSpec(clip="idle", style="calm guard", speed=0.8, bounce=0.6, arm_swing=0.4),
    ),
]


def _examples_section() -> str:
    blocks = [
        f'Request: "{description}"\nAnimationSpec: {spec.model_dump_json(exclude_defaults=True)}'
        for description, spec in EXAMPLES
    ]
    return "Examples (settings not shown are left at their defaults):\n\n" + "\n\n".join(blocks)


def build_anim_system_prompt() -> str:
    return "\n\n".join(
        [
            ROLE,
            _clips_table(),
            _settings_table(),
            DECISION_GUIDE,
            "Rules:\n" + render_anim_planner_guardrails(),
            TOOL_POLICY,
            _examples_section(),
        ]
    )


def format_anim_request(description: str, skeleton: Skeleton) -> str:
    # no list of the clips this rig "allows": that nudged the planner into swapping in an idle;
    # the pipeline checks the view after planning and explains it to the user
    return (
        f"The rig: '{skeleton.rig_name}', {skeleton.view} view, style '{skeleton.style}', "
        f"height {skeleton.height:g} units.\n\n"
        f"{wrap_motion(description)}"
    )


def build_anim_repair_message(previous: AnimationSpec, report: ValidationReport) -> str:
    issues = "\n".join(f"- {i.code.value}: {i.message}" for i in report.issues) or "- (none)"
    return (
        "Your previous AnimationSpec produced a clip that failed validation:\n"
        f"{previous.model_dump_json()}\n\nIssues:\n{issues}\n\n"
        "Return a corrected AnimationSpec for the same request. Keep what already matched the "
        "description and change only what the issues point to."
    )
