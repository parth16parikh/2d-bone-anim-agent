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
