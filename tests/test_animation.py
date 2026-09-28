"""Goal 2, phase A1: animation schema, FK, IK, templates, baker, validator, exporter and CLI."""

import itertools
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from rig_agent.animation.baker import BakeError, bake
from rig_agent.animation.ik import bend_sign, solve_two_bone
from rig_agent.animation.pose import forward
from rig_agent.animation.templates import TEMPLATES, RigInfo, cycle_frames, ground_speed
from rig_agent.animation.validator import validate_clip
from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.cli import main
from rig_agent.export.animation_exporter import animation_paths, export_animation, load_animation
from rig_agent.export.json_exporter import delete_rig, export
from rig_agent.schemas.animation import AnimationClip, AnimationSpec
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.validation import IssueCode, ValidationReport

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def rig(name):
    return build_skeleton(RigSpec.model_validate_json((EXAMPLES / f"{name}.json").read_text()))


KNIGHT = rig("knight_side")  # side view: sword, cape, toes, jaw
ELF = rig("elf_front")  # front view, A-pose
MAGE = rig("chibi_mage_front")  # front view, T-pose, extras on the hands and head


def spec(clip="walk", **kw):
    return AnimationSpec(clip=clip, style="test", **kw)


def codes(report):
    return {i.code for i in report.issues}


# ---- schema ------------------------------------------------------------------------------------


def test_spec_knobs_are_bounded():
    with pytest.raises(ValidationError):
        spec(speed=3.0)
    with pytest.raises(ValidationError):
        spec(lean_deg=40)
    with pytest.raises(ValidationError):
        AnimationSpec(clip="dance", style="x")


def test_a_clip_needs_every_track_to_have_every_frame():
    clip = bake(spec(), KNIGHT)
    data = clip.model_dump()
    data["rotations"]["hip"] = [0.0]  # one frame short of the others
    with pytest.raises(ValidationError, match="frames"):
        AnimationClip.model_validate(data)


# ---- FK and IK -----------------------------------------------------------------------------------


@pytest.mark.parametrize("skeleton", [KNIGHT, ELF, MAGE], ids=["knight", "elf", "mage"])
def test_forward_kinematics_reproduces_the_skeleton(skeleton):
    world = forward(skeleton)
    for bone in skeleton.bones:
        assert math.dist(world[bone.name].head, bone.world_head) < 5e-6, bone.name
        assert math.dist(world[bone.name].tail, bone.world_tail) < 5e-6, bone.name


def test_two_bone_ik_reaches_and_bends_to_the_asked_side():
    for side in ("left", "right"):
        s = solve_two_bone((0, 0), (0.3, -0.6), 0.5, 0.4, side)
        end = (
            s.joint[0] + 0.4 * math.cos(math.radians(s.lower_deg)),
            s.joint[1] + 0.4 * math.sin(math.radians(s.lower_deg)),
        )
        assert s.reached and math.dist(end, (0.3, -0.6)) < 1e-9
        # the joint sits on the counter-clockwise side of root -> target for "left"
        cross = 0.3 * s.joint[1] - (-0.6) * s.joint[0]
        assert (cross > 0) == (side == "left")
        # and the lower bone turns the way bend_sign says
        assert bend_sign(side) * (s.lower_deg - s.upper_deg) > 0


def test_an_unreachable_target_is_reported_and_the_limb_points_at_it():
    s = solve_two_bone((0, 0), (0, -2.0), 0.5, 0.4, "left")
    assert not s.reached
    assert s.upper_deg == pytest.approx(-90) and s.lower_deg == pytest.approx(-90)


# ---- templates -----------------------------------------------------------------------------------


@pytest.mark.parametrize("clip", ["idle", "walk", "run"])
def test_templates_are_periodic(clip):
    info = RigInfo.of(KNIGHT)
    s = spec(clip, stride=1.3, knee_lift=1.4, bounce=1.7)
    a, b = TEMPLATES[clip](s, info, 0.0), TEMPLATES[clip](s, info, 1.0)
    assert a.hip_offset == pytest.approx(b.hip_offset, abs=1e-12)
    assert a.deltas == pytest.approx(b.deltas, abs=1e-9)
    for chain in a.feet:
        assert a.feet[chain][0] == pytest.approx(b.feet[chain][0], abs=1e-12)


