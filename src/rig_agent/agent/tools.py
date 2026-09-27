"""Pure, deterministic planner tools: vocabulary, presets, view rules, dry runs (LLD 3.6).

None of these has side effects, and none can reach Unity.
"""

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from rig_agent.builder.errors import BuildError
from rig_agent.builder.proportions import resolve_proportions
from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.schemas.rig_spec import MAX_EXTRA_BONES, RigSpec
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport
from rig_agent.validator.report import validate
from rig_agent.vocabulary.bones import (
    BONES,
    OPTIONAL_TOKENS,
    REQUIRED_BONES,
    View,
    expand_optional,
    present_bones,
    token_views,
)
from rig_agent.vocabulary.presets import BANDS, PRESETS, Preset

MAX_TOTAL_BONES = 40

PARENT_RULES = [
    (
        "Torso column, bottom to top: hip, spine, spine_2, chest, neck, head. A torso bone hangs "
        "from the nearest present bone below it."
    ),
    "The torso top is the topmost present bone among spine, spine_2 and chest.",
    (
        "upper_arm_* and shoulder_* hang from the torso top. upper_arm_* hangs from shoulder_* "
        "instead when shoulders are present."
    ),
    "head hangs from neck when present, otherwise from the torso top.",
    (
        "forearm from upper_arm, hand from forearm, thigh from hip, shin from thigh, foot from "
        "shin, toe from foot, jaw from head (same side for sided bones)."
    ),
    (
        "If chest is absent its share of the torso goes to spine; if neck is absent its length "
        "goes to head; if hands are absent the hand's share of the arm goes to the forearm."
    ),
]

_VIEW_RULES: dict[str, dict[str, Any]] = {
    "front": {
        "rest_poses": ["A_pose", "T_pose"],
        "default_rest_pose": "A_pose",
        "facing": "toward the camera; the character's left is screen right (+X)",
        "joint_layout": "_L/_R limbs spread left and right of the spine",
        "depth": "torso at depth 0; limbs slightly in front (positive depth)",
        "symmetry": "each _L/_R pair mirrors across the Y axis",
        "shoulder_width_applies": True,
    },
    "side": {
        "rest_poses": ["side_neutral"],
        "default_rest_pose": "side_neutral",
        "facing": "right (+X); Unity flips the rig to face left",
        "joint_layout": "_L/_R limbs stacked on nearly the same X; _R is the near side (a right-facing "
        "character shows its right side to the camera), _L the far side, offset 1.5% of "
        "the height toward -X",
        "depth": "far limbs behind the torso (negative depth); near limbs in front (positive)",
        "symmetry": "each pair has equal lengths and near-identical positions",
        "shoulder_width_applies": False,
    },
}


def list_vocabulary() -> dict[str, Any]:
    """The bone vocabulary: every canonical bone, which are required, the optional tokens and
    which bones they add, parent rules, naming rules and limits. Call this first."""
    return {
        "bones": [
            {
                "name": b.name,
                "required": b.required,
                "optional_token": b.token,
                "views": sorted(b.views),
            }
            for b in BONES.values()
        ],
        "required_bones": [name for name in BONES if name in REQUIRED_BONES],
        "optional_tokens": {
            token: {"adds": expand_optional([token]), "views": sorted(token_views(token))}
            for token in OPTIONAL_TOKENS
        },
        "parent_rules": PARENT_RULES,
        "naming": {
            "sides": "_L and _R are the character's own left and right. In side view _L is the "
            "far limb and _R the near limb.",
            "extra_bones": "extra bones must be named extra_<lowercase letters, digits, underscores>",
            "chains": "a chain with segments>1 becomes <name>_1.._N; a mirrored extra becomes "
            "<name>_L and <name>_R (or <name>_<i>_L, <name>_<i>_R)",
        },
        "limits": {
            "max_total_bones": MAX_TOTAL_BONES,
            "max_extra_bones": MAX_EXTRA_BONES,
            "extra_segments": [1, 4],
            "extra_length_ratio": [0.01, 0.6],
        },
        "presets": list(PRESETS),
    }


def get_preset(name: Preset) -> dict[str, Any]:
    """The proportions of a style preset: its five base numbers plus the default splits inside
    each limb and the torso. A preset is only a starting point."""
    p = PRESETS[name]
    data = asdict(p)
    return {
        "name": data.pop("name"),
        "base": {
            "heads_tall": data.pop("heads_tall"),
            "shoulder_width_hu": data.pop("shoulder_width_hu"),
            "hip_spacing_hu": data.pop("hip_spacing_hu"),
            "leg_ratio": data.pop("leg_ratio"),
            "arm_ratio": data.pop("arm_ratio"),
        },
        "ankle_ratio": data.pop("ankle_ratio"),
        "thigh_share": data.pop("thigh_share"),
        "arm_split_upper_forearm_hand": list(data.pop("arm_split")),
        "foot_length_hu": data.pop("foot_length_hu"),
        "neck_hu": data.pop("neck_hu"),
        "torso_split_hip_spine_chest": list(data.pop("torso_split")),
        "units": "HU is one head height; ratios are fractions of the character's height",
    }


