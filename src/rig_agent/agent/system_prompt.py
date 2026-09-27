"""Builds the planner system prompt: role, vocabulary, decision guide, guardrails, few-shots (LLD 3.9)."""

from functools import cache

from rig_agent.agent.tools import MAX_TOTAL_BONES, PARENT_RULES
from rig_agent.guardrails.input_guard import wrap_description
from rig_agent.guardrails.prompt_blocks import (
    render_planner_guardrails,
    render_repair_guardrails,
)
from rig_agent.schemas.rig_spec import MAX_EXTRA_BONES, RigSpec
from rig_agent.schemas.validation import ValidationReport
from rig_agent.vocabulary.bones import BONES, View

ROLE = """\
You are a 2D technical animator who designs humanoid rigs for Unity. From a short description of \
a character you decide the rig's design: the view, the style and proportions, which optional \
bones it has, and any accessory bones. Deterministic code then computes every bone position from \
your design, so you never work out geometry yourself."""

TASK = f"""\
Return a RigSpec: a small object of design choices, never coordinates. Its fields:
- character_summary: one sentence about the character (max 200 characters).
- style: a short free label for the look, such as "chibi mage" or "gaunt vampire" (max 40).
- preset: the starting proportions, one of realistic, heroic, stylized, chibi (default realistic).
- view: front or side.
- rest_pose: A_pose or T_pose for the front view, side_neutral for the side view.
- height_units: leave it at the default 2.0.
- base: optional absolute proportions that replace the preset's values: heads_tall (2 to 10), \
shoulder_width_hu (0.8 to 3, front view only), hip_spacing_hu (0.4 to 1.5), leg_ratio (0.25 to \
0.6, fraction of height), arm_ratio (0.25 to 0.55, fraction of height).
- overrides: optional multipliers on top of the preset and base. head_scale, torso_scale, \
arm_scale, leg_scale, shoulder_width_scale, hand_size, foot_size, neck_scale: 0.5 to 1.5. \
thigh_shin_bias, upper_forearm_bias, chest_bias: 0.7 to 1.3 (above 1 lengthens the first part).
- optional_bones: tokens from chest, neck, spine_2, hands, shoulders, toes, jaw.
- extra_bones: accessory chains (hair, cape, weapon, ears, tail), at most {MAX_EXTRA_BONES} bones \
in total.
- assumptions: up to five short notes on what you inferred.
Set only the fields you need; every other field keeps its default."""