def test_ground_speed_matches_the_whole_frame_cycle():
    """At 2x speed a run cycle is 8 frames (0.333 s), not the nominal 0.35 s: the speed the game
    moves the character at must use the real cycle, or planted feet slide."""
    info = RigInfo.of(KNIGHT)
    s = spec("run", speed=2.0)
    assert cycle_frames(s) == 8
    duty, step = 0.38, 0.9 * info.leg_length
    assert ground_speed(s, info) == pytest.approx(step / (duty * 8 / 24))
    assert ground_speed(spec("idle"), info) == 0.0


# ---- baker ---------------------------------------------------------------------------------------


def test_a_walk_on_a_front_view_rig_is_refused():
    with pytest.raises(BakeError, match="side-view"):
        bake(spec("walk"), ELF)


def test_the_clip_closes_on_its_first_pose_and_keys_ik_targets_for_every_limb():
    clip = bake(spec("walk"), KNIGHT)
    assert clip.frame_count == cycle_frames(clip.spec) + 1
    assert {t.chain for t in clip.ik_targets} == {"arm_L", "arm_R", "leg_L", "leg_R"}
    assert {t.target for t in clip.ik_targets} >= {"target_foot_R", "target_hand_L"}
    for values in clip.rotations.values():
        assert values[-1] == pytest.approx(values[0], abs=1e-4)
    assert "hip" in clip.positions and clip.ground_speed > 0


def test_angle_tracks_never_wrap_around():
    """A 179 -> -179 jump would make Unity spin the bone the long way round."""
    for clip in (bake(spec("run", knee_lift=1.5), KNIGHT), bake(spec("idle"), MAGE)):
        for values in clip.rotations.values():
            assert max(abs(b - a) for a, b in itertools.pairwise(values)) < 90


def test_bones_that_never_move_are_not_keyed():
    clip = bake(spec("idle", arm_swing=0.0, bounce=0.0), ELF)
    assert "extra_cape_1" not in clip.rotations and "root" not in clip.rotations


# ---- validator: baked clips pass ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("skeleton", "clip"),
    [(KNIGHT, "idle"), (KNIGHT, "walk"), (KNIGHT, "run"), (ELF, "idle"), (MAGE, "idle")],
)
def test_baked_clips_pass_across_the_parameter_extremes(skeleton, clip):
    for kw in (
        {},
        {"speed": 0.5, "stride": 0.5, "knee_lift": 0.5, "bounce": 0.0, "arm_swing": 0.0, "fps": 12},
        {
            "speed": 2.0,
            "stride": 1.5,
            "knee_lift": 1.5,
            "bounce": 2.0,
            "arm_swing": 2.0,
            "lean_deg": 25,
            "fps": 60,
        },
        {"lean_deg": -10, "fps": 12, "knee_lift": 1.5},
    ):
        report = validate_clip(bake(spec(clip, **kw), skeleton), skeleton)
        assert report.passed, (kw, [i.message for i in report.issues])
        assert report.metrics["loop_error"] < 1e-4
        assert report.metrics["max_foot_slip"] < 0.005
        assert report.metrics["max_ground_penetration"] <= 0.003


# ---- validator: it catches each kind of broken clip ------------------------------------------------


def broken(mutate, clip_type="walk"):
    clip = bake(spec(clip_type), KNIGHT)
    data = clip.model_dump()
    mutate(data)
    return validate_clip(AnimationClip.model_validate(data), KNIGHT)


def test_catches_a_clip_for_another_view():
    clip = bake(spec("idle"), ELF)
    assert IssueCode.CLIP_VIEW_MISMATCH in codes(validate_clip(clip, KNIGHT))


def test_catches_unknown_bones():
    report = broken(lambda d: d["rotations"].update(tail_bone=d["rotations"]["spine"]))
    assert IssueCode.CLIP_RIG_MISMATCH in codes(report)


