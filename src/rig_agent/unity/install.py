"""Copies the C# scripts into a Unity project (LLD 3.11a). Nothing outside Assets/RigAgent and
Assets/Rigs is ever written."""

from dataclasses import dataclass, field
from pathlib import Path

from rig_agent.unity.contract import RIGS_DIR, SCRIPTS_DIR

CSHARP_DIR = Path(__file__).parent / "csharp"


class UnityProjectError(ValueError):
    """The given folder is not a Unity project."""


@dataclass
class InstallResult:
    copied: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.copied)


def script_files() -> list[Path]:
    """The C# sources shipped with rig-agent, relative to the csharp folder."""
    return sorted(p.relative_to(CSHARP_DIR) for p in CSHARP_DIR.rglob("*.cs"))


def check_project(project: str | Path) -> Path:
    path = Path(project).expanduser()
    if not (path / "Assets").is_dir() or not (path / "ProjectSettings").is_dir():
        raise UnityProjectError(
            f"'{path}' is not a Unity project (it needs Assets/ and ProjectSettings/). "
            "Set UNITY_PROJECT_PATH to the folder that contains them."
        )
    return path


def install_scripts(project: str | Path) -> InstallResult:
    """Copy the scripts to <project>/Assets/RigAgent/{Editor,Runtime} and create Assets/Rigs."""
    root = check_project(project)
    result = InstallResult()
    for relative in script_files():
        source = CSHARP_DIR / relative
        target = root / SCRIPTS_DIR / relative
        label = str(Path(SCRIPTS_DIR) / relative)
        if target.exists() and target.read_bytes() == source.read_bytes():
            result.unchanged.append(label)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        result.copied.append(label)
    (root / RIGS_DIR).mkdir(parents=True, exist_ok=True)
    return result


def scripts_installed(project: str | Path) -> bool:
    """True if every script is in the project and identical to the shipped version."""
    root = check_project(project)
    return all(
        (root / SCRIPTS_DIR / relative).is_file()
        and (root / SCRIPTS_DIR / relative).read_bytes() == (CSHARP_DIR / relative).read_bytes()
        for relative in script_files()
    )
