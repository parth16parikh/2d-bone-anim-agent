"""Tests against a real, running Unity Editor. Opt-in:

    uv run pytest -m unity

They need Unity open on the project in UNITY_PROJECT_PATH with the MCP for Unity server started,
and are skipped when it cannot be reached. They change the open scene (objects under
RigAgent_Output only); use Tools > Rig Agent > Clear Output to remove them.
"""

from pathlib import Path

import pytest

from rig_agent.builder.skeleton_builder import build_skeleton
from rig_agent.config import settings
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.unity.batch import collect_rigs
from rig_agent.unity.delivery import UnityDelivery
from rig_agent.unity.mcp_client import UnityMcpError, check_unity

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _reachable() -> bool:
    try:
        return check_unity().ok and settings.unity_project_path is not None
    except UnityMcpError:
        return False


pytestmark = [
    pytest.mark.unity,
    pytest.mark.skipif(not _reachable(), reason="no Unity Editor with the MCP server is reachable"),
]


def _skeleton(name):
    spec = RigSpec.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))
    return build_skeleton(spec, source_prompt=spec.character_summary)


def test_unity_is_ready_and_has_the_tools_we_need():
    status = check_unity()
    assert status.ok and status.missing_tools == []


@pytest.mark.parametrize("example", ["knight_side.json", "elf_front.json", "chibi_mage_front.json"])
def test_every_example_rig_is_built_and_verified_in_unity(example):
    skeleton = _skeleton(example)
    result = UnityDelivery(report_wait=30).deliver(skeleton)
    assert result.status == "applied", result.detail
    assert f"{len(skeleton.bones)} bones under RigAgent_Output/{skeleton.rig_name}" in result.detail


def test_importing_the_same_rig_twice_replaces_it():
    skeleton = _skeleton("knight_side.json")
    delivery = UnityDelivery(report_wait=30)
    assert delivery.deliver(skeleton).status == "applied"
    assert delivery.deliver(skeleton).status == "applied"


def test_every_rig_in_a_folder_is_built_side_by_side_and_verified(tmp_path):
    for example in ("knight_side.json", "elf_front.json", "chibi_mage_front.json"):
        folder = tmp_path / example.removesuffix(".json")
        folder.mkdir()
        (folder / "skeleton.json").write_text(_skeleton(example).model_dump_json(indent=2))
    rigs, skipped = collect_rigs(tmp_path)
    assert len(rigs) == 3 and not skipped

    result = UnityDelivery(report_wait=30).deliver_all(rigs)
    assert result.status == "applied", result
    assert [o.status for o in result.rigs] == ["applied"] * 3
