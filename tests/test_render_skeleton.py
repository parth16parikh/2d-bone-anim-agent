"""evals/render_skeleton.py (Phase H2): the offline PNG renderer for the eval harness."""

from pathlib import Path

import pytest

pytest.importorskip("PIL", reason="the renderer needs the eval extra: uv sync --extra eval")

from PIL import Image

from evals.render_skeleton import (
    IK_COLORS,
    THEME,
    RenderOptions,
    bone_shape,
    color_for,
    draw_key,
    grid_step,
    kind_of,
    link_gaps,
    main,
    render,
    render_folder,
    reported_bones,
)
from layout_helpers import bone
from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.export.json_exporter import RENDER_FILE, REPORT_FILE, export
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.schemas.validation import IssueCode, ValidationIssue, ValidationReport

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SMALL = RenderOptions(size=320)


def knight():
    """Side view with a sword (front layer), a cape (behind layer), toes and a jaw."""
    spec = RigSpec.model_validate_json((EXAMPLES / "knight_side.json").read_text())
    return build_skeleton(spec)


def failing_report(*bones):
    return ValidationReport(
        issues=[
            ValidationIssue(code=IssueCode.PROPORTION_OUT_OF_BAND, message="m", bones=list(bones))
        ]
    )


def png_bytes(image):
    import io

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def count_color(image, rgb, tol=12):
    import numpy as np

    pixels = np.asarray(image, dtype=int)
    return int((np.abs(pixels - np.array(rgb)).max(axis=-1) <= tol).sum())


# ---- the drawing rules match the viewer --------------------------------------------------------


def test_bones_are_coloured_by_side_like_the_viewer():
    assert [kind_of(n) for n in ("thigh_L", "hand_R", "spine", "extra_sword")] == [
        "left",
        "right",
        "center",
        "extra",
    ]


def test_draw_order_puts_behind_extras_back_and_front_extras_forward():
    sk = knight()
    assert draw_key(bone(sk, "extra_cape_1")) == -0.5  # depth 0, behind layer
    assert draw_key(bone(sk, "extra_sword")) == bone(sk, "extra_sword").depth + 0.5
    assert draw_key(bone(sk, "thigh_L")) == bone(sk, "thigh_L").depth


def test_a_bone_diamond_runs_from_its_pivot_to_its_tip():
    sk = knight()
    shape = bone_shape(bone(sk, "shin_R"), sk.height)
    assert shape[0] == bone(sk, "shin_R").world_head
    assert shape[2] == bone(sk, "shin_R").world_tail
    assert len(shape) == 4


def test_link_gaps_are_the_bones_that_do_not_start_on_their_parents_tail():
    sk = knight()
    by_head = {b.world_head: b.name for b in sk.bones}
    starts = {by_head[head] for _, head in link_gaps(sk)}
    assert "jaw" in starts  # the jaw hangs from the middle of the head, not its tip
    assert "spine" not in starts and "shin_L" not in starts  # chained bones join exactly


def test_reported_bones_expand_a_spec_extra_name_to_its_built_bones():
    sk = knight()
    names = reported_bones(failing_report("extra_cape", "head"), sk)
    assert {"extra_cape_1", "extra_cape_2", "extra_cape_3", "head"} <= names
    assert "extra_sword" not in names
    assert reported_bones(None, sk) == set()


def test_colour_modes():
    sk = knight()
    lo, hi = min(b.depth for b in sk.bones), max(b.depth for b in sk.bones)
    assert color_for(bone(sk, "thigh_L"), "side", lo, hi) == THEME["left"]
    assert color_for(bone(sk, "thigh_L"), "ik", lo, hi) == IK_COLORS["leg_L"]
    assert color_for(bone(sk, "extra_sword"), "ik", lo, hi) == THEME["none"]
    assert color_for(bone(sk, "spine"), "depth", lo, hi) == THEME["center"]
    near, far = (
        color_for(bone(sk, "thigh_R"), "depth", lo, hi),
        color_for(bone(sk, "thigh_L"), "depth", lo, hi),
    )
    assert near[0] > near[2] and far[2] > far[0]  # in front is orange, behind is blue