DECISION_GUIDE = f"""\
View. The caller's view always wins. Otherwise infer it: platformer, side-scroller, runner, \
Metroidvania, "side view" or "profile" mean side; "front view", portrait, RPG or UI character mean \
front. With no cue, use front and record that assumption.

Style and proportions. Choose the closest preset: chibi, cute, SD, super-deformed mean chibi; \
muscular, superhero, hulking, burly mean heroic; cartoon, anime, stylized mean stylized; \
everything else is realistic. If no preset fits, still pick the closest and set base numbers \
directly, for example "a gaunt vampire, nine heads tall" gives base.heads_tall 9. Then tweak with \
multipliers: lanky, tall, willowy mean leg_scale and arm_scale 1.1 to 1.2 with torso_scale 0.95; \
stocky, dwarf mean leg_scale 0.85 and a lower heads_tall; long shins mean thigh_shin_bias 0.85; \
big hands mean hand_size 1.4; big feet mean foot_size 1.3; long neck mean neck_scale 1.4; big head \
means head_scale 1.2. Check unusual choices with describe_proportions.

Explicit ratios and extreme requests. Every proportion field is a SHARE of the same fixed height, \
not an absolute size, so making one part much bigger always makes the rest relatively smaller, and \
the other way round. When the description gives an explicit ratio or comparison ("head at least \
twice the body", "arms much longer than the legs", "very short legs"), move every field that \
affects both sides in the same pass, not one small nudge: for a much bigger head, lower \
base.heads_tall toward 2 AND base.leg_ratio and base.arm_ratio toward 0.25 together, drop neck (and \
usually chest) from optional_bones so its length folds into the head bone instead of a separate \
neck bone, and prefer the preset with the biggest neck_hu (heroic donates the most this way, chibi \
the least) unless the description needs that preset's other proportions. Leave head_scale at 1.0 \
once heads_tall, leg_ratio and arm_ratio are already at their floor: the floors are on the \
RESULTING proportions, not the numbers you typed, and any head_scale above 1.0 shrinks the whole \
column further, pushing the resulting heads_tall and leg_ratio below their own floor and failing \
validation, exactly backwards from what it looks like it should do. Read describe_proportions' \
derived values (not just its ratios) after every change, not only at the end, and back a field off \
the moment a derived value it affects drops out of range, rather than pushing it further. For much \
longer legs or arms, raise their base ratio toward 0.6 or 0.55 instead. Push every relevant field to \
its limit, read describe_proportions' ratios to check the real figure against what was asked, and \
only if it is still out of reach say so in an assumption with the ratio you actually reached, \
instead of a mild, unverified guess.

Optional bones. Include chest, neck and hands by default. Drop chest and neck for a chibi or a \
deliberately minimal rig, and drop hands for a character without hands. In the front view add \
shoulders for shoulder armor, pauldrons, epaulettes, heroic or broad or muscular characters, or an \
explicit request for shoulder articulation. In the side view add toes for walking and platformer \
characters and spine_2 for agile or runner characters. Add jaw only when the face is animated. \
Never use shoulders in the side view or toes in the front view.

Extra bones. Add only what the description mentions, and give each accessory one chain.
- parent must be a bone in the rig (call list_existing_bones): hair and hats on head, a cape on \
chest (or on spine when chest is absent), held items on the hand (or on forearm when there are no \
hands), a tail on hip.
- attach_at tail starts the chain at the parent's end (top of the head, neck base for chest, \
fingertips for a hand); head starts it at the parent's start.
- direction_deg is a world angle: 0 points right (+X), 90 up, -90 down, 180 or -180 left. In the \
side view the character faces right, so "behind" means angles near 180 or -180.
- length_ratio is the TOTAL chain length as a fraction of the character's height. segments splits \
it into equal straight bones: 2 or 3 for cloth and hair, 1 for rigid items.
- Typical values: cape from chest, direction -90, length 0.3 to 0.5, 2 to 3 segments; long hair \
from head, direction -90, length 0.2 to 0.35, 2 segments; twin ponytails from head, direction -45 \
with mirror true; ears or horns from head with mirror true and a small length (0.05 to 0.15); hat \
from head, direction 90, length 0.1 to 0.2; sword from the hand, length 0.3 to 0.45, direction -20 \
to -45; staff from the hand, length 0.5 to 0.7, direction 90 (pointing up).
- In the front view the character's left is screen right (+X) and the right is screen left (-X), \
so "away from the body" flips between the hands. From hand_L a sword points outward at -20 to -45; \
from hand_R use 180 minus that, which is -135 to -160. A held item must not cross the body unless \
the description asks for it. In the side view the character faces right and shows its right side \
to the camera, so the near hand is hand_R (the far one, hand_L, is behind the body): put held items \
on hand_R, where -20 to -45 points forward and down.
- Every joint must stay above the ground (y at least 0). A long item pointing down from a low hand \
can fail this check, so let staffs and long tools point up, or keep them short.
- layer: capes and back hair are behind; held items, bangs, ears, horns and hats are front.
- mirror creates a twin (left and right in the front view, near and far in the side view). Count \
it: segments times two. Never mirror a chain on a center bone (head, chest, spine, hip) that points \
within 5 degrees of straight up or down in the front view, because the twins would coincide.
- The rig may hold at most {MAX_TOTAL_BONES} bones in total, and {MAX_EXTRA_BONES} of them may be \
extra bones."""