def test_catches_nan():
    report = broken(lambda d: d["rotations"]["spine"].__setitem__(3, float("nan")))
    assert IssueCode.NON_FINITE in codes(report)


def test_catches_an_ik_target_off_its_foot():
    def move(d):
        track = next(t for t in d["ik_targets"] if t["chain"] == "leg_R")
        track["positions"][5] = (track["positions"][5][0] + 0.1, track["positions"][5][1])

    assert IssueCode.IK_TARGET_MISMATCH in codes(broken(move))


def test_catches_a_knee_bent_the_wrong_way():
    def hyperextend(d):
        d["rotations"]["shin_R"] = [
            v + 60.0 for v in d["rotations"]["shin_R"]
        ]  # knee "left": + is backwards
        d["ik_targets"] = []  # isolate the joint check

    report = broken(hyperextend)
    assert IssueCode.JOINT_LIMIT in codes(report)
    assert any("wrong way" in i.message for i in report.issues)


def test_catches_a_sliding_foot():
    def slide(d):
        d["ground_speed"] = d["ground_speed"] * 3  # the feet move at a third of the stated speed

    assert IssueCode.FOOT_SLIDING in codes(broken(slide))


def test_catches_a_foot_below_the_ground():
    def sink(d):
        # the hip's parent (the root) points up, so the hip's local x is world up: sink it 0.3
        d["positions"]["hip"] = [(x - 0.3, y) for x, y in d["positions"]["hip"]]
        d["ik_targets"] = []

    assert IssueCode.GROUND_PENETRATION in codes(broken(sink, "idle"))


def test_catches_a_loop_that_does_not_close():
    def open_loop(d):
        d["rotations"]["spine"][-1] += 20.0

    report = broken(open_loop)
    assert IssueCode.LOOP_DISCONTINUITY in codes(report)
    assert report.metrics["loop_error"] == pytest.approx(20.0, abs=0.01)


# ---- exporter and CLI ------------------------------------------------------------------------------


def test_export_and_load_round_trip(tmp_path):
    clip = bake(spec("run"), KNIGHT)
    paths = export_animation(clip, ValidationReport(), tmp_path / "knight")
    assert paths == animation_paths(tmp_path / "knight", "run")
    assert paths.clip_path.name == "run.json" and paths.report_path.name == "run.report.json"
    assert load_animation(paths.clip_path) == clip


def test_deleting_a_rig_also_deletes_its_clips(tmp_path):
    folder = tmp_path / "knight"
    export(KNIGHT, ValidationReport(), folder)
    export_animation(bake(spec("walk"), KNIGHT), ValidationReport(), folder)
    result = delete_rig(folder)
    assert (
        "animations/walk.json" in result.removed_files
        and "animations/walk.report.json" in result.removed_files
    )
    assert result.folder_removed and not folder.exists()


def test_cli_bakes_a_default_clip(tmp_path, capsys):
    export(KNIGHT, ValidationReport(), tmp_path / "knight")
    assert main(["animate-build", "--rig", str(tmp_path / "knight"), "--clip", "walk"]) == 0
    out = capsys.readouterr().out
    assert "Baked 'walk'" in out and "ground speed" in out
    assert (tmp_path / "knight" / "animations" / "walk.json").is_file()


def test_cli_bakes_from_a_spec_file_under_its_own_name(tmp_path):
    export(KNIGHT, ValidationReport(), tmp_path / "knight")
    spec_file = tmp_path / "heavy.json"
    spec_file.write_text(spec("walk", speed=0.7, bounce=0.4, lean_deg=10).model_dump_json())
    code = main(
        [
            "animate-build",
            "--rig",
            str(tmp_path / "knight"),
            "--spec",
            str(spec_file),
            "--name",
            "heavy_walk",
        ]
    )
    assert code == 0
    assert load_animation(tmp_path / "knight" / "animations" / "heavy_walk.json").spec.speed == 0.7


