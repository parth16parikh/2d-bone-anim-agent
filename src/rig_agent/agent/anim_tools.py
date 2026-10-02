"""The animation planner's tools (Goal 2, A3). Both run against the rig being animated (the
agent's dependency), so the planner sees what its spec does to *this* character, in numbers."""

from collections.abc import Callable
from typing import Any

from pydantic_ai import RunContext

from rig_agent.animation.baker import BakeError, bake
from rig_agent.animation.pose import forward
from rig_agent.animation.templates import CYCLE_SECONDS, GAITS, RigInfo, gait_numbers
from rig_agent.animation.validator import validate_clip
from rig_agent.schemas.animation import CLIP_TYPES, CLIP_VIEWS, AnimationSpec
from rig_agent.schemas.skeleton import Skeleton

CLIP_MEANINGS = {
    "idle": "standing in place and breathing: the hip dips, the chest rises, the arms sway",
    "walk": "a walk cycle on the spot, facing right: planted feet move back at the ground speed",
    "run": "a run cycle on the spot, with a flight phase where both feet are off the ground",
    "backflip": "a standing backflip that plays once: crouch, jump, a full backward turn with the "
    "knees tucked, land; it starts and ends in the rest pose",
}


# The planner must return the clip the request asks for even when this rig cannot play it: the
# pipeline then stops and tells the user why. Showing a clip as "not allowed" made the planner
# quietly swap in an idle (6 of 6 front-view walk/run runs in the first animation eval).
KEEP_THE_CLIP = (
    "Always return the clip the request asks for, even if this rig's view cannot play it: the "
    "pipeline then explains the limit to the user. Never swap in a different clip."
)


def list_clip_types(ctx: RunContext[Skeleton]) -> dict[str, Any]:
    """The clip types, what each one is, and their default cycle length."""
    return {
        "rule": KEEP_THE_CLIP,
        "clips": {
            clip: {
                "views": list(CLIP_VIEWS[clip]),
                "default_cycle_seconds": CYCLE_SECONDS[clip],
                "what": CLIP_MEANINGS[clip],
            }
            for clip in CLIP_TYPES
        },
    }


def preview_clip(ctx: RunContext[Skeleton], spec: AnimationSpec) -> dict[str, Any]:
    """Bake the spec onto this rig and describe the result: cycle length, speed, step length,
    bounce and lean in numbers relative to the character's height, plus the validation result.
    Read these to check that the clip matches the description before you answer."""
    skeleton = ctx.deps
    if skeleton.view not in CLIP_VIEWS[spec.clip]:
        return {"clip": spec.clip, "previewed": False, "note": KEEP_THE_CLIP}
    try:
        clip = bake(spec, skeleton)
    except BakeError as error:
        return {"error": str(error)}
    report = validate_clip(clip, skeleton)
    H = skeleton.height
    hips = [
        forward(
            skeleton,
            {b: v[i] for b, v in clip.rotations.items()},
            {b: p[i] for b, p in clip.positions.items()},
        )["hip"].head[1]
        for i in range(clip.frame_count)
    ]
    result: dict[str, Any] = {
        "clip": spec.clip,
        "cycle_seconds": round(clip.duration_s, 3),
        "frames": clip.frame_count,
        "hip_bounce_share_of_height": round((max(hips) - min(hips)) / H, 4),
        "max_joint_bend_deg": round(report.metrics.get("max_joint_bend_deg", 0.0), 1),
        "passed": report.passed,
        "issues": [f"{i.code.value}: {i.message}" for i in report.issues],
    }
    if spec.clip == "backflip":
        result["jump_height_share_of_height"] = result.pop("hip_bounce_share_of_height")
        result["plays_once"] = True
    elif spec.clip in GAITS:
        gait = gait_numbers(spec, RigInfo.of(skeleton))
        result["step_length_share_of_height"] = round(gait.step / H, 3)
        result["ground_speed_heights_per_second"] = round(clip.ground_speed / H, 3)
        result["torso_lean_deg"] = spec.lean_deg + (8.0 if spec.clip == "run" else 2.0)
    elif skeleton.view == "side":
        result["torso_lean_deg"] = spec.lean_deg
    else:
        result["note"] = "lean_deg has no effect in the front view"
    return result


ANIM_TOOLS: list[Callable[..., Any]] = [list_clip_types, preview_clip]