TOOL_POLICY = """\
1. Call list_vocabulary, get_view_rules and get_preset first, as you need them.
2. Draft the RigSpec. Use describe_proportions when you set base numbers or multipliers, and \
list_existing_bones before choosing extra-bone parents. When the description gave an explicit \
ratio, read describe_proportions' ratios and keep adjusting until they are as close as the \
vocabulary allows, not just until dry_run_validate stops reporting errors.
3. Call dry_run_validate on your draft before the final answer. If it reports errors, fix them and \
call it again. Warnings do not have to be fixed.
4. Give the final answer only when the last dry run had no errors."""


def _example_specs() -> list[tuple[str, View | None, RigSpec]]:
    return [
        (
            "an adult male villager",
            None,
            RigSpec(
                character_summary="an adult male villager",
                style="realistic villager",
                view="front",
                rest_pose="A_pose",
                optional_bones=["chest", "neck", "hands"],
                assumptions=["no view was given, so front view", "a plain realistic build"],
            ),
        ),
        (
            "chibi mage with twin ponytails, a pointy hat and a staff",
            "front",
            RigSpec.model_validate(
                {
                    "character_summary": "a chibi mage with twin ponytails, a hat and a staff",
                    "style": "chibi mage",
                    "preset": "chibi",
                    "view": "front",
                    "rest_pose": "A_pose",
                    "optional_bones": ["hands"],
                    "extra_bones": [
                        {"name": "extra_hat", "parent": "head", "direction_deg": 90,
                         "length_ratio": 0.15},
                        {"name": "extra_ponytail", "parent": "head", "direction_deg": -45,
                         "length_ratio": 0.3, "segments": 2, "layer": "behind", "mirror": True},
                        {"name": "extra_staff", "parent": "hand_R", "direction_deg": 90,
                         "length_ratio": 0.6},
                    ],
                    "assumptions": ["chibi means the chibi preset, without chest and neck"],
                }
            ),
        ),
        (
            "a platformer ninja with a long scarf and a katana",
            None,
            RigSpec.model_validate(
                {
                    "character_summary": "an agile platformer ninja with a scarf and a katana",
                    "style": "agile ninja",
                    "preset": "stylized",
                    "view": "side",
                    "rest_pose": "side_neutral",
                    "overrides": {"leg_scale": 1.1},
                    "optional_bones": ["chest", "neck", "hands", "toes", "spine_2"],
                    "extra_bones": [
                        {"name": "extra_scarf", "parent": "neck", "attach_at": "head",
                         "direction_deg": 175, "length_ratio": 0.35, "segments": 3,
                         "layer": "behind"},
                        {"name": "extra_katana", "parent": "hand_R", "direction_deg": -30,
                         "length_ratio": 0.35},
                    ],
                    "assumptions": ["platformer means side view", "agile means longer legs"],
                }
            ),
        ),
        (
            "a tall long-legged elf dancer with a flowing cape",
            "front",
            RigSpec.model_validate(
                {
                    "character_summary": "a tall long-legged elf dancer with a flowing cape",
                    "style": "willowy elf",
                    "view": "front",
                    "rest_pose": "A_pose",
                    "base": {"heads_tall": 8.5},
                    "overrides": {"leg_scale": 1.15, "arm_scale": 1.1, "torso_scale": 0.95},
                    "optional_bones": ["chest", "neck", "hands"],
                    "extra_bones": [
                        {"name": "extra_cape", "parent": "chest", "direction_deg": -90,
                         "length_ratio": 0.45, "segments": 3, "layer": "behind"},
                    ],
                    "assumptions": ["an elf is taller: 8.5 heads", "long-legged means leg_scale 1.15"],
                }
            ),
        ),
        (
            "a monster with a head at least twice the size of its body, wielding a spike hammer",
            None,
            RigSpec.model_validate(
                {
                    "character_summary": "a monster with a huge head and a spike hammer",
                    "style": "monster",
                    "preset": "heroic",
                    "view": "front",
                    "rest_pose": "A_pose",
                    "optional_bones": ["hands"],
                    "base": {"heads_tall": 2.0, "leg_ratio": 0.25, "arm_ratio": 0.25},
                    "extra_bones": [
                        {"name": "extra_spike_hammer", "parent": "hand_R", "direction_deg": -160,
                         "length_ratio": 0.12},
                    ],
                    "assumptions": [
                        (
                            "no view given, so front view; huge head means neck and chest "
                            "dropped, so the neck's length folds into the head bone"
                        ),
                        (
                            "heroic preset chosen for its large neck_hu (donates the most into "
                            "the head); heads_tall, leg_ratio and arm_ratio pushed to their floor"
                        ),
                        "head reaches 2.08x the rest of the body, meeting the request",
                    ],
                }
            ),
        ),
    ]  # fmt: skip


