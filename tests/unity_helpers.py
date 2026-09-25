"""Shared by the Unity tests: what the C# importer would write, and a fake Unity project."""

import json
from pathlib import Path

from rig_agent.schemas.skeleton import Skeleton
from rig_agent.unity.contract import REPORT_FILE, RIGS_DIR, SKELETON_FILE


def unity_report(skeleton, *, root="RigAgent_Output"):
    """What the C# importer writes to last_import.json for this skeleton."""
    by_id = {b.id: b for b in skeleton.bones}
    paths = {}
    for b in skeleton.bones:
        paths[b.id] = (
            paths[b.parent_id] + "/" if b.parent_id >= 0 else f"{root}/{skeleton.rig_name}/"
        ) + b.name
    return {
        "ok": True,
        "rig_name": skeleton.rig_name,
        "view": skeleton.view,
        "bone_count": len(skeleton.bones),
        "root_path": f"{root}/{skeleton.rig_name}",
        "max_head_error": 1e-6,
        "max_tail_error": 1e-6,
        "errors": [],
        "bones": [
            {
                "id": b.id,
                "name": b.name,
                "parent": by_id[b.parent_id].name if b.parent_id >= 0 else "",
                "path": paths[b.id],
                "world_head": list(b.world_head),
                "world_tail": list(b.world_tail),
                "depth": b.depth,
                "layer": b.layer or "",
            }
            for b in skeleton.bones
        ],
    }


def make_project(root: Path) -> Path:
    (root / "Assets").mkdir(parents=True, exist_ok=True)
    (root / "ProjectSettings").mkdir(parents=True, exist_ok=True)
    return root


def simulate_import(project: Path, mutate=None):
    """A stand-in for the Unity menu item: reads Assets/Rigs/skeleton.json, writes last_import.json."""

    def run() -> None:
        skeleton = Skeleton.model_validate_json((project / RIGS_DIR / SKELETON_FILE).read_text())
        report = unity_report(skeleton)
        if mutate:
            mutate(report)
        (project / RIGS_DIR / REPORT_FILE).write_text(json.dumps(report))

    return run


def simulate_batch_import(project: Path, mutate=None):
    """A stand-in for 'Import All Rigs': reads batch.json, writes last_batch.json."""
    from rig_agent.unity.contract import BATCH_FILE, BATCH_REPORT_FILE

    def run() -> None:
        manifest = json.loads((project / RIGS_DIR / BATCH_FILE).read_text())
        reports = []
        for file in manifest["files"]:
            skeleton = Skeleton.model_validate_json((project / file).read_text())
            report = unity_report(skeleton)
            report["file"] = file
            if mutate:
                mutate(report)
            reports.append(report)
        batch = {"ok": all(r["ok"] for r in reports), "errors": [], "rigs": reports}
        (project / RIGS_DIR / BATCH_REPORT_FILE).write_text(json.dumps(batch))

    return run


class FakePrefabs:
    """A stand-in for 'Save Rigs As Prefabs'. Remembers which prefab assets exist."""

    def __init__(self, project: Path, existing=(), failing=()):
        self.project = project
        self.existing = set(existing)  # rig names that already have a prefab
        self.failing = set(failing)
        self.requests: list[dict] = []

    def __call__(self) -> None:
        from rig_agent.unity.contract import PREFAB_FILE, PREFAB_REPORT_FILE

        request = json.loads((self.project / RIGS_DIR / PREFAB_FILE).read_text())
        self.requests.append(request)
        results = []
        for rig in request["rigs"]:
            path = f"{request['folder']}/{rig}.prefab"
            if rig in self.failing:
                results.append({"rig": rig, "path": path, "status": "failed", "message": "boom"})
                continue
            if rig in self.existing and not request["overwrite"]:
                status = "kept"
            else:
                status = "updated" if rig in self.existing else "created"
                self.existing.add(rig)
            results.append({"rig": rig, "path": path, "status": status, "message": ""})
        ok = all(r["status"] != "failed" for r in results)
        report = {"ok": ok, "folder": request["folder"], "errors": [], "results": results}
        (self.project / RIGS_DIR / PREFAB_REPORT_FILE).write_text(json.dumps(report))