def test_cli_refuses_a_walk_on_a_front_rig_and_bad_input(tmp_path, capsys):
    export(ELF, ValidationReport(), tmp_path / "elf")
    assert main(["animate-build", "--rig", str(tmp_path / "elf"), "--clip", "walk"]) == 2
    assert "side-view" in capsys.readouterr().err
    assert main(["animate-build", "--rig", str(tmp_path / "nope"), "--clip", "idle"]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"clip": "moonwalk"}')
    assert main(["animate-build", "--rig", str(tmp_path / "elf"), "--spec", str(bad)]) == 2


# ---- the backflip ----------------------------------------------------------------------------------

CHIBI_SIDE = build_skeleton(
    RigSpec.model_validate(
        {
            **RigSpec.model_validate_json((EXAMPLES / "knight_side.json").read_text()).model_dump(),
            "preset": "chibi",
        }
    )
)


def test_a_backflip_is_side_view_only():
    with pytest.raises(BakeError, match="side-view"):
        bake(spec("backflip"), ELF)


def test_a_backflip_plays_once_in_place_and_starts_and_ends_at_rest():
    clip = bake(spec("backflip"), KNIGHT)
    assert clip.loop is False and clip.ground_speed == 0.0
    rest = {b.name: b for b in KNIGHT.bones}
    for bone, values in clip.rotations.items():
        for frame in (0, -1):  # the hip ends a full turn later: the same pose
            assert math.remainder(
                values[frame] - rest[bone].local_rotation_deg, 360
            ) == pytest.approx(0, abs=1e-4), bone
    assert clip.positions["hip"][0] == clip.positions["hip"][-1]


def test_the_body_turns_exactly_once_backwards():
    hip = bake(spec("backflip"), KNIGHT).rotations["hip"]
    assert hip[-1] - hip[0] == pytest.approx(
        360.0, abs=1e-4
    )  # counter-clockwise: backwards when facing +X
    assert all(b >= a - 1e-9 for a, b in itertools.pairwise(hip))  # never turns back


@pytest.mark.parametrize("skeleton", [KNIGHT, CHIBI_SIDE], ids=["knight", "chibi"])
def test_even_the_lowest_backflip_clears_the_floor(skeleton):
    """A chibi's big head needs a higher jump than a knight's: the baker works it out per rig."""
    for kw in (
        {"bounce": 0.0},
        {"bounce": 2.0, "knee_lift": 0.5, "arm_swing": 2.0},
        {"speed": 2.0, "fps": 12},
    ):
        report = validate_clip(bake(spec("backflip", **kw), skeleton), skeleton)
        assert report.passed, (kw, [i.message for i in report.issues])
        assert report.metrics["max_body_below_floor"] == 0.0


def test_a_held_item_stays_steady_while_the_arm_swings():
    """The knight's sword hand turns against the arm's swing (capped like a real wrist); the
    empty hand does not."""
    clip = bake(spec("run", arm_swing=1.5), KNIGHT)
    rest = {b.name: b.local_rotation_deg for b in KNIGHT.bones}
    wrist = [v - rest["hand_R"] for v in clip.rotations["hand_R"]]
    swing = [
        a + b - rest["upper_arm_R"] - rest["forearm_R"]
        for a, b in zip(clip.rotations["upper_arm_R"], clip.rotations["forearm_R"], strict=True)
    ]
    assert "hand_L" not in clip.rotations  # nothing in that hand: nothing to steady
    assert max(abs(w) for w in wrist) == pytest.approx(70.0)  # the cap
    for w, s in zip(wrist, swing, strict=True):
        assert w == pytest.approx(-max(-70.0, min(70.0, s)), abs=1e-4)


def test_a_body_part_below_the_floor_is_caught():
    def sink_the_sword(d):
        d["rotations"]["hand_R"] = [
            v - 70.0 for v in d["rotations"]["hand_R"]
        ]  # the blade straight down, into the floor
        d["ik_targets"] = []

    report = broken(sink_the_sword)
    assert any(
        i.code == IssueCode.GROUND_PENETRATION and i.bones == ["extra_sword"] for i in report.issues
    )


def test_a_prop_standing_on_the_floor_at_rest_is_not_a_failure():
    """The mage's staff already touches the floor at rest; an idle's bob must not fail it."""
    assert validate_clip(bake(spec("idle"), MAGE), MAGE).passed