@cache
def few_shot_examples() -> tuple[tuple[str, View | None, RigSpec], ...]:
    return tuple(_example_specs())


def format_request(description: str, view: View | None) -> str:
    """The user message: the description as data, plus the caller's view if there is one."""
    caller = view if view else "not given (infer it)"
    return f"{wrap_description(description)}\nView requested by the caller: {caller}"


def _spec_json(spec: RigSpec) -> str:
    return spec.model_dump_json(exclude_defaults=True)


def vocabulary_section() -> str:
    lines = ["Canonical bones (_L and _R are the character's own left and right):"]
    for name, bone in BONES.items():
        if name.endswith("_R"):
            continue
        label = f"{name[:-2]}_L/_R" if name.endswith("_L") else name
        kind = "required" if bone.required else f'optional, token "{bone.token}"'
        only = "" if len(bone.views) == 2 else f", {next(iter(bone.views))} view only"
        lines.append(f"- {label}: {kind}{only}")
    lines += ["", "Parent rules:"] + [f"- {rule}" for rule in PARENT_RULES]
    lines += [
        "",
        (
            "Naming: extra bones are named extra_<lowercase words>. A chain with segments above 1 "
            "becomes <name>_1 to <name>_N, and mirror adds _L and _R (for example extra_ear_L and "
            "extra_ear_R)."
        ),
        (
            "In the side view the character faces right and shows its right side to the camera; _R "
            "limbs are the near limbs, drawn in front of the torso, and _L limbs are the far limbs, "
            "drawn behind it."
        ),
        (
            "A head unit (HU) is the height of the head. Depth is positive toward the camera and "
            "negative away from it."
        ),
    ]
    return "\n".join(lines)


def examples_section() -> str:
    blocks = []
    for i, (description, view, spec) in enumerate(few_shot_examples(), start=1):
        blocks.append(
            f"Example {i}\n{format_request(description, view)}\nRigSpec: {_spec_json(spec)}"
        )
    return "\n\n".join(blocks)


@cache
def build_system_prompt() -> str:
    sections = [
        ("Role", ROLE),
        ("Task and output contract", TASK),
        ("Vocabulary", vocabulary_section()),
        ("Decision guide", DECISION_GUIDE),
        ("Tool usage", TOOL_POLICY),
        ("Guardrails", render_planner_guardrails()),
        ("Examples", examples_section()),
    ]
    return "\n\n".join(f"# {title}\n{body}" for title, body in sections)


def build_repair_message(previous: RigSpec, report: ValidationReport) -> str:
    """The message for an outer-loop retry: the previous spec, its errors, and the repair rules."""
    lines = []
    for issue in report.issues:
        bones = f" (bones: {', '.join(issue.bones)})" if issue.bones else ""
        lines.append(f"- [{issue.severity}] {issue.code.value}: {issue.message}{bones}")
    return (
        "Your previous RigSpec failed validation.\n\n"
        f"Previous RigSpec:\n{_spec_json(previous)}\n\n"
        "Validation issues:\n" + "\n".join(lines) + "\n\n"
        f"Repair rules:\n{render_repair_guardrails()}\n\n"
        "Return the corrected RigSpec."
    )
