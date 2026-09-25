"""Settings for saving rigs as prefabs in the Unity project (LLD 3.11a).

The prefab folder must be inside the project's Assets folder. The same check runs again in C#,
so a bad path is refused on both sides.
"""

import re
from dataclasses import dataclass

_SEGMENT = re.compile(r"^[A-Za-z0-9 _.\-()]+$")


class PrefabFolderError(ValueError):
    """The prefab folder is not a usable path inside the Unity project."""


def check_prefab_folder(folder: str) -> str:
    """The folder in Unity's own form ('Assets/Prefabs/Rigs'), or PrefabFolderError."""
    cleaned = folder.strip().replace("\\", "/").strip("/")
    parts = cleaned.split("/")
    if parts[0] != "Assets":
        raise PrefabFolderError(
            f"the prefab folder must be inside the project's Assets folder, got '{folder}'"
        )
    for part in parts:
        if not part or part in (".", "..") or part.startswith(".") or not _SEGMENT.match(part):
            raise PrefabFolderError(f"'{folder}' is not a usable prefab folder (bad part '{part}')")
    return cleaned


@dataclass(frozen=True)
class PrefabOptions:
    """Save each verified rig as <folder>/<rig name>.prefab.

    An existing prefab is kept as it is unless overwrite is set, because you may have added
    sprites or components to it since.
    """

    folder: str
    overwrite: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "folder", check_prefab_folder(self.folder))