def test_grid_step_keeps_lines_apart():
    assert grid_step(1000) == 0.1
    assert grid_step(100) == 1.0
    assert grid_step(1) == 10.0  # the largest step when nothing else is wide enough


# ---- render() ----------------------------------------------------------------------------------


def test_render_returns_a_square_rgb_image_of_the_asked_size():
    image = render(knight(), options=SMALL)
    assert image.size == (320, 320) and image.mode == "RGB"


def test_render_is_deterministic():
    """The eval harness compares runs, so the same rig must always give the same bytes."""
    sk = knight()
    assert png_bytes(render(sk, options=SMALL)) == png_bytes(render(sk, options=SMALL))


def test_a_failing_report_shows_red_and_a_passing_one_does_not():
    sk = knight()
    ok = render(sk, ValidationReport(), SMALL)
    bad = render(sk, failing_report("head"), SMALL)
    assert count_color(ok, THEME["bad"]) == 0
    assert count_color(bad, THEME["bad"]) > 50  # the FAILED badge and the ring on the head


def test_options_change_the_picture():
    sk = knight()
    base = png_bytes(render(sk, options=SMALL))
    assert png_bytes(render(sk, options=RenderOptions(size=320, labels=False))) != base
    assert png_bytes(render(sk, options=RenderOptions(size=320, color="depth"))) != base
    assert png_bytes(render(sk, options=RenderOptions(size=320, color="ik"))) != base


def test_a_tiny_size_is_refused():
    with pytest.raises(ValueError, match="at least"):
        render(knight(), options=RenderOptions(size=50))


# ---- files and the command line ----------------------------------------------------------------


def test_render_folder_writes_skeleton_png_next_to_the_rig(tmp_path):
    export(knight(), ValidationReport(), tmp_path / "knight")
    target = render_folder(tmp_path / "knight", options=SMALL)
    assert target == tmp_path / "knight" / RENDER_FILE
    assert Image.open(target).size == (320, 320)


def test_render_folder_can_write_elsewhere_named_after_the_folder(tmp_path):
    export(knight(), ValidationReport(), tmp_path / "out" / "knight")
    target = render_folder(tmp_path / "out" / "knight", dest=tmp_path / "renders", options=SMALL)
    assert target == tmp_path / "renders" / "knight.png" and target.is_file()
    assert not (tmp_path / "out" / "knight" / RENDER_FILE).exists()


def test_a_rig_without_its_report_still_renders(tmp_path):
    export(knight(), ValidationReport(), tmp_path / "knight")
    (tmp_path / "knight" / REPORT_FILE).unlink()
    assert render_folder(tmp_path / "knight", options=SMALL).is_file()


def test_main_renders_every_rig_under_all_and_skips_a_broken_one(tmp_path, capsys):
    out = tmp_path / "out"
    export(knight(), ValidationReport(), out / "a")
    export(knight(), ValidationReport(), out / "b")
    (out / "broken").mkdir()
    (out / "broken" / "skeleton.json").write_text("{not json")
    (out / "notes").mkdir()  # no skeleton.json: not a rig, not picked up at all

    code = main(["--all", str(out), "--size", "320"])

    captured = capsys.readouterr()
    assert code == 1  # one rig failed
    assert (out / "a" / RENDER_FILE).is_file() and (out / "b" / RENDER_FILE).is_file()
    assert "skipped" in captured.err and "broken" in captured.err
    assert "notes" not in captured.err


def test_main_exits_zero_when_every_rig_renders(tmp_path):
    export(knight(), ValidationReport(), tmp_path / "knight")
    assert main([str(tmp_path / "knight"), "--size", "320", "--color", "ik", "--no-labels"]) == 0


@pytest.mark.parametrize("argv", [[], ["--size", "10", "x"], ["--all", "/does/not/exist"]])
def test_main_rejects_bad_arguments(argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
