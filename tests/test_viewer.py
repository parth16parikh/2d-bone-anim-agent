"""The browser viewer: its sample data must be current, and its Node unit tests must pass."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "make_viewer_samples", ROOT / "scripts" / "make_viewer_samples.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_viewer_files_exist():
    for name in ("index.html", "viewer.js", "samples.js", "viewer.test.js"):
        assert (VIEWER / name).is_file(), name


def test_samples_match_what_the_builder_produces_today():
    generated = load_generator().render()
    assert (VIEWER / "samples.js").read_text(encoding="utf-8") == generated, (
        "viewer/samples.js is stale: run `uv run python scripts/make_viewer_samples.py`"
    )


def test_every_sample_report_passed():
    text = (VIEWER / "samples.js").read_text(encoding="utf-8")
    assert text.count('"passed":true') == 3 and '"passed":false' not in text


def test_the_page_loads_its_scripts_in_order():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    assert html.index('src="samples.js"') < html.index('src="viewer.js"')
    for element_id in ("stage", "tree", "details", "report", "meta", "notice", "sample", "pick"):
        assert f'id="{element_id}"' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_viewer_unit_tests_pass_in_node():
    result = subprocess.run(
        ["node", "--test", str(VIEWER / "viewer.test.js")],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_viewer_poses_a_baked_clip_exactly_like_python(tmp_path):
    """The viewer's poseAt must be the same forward kinematics as rig_agent.animation.pose, or the
    browser preview would show a different motion from the one Unity plays."""
    import json
    import math

    from rig_agent.animation.baker import bake
    from rig_agent.animation.pose import forward
    from rig_agent.builder.skeleton_builder import build_skeleton
    from rig_agent.schemas.animation import AnimationSpec
    from rig_agent.schemas.rig_spec import RigSpec

    skeleton = build_skeleton(
        RigSpec.model_validate_json((ROOT / "examples" / "knight_side.json").read_text())
    )
    clip = bake(AnimationSpec(clip="run", style="t", knee_lift=1.4, lean_deg=12), skeleton)
    (tmp_path / "skeleton.json").write_text(skeleton.model_dump_json())
    (tmp_path / "clip.json").write_text(clip.model_dump_json())
    script = (
        "const V = require(process.argv[1]); const fs = require('fs');"
        "const sk = JSON.parse(fs.readFileSync(process.argv[2])); const c = JSON.parse(fs.readFileSync(process.argv[3]));"
        "const out = []; for (let f = 0; f < c.frame_count; f++) out.push(V.poseAt(sk, c, f).bones.map((b) => [b.name, b.world_head, b.world_tail]));"
        "console.log(JSON.stringify(out));"
    )
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(VIEWER / "viewer.js"),
            str(tmp_path / "skeleton.json"),
            str(tmp_path / "clip.json"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    frames = json.loads(result.stdout)
    worst = 0.0
    for f, bones in enumerate(frames):
        world = forward(
            skeleton,
            {b: v[f] for b, v in clip.rotations.items()},
            {b: p[f] for b, p in clip.positions.items()},
        )
        for name, head, tail in bones:
            worst = max(worst, math.dist(head, world[name].head), math.dist(tail, world[name].tail))
    assert worst < 1e-9, worst
