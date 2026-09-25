from pathlib import Path

from rig_agent.config import PROJECT_ROOT, Settings


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_a_relative_unity_project_path_is_taken_from_the_repository_root():
    assert (
        make(unity_project_path="unity-project").unity_project_path
        == PROJECT_ROOT / "unity-project"
    )


def test_an_absolute_unity_project_path_is_kept():
    assert make(unity_project_path="/somewhere/else").unity_project_path == Path("/somewhere/else")


def test_a_home_relative_path_is_expanded():
    assert make(unity_project_path="~/proj").unity_project_path == Path.home() / "proj"


def test_no_unity_project_path_stays_unset():
    assert make().unity_project_path is None


def test_the_repository_root_holds_the_project_files():
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
