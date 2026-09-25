import re
from pathlib import Path

import pytest

from rig_agent.unity import contract
from rig_agent.unity.install import (
    CSHARP_DIR,
    UnityProjectError,
    check_project,
    install_scripts,
    script_files,
    scripts_installed,
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "Assets").mkdir()
    (tmp_path / "ProjectSettings").mkdir()
    return tmp_path


def read(name):
    return (CSHARP_DIR / name).read_text(encoding="utf-8")


# ---- the C# sources and the Python contract must agree ------------------------------------------


def test_the_expected_scripts_ship_with_the_package():
    assert [str(p) for p in script_files()] == [
        "Editor/RigImporter.cs",
        "Runtime/BoneGizmo.cs",
        "Runtime/FacingController.cs",
    ]


def test_the_importer_uses_the_shared_names():
    code = read("Editor/RigImporter.cs")
    for name, value in {
        "OutputRoot": contract.OUTPUT_ROOT,
        "RigsDir": contract.RIGS_DIR,
        "SkeletonFile": contract.SKELETON_FILE,
        "ReportFile": contract.REPORT_FILE,
        "LogTag": contract.IMPORT_LOG_TAG,
        "MenuImportLatest": contract.IMPORT_MENU,
        "BatchDir": contract.BATCH_DIR,
        "BatchFile": contract.BATCH_FILE,
        "BatchReportFile": contract.BATCH_REPORT_FILE,
        "MenuImportAll": contract.IMPORT_ALL_MENU,
        "PrefabFile": contract.PREFAB_FILE,
        "PrefabReportFile": contract.PREFAB_REPORT_FILE,
        "MenuSavePrefabs": contract.SAVE_PREFABS_MENU,
    }.items():
        assert f'public const string {name} = "{value}";' in code, name


def test_the_only_menu_items_python_may_run_are_the_rig_agent_ones():
    from rig_agent.unity.mcp_client import ALLOWED_MENU_ITEMS

    assert ALLOWED_MENU_ITEMS == {
        contract.IMPORT_MENU,
        contract.IMPORT_ALL_MENU,
        contract.SAVE_PREFABS_MENU,
    }
    code = read("Editor/RigImporter.cs")
    for constant in ("MenuImportLatest", "MenuImportAll", "MenuSavePrefabs"):
        assert f"[MenuItem({constant})]" in code, constant


def test_the_scripts_are_in_a_namespace_and_named_like_their_files():
    for relative in script_files():
        code = read(str(relative))
        assert "namespace RigAgent" in code
        class_name = relative.stem
        assert re.search(rf"\bclass {class_name}\b", code), relative


def test_editor_code_lives_in_an_editor_folder_and_uses_editor_apis_only_there():
    assert "using UnityEditor;" in read("Editor/RigImporter.cs")
    for runtime in ("Runtime/BoneGizmo.cs", "Runtime/FacingController.cs"):
        assert "UnityEditor" not in read(runtime), runtime


def test_the_importer_only_touches_its_own_root_and_never_deletes_assets():
    code = read("Editor/RigImporter.cs")
    assert "AssetDatabase.DeleteAsset" not in code and "FileUtil.DeleteFileOrDirectory" not in code
    assert "File.Delete" not in code
    assert "Directory.Delete" not in code


def test_the_importer_reads_the_fields_the_python_side_writes():
    from rig_agent.schemas.skeleton import Bone

    code = read("Editor/RigImporter.cs")
    used = {"id", "name", "parent_id", "world_head", "world_tail", "local_position",
            "local_rotation_deg", "length", "depth", "layer", "ik_chain", "mirror_of"}  # fmt: skip
    assert used <= set(Bone.model_fields)
    for field in used:
        assert re.search(rf"public [\w\[\]]+ {field};", code), field


# ---- installing ----------------------------------------------------------------------------------


def test_install_copies_every_script_and_creates_the_rigs_folder(project):
    result = install_scripts(project)
    assert sorted(result.copied) == [
        "Assets/RigAgent/Editor/RigImporter.cs",
        "Assets/RigAgent/Runtime/BoneGizmo.cs",
        "Assets/RigAgent/Runtime/FacingController.cs",
    ]
    assert result.unchanged == [] and result.changed
    assert (project / "Assets/RigAgent/Editor/RigImporter.cs").read_bytes() == (
        CSHARP_DIR / "Editor/RigImporter.cs"
    ).read_bytes()
    assert (project / "Assets/Rigs").is_dir()


def test_installing_twice_changes_nothing_the_second_time(project):
    install_scripts(project)
    again = install_scripts(project)
    assert again.copied == [] and len(again.unchanged) == 3 and not again.changed


def test_an_edited_script_is_restored(project):
    install_scripts(project)
    target = project / "Assets/RigAgent/Runtime/BoneGizmo.cs"
    target.write_text("// edited")
    assert not scripts_installed(project)
    assert install_scripts(project).copied == ["Assets/RigAgent/Runtime/BoneGizmo.cs"]
    assert scripts_installed(project)


def test_scripts_installed_is_false_for_a_fresh_project(project):
    assert not scripts_installed(project)


def test_only_the_two_expected_folders_are_written(project):
    before = {p for p in project.rglob("*")}
    install_scripts(project)
    new = {p.relative_to(project).parts[:2] for p in project.rglob("*") if p not in before}
    assert {parts[:2] for parts in new} <= {("Assets", "RigAgent"), ("Assets", "Rigs")}


def test_a_folder_that_is_not_a_unity_project_is_refused(tmp_path):
    with pytest.raises(UnityProjectError, match="not a Unity project"):
        install_scripts(tmp_path)
    with pytest.raises(UnityProjectError):
        check_project(tmp_path / "missing")
    assert list(Path(tmp_path).iterdir()) == []