def get_view_rules(view: View) -> dict[str, Any]:
    """The rules of a view: allowed rest poses, which optional bones and overrides apply,
    depth order and symmetry."""
    rules = dict(_VIEW_RULES[view])
    rules["view"] = view
    rules["optional_bones_available"] = [t for t in OPTIONAL_TOKENS if view in token_views(t)]
    rules["optional_bones_not_available"] = [
        t for t in OPTIONAL_TOKENS if view not in token_views(t)
    ]
    return rules


def describe_proportions(rig_spec: RigSpec) -> dict[str, Any]:
    """The resulting proportions of a draft spec, with a warning for each value outside its
    plausible range, and ratios between the main parts. Use it to sanity-check your reading of
    the description and to check an explicit size ratio the description asked for (LLD 2.4.4).

    heads_tall can never go below 2 (its plausible range's floor), so the head SHAPE on its own
    can never be more than half the character's total height. The head bone can still end up
    bigger than that: when neck is left out of optional_bones its length folds into the head bone
    instead, and how much it donates depends on the preset (heroic's neck_hu is the biggest, so
    it donates the most; chibi's is the smallest). Pushing heads_tall, base.leg_ratio and
    base.arm_ratio all the way to their floor together, dropping neck, and picking a preset with a
    big neck_hu for that donation reaches the biggest head a valid rig can have. Leave head_scale
    at 1.0 once those three are already at their floor: the floors below apply to these DERIVED
    values, not the numbers you typed, and head_scale above 1.0 shrinks the whole column further,
    pushing heads_tall and leg_ratio below their own floor instead of helping. Check the derived
    values below (not just the ratios) after every change you make, and back a field off as soon
    as one goes out of range, rather than pushing it further."""
    try:
        props = resolve_proportions(rig_spec)
    except BuildError as error:
        return {"error": str(error)}
    derived = {}
    warnings = []
    for name, value in props.derived_values(rig_spec.view).items():
        low, high = BANDS[name]
        in_band = low <= value <= high
        derived[name] = {"value": round(value, 3), "plausible": [low, high], "in_range": in_band}
        if not in_band:
            warnings.append(f"{name} is {value:.3f}, outside the plausible range {low}-{high}")
    head, torso, leg, arm = props.head, props.torso_length, props.leg_length, props.arm_length
    return {
        "height": props.height,
        "lengths": {
            "head": round(props.head_only, 4),
            "neck": round(props.neck, 4),
            "torso": round(torso, 4),
            "leg_hip_to_ground": round(leg, 4),
            "arm_shoulder_to_fingertips": round(arm, 4),
            "shoulder_width": round(props.shoulder_width, 4),
        },
        "ratios": {
            # "head" here is the built head bone: it includes the neck's length when neck is
            # absent from optional_bones (LLD 2.3), so dropping neck grows this figure further.
            "head_to_rest_of_body": round(head / (props.height - head), 3),
            "leg_to_arm": round(leg / arm, 3) if arm else None,
            "leg_to_torso": round(leg / torso, 3) if torso else None,
            "arm_to_torso": round(arm / torso, 3) if torso else None,
        },
        "derived": derived,
        "warnings": warnings,
    }


def dry_run_validate(rig_spec: RigSpec) -> ValidationReport:
    """Build and validate a draft spec exactly as the pipeline will, and return the report.
    Call it before giving your final answer and fix every error."""
    try:
        skeleton = build_skeleton(rig_spec)
    except BuildError as error:
        issue = ValidationIssue(code=IssueCode.UNBUILDABLE, message=str(error))
        return ValidationReport(issues=[issue])
    return validate(skeleton, rig_spec)


def list_existing_bones(rig_spec: RigSpec) -> dict[str, Any]:
    """The bones a draft spec would produce: canonical bones present, and the extra bones
    (with chain segments and mirrored twins resolved). Use it to pick valid extra-bone parents."""
    canonical = [name for name in BONES if name in present_bones(rig_spec.optional_bones)]
    try:
        skeleton = build_skeleton(rig_spec)
    except BuildError as error:
        return {"canonical": canonical, "extra": [], "error": str(error)}
    return {
        "canonical": canonical,
        "extra": [b.name for b in skeleton.bones if b.name.startswith("extra_")],
    }


PLANNER_TOOLS: list[Callable[..., Any]] = [
    list_vocabulary,
    get_preset,
    get_view_rules,
    describe_proportions,
    dry_run_validate,
    list_existing_bones,
]
