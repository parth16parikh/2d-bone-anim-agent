"""Delivers a skeleton to the open Unity Editor and verifies the result (LLD 3.11b).

apply():       make sure the C# scripts are installed, write Assets/Rigs/skeleton.json, and
               trigger the import menu item through the MCP allowlist.
verify():      read the importer's report, compare it with the JSON, and check the console. When
               prefab options are set, a verified rig is then saved as a prefab.
deliver_all(): build every rig from out/ in one go, side by side, then verify each one.

A failure here never invalidates the rig: the JSON is already delivered (LLD 3.13).
"""

import asyncio
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from rig_agent.config import settings
from rig_agent.schemas.skeleton import Skeleton
from rig_agent.schemas.state import UnityResult
from rig_agent.unity.batch import BatchRig
from rig_agent.unity.contract import (
    BATCH_DIR,
    BATCH_FILE,
    BATCH_REPORT_FILE,
    IMPORT_ALL_MENU,
    IMPORT_LOG_TAG,
    IMPORT_MENU,
    OUTPUT_ROOT,
    PREFAB_FILE,
    PREFAB_REPORT_FILE,
    REPORT_FILE,
    RIGS_DIR,
    SAVE_PREFABS_MENU,
    SKELETON_FILE,
)
from rig_agent.unity.install import UnityProjectError, install_scripts, scripts_installed
from rig_agent.unity.mcp_client import UnityMcpClient, UnityMcpError, UnityUnavailable, run_sync
from rig_agent.unity.prefab import PrefabOptions
from rig_agent.unity.verify import compare_import

Say = Callable[[str], None]


@dataclass
class RigOutcome:
    """What happened to one rig of a batch."""

    name: str
    status: Literal["applied", "failed"]
    detail: str = ""
    prefab: str = ""  # the prefab asset path when one was created, updated or kept


@dataclass
class BatchResult:
    status: Literal["applied", "failed", "unavailable"]
    detail: str = ""
    rigs: list[RigOutcome] = field(default_factory=list)


def _silent(message: str) -> None:
    pass


class UnityDelivery:
    def __init__(
        self,
        target: object = None,
        project: str | Path | None = None,
        *,
        timeout: float | None = None,
        report_wait: float = 30.0,
        compile_wait: float = 120.0,
        say: Say = _silent,
        prefab: PrefabOptions | None = None,
    ):
        self.target = target
        self.project = Path(project) if project else settings.unity_project_path
        self.timeout = timeout
        self.report_wait = report_wait
        self.compile_wait = compile_wait
        self.say = say
        self.prefab = prefab
        self._report_mtime_before = 0

    # ---- public, synchronous API ------------------------------------------------------------

    def apply(self, skeleton: Skeleton) -> UnityResult:
        """Trigger the import. Status is 'applied' when it was started, else why not."""
        return self._guarded(self._apply(skeleton))

    def verify(self, skeleton: Skeleton) -> UnityResult:
        """Check what Unity created against the JSON. Status is 'applied' only if it matches."""
        return self._guarded(self._verify(skeleton))

    def deliver(self, skeleton: Skeleton) -> UnityResult:
        """apply() then verify()."""
        result = self.apply(skeleton)
        return self.verify(skeleton) if result.status == "applied" else result

    def deliver_all(self, rigs: Sequence[BatchRig]) -> BatchResult:
        """Build every rig in one go, side by side, then verify each. Prefabs follow if set."""
        try:
            return run_sync(self._deliver_all(rigs))
        except UnityUnavailable as error:
            return BatchResult(status="unavailable", detail=str(error))
        except (UnityMcpError, UnityProjectError) as error:
            return BatchResult(status="failed", detail=str(error))

    # ---- internals --------------------------------------------------------------------------

    def _guarded(self, coroutine) -> UnityResult:
        try:
            return run_sync(coroutine)
        except UnityUnavailable as error:
            return UnityResult(status="unavailable", detail=str(error))
        except (UnityMcpError, UnityProjectError) as error:
            return UnityResult(status="failed", detail=str(error))

    def _client(self) -> UnityMcpClient:
        return UnityMcpClient(self.target, timeout=self.timeout)

    def _project_dir(self) -> Path:
        if not self.project:
            raise UnityUnavailable(
                "UNITY_PROJECT_PATH is not set, so there is nowhere to deliver to"
            )
        return self.project

    async def _apply(self, skeleton: Skeleton) -> UnityResult:
        project = self._project_dir()
        rigs = project / RIGS_DIR
        async with self._client() as unity:
            self.say(f"[unity] connected to {unity.url}")
            await unity.wait_until_ready(self.compile_wait)
            await self._ensure_scripts(unity, project)

            rigs.mkdir(parents=True, exist_ok=True)
            report = rigs / REPORT_FILE
            self._report_mtime_before = report.stat().st_mtime_ns if report.exists() else 0
            (rigs / SKELETON_FILE).write_text(skeleton.model_dump_json(indent=2), encoding="utf-8")
            await unity.clear_console()
            await unity.call_tool("execute_menu_item", {"menu_path": IMPORT_MENU})
            self.say(f"[unity] import triggered for '{skeleton.rig_name}'")
        return UnityResult(status="applied", detail="import triggered")

    async def _ensure_scripts(self, unity: UnityMcpClient, project: Path) -> None:
        if scripts_installed(project):
            return
        result = install_scripts(project)
        self.say(
            f"[unity] installed {len(result.copied)} C# script(s); waiting for Unity to compile"
        )
        await unity.clear_console()
        await unity.call_tool(
            "refresh_unity",
            {"mode": "force", "scope": "all", "compile": "request", "wait_for_ready": True},
        )
        await unity.wait_until_ready(self.compile_wait)
        errors = await unity.console_messages(["error"])
        if errors:
            raise UnityMcpError(f"Unity reported errors after installing the scripts: {errors[:3]}")

    async def _verify(self, skeleton: Skeleton) -> UnityResult:
        project = self._project_dir()
        report_path = project / RIGS_DIR / REPORT_FILE
        report = await self._wait_for_json(report_path, self._report_mtime_before, "import report")
        problems = compare_import(skeleton, report)

        async with self._client() as unity:
            errors = await unity.console_messages(["error"])
            if errors:
                problems.append(f"Unity console errors: {errors[:3]}")
            if problems:
                more = f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""
                self.say(f"[unity] verification FAILED: {len(problems)} problem(s)")
                return UnityResult(status="failed", detail="; ".join(problems[:5]) + more)
            detail = (
                f"{report.get('bone_count')} bones under {OUTPUT_ROOT}/{skeleton.rig_name}, "
                f"max position error {report.get('max_head_error', 0):.1e}"
            )
            self.say(f"[unity] verified: {detail}")

            if self.prefab:
                result = (await self._save_prefabs(unity, project, [skeleton.rig_name]))[0]
                if result["status"] == "failed":
                    return UnityResult(
                        status="failed",
                        detail=f"the rig is verified, but its prefab was not saved: "
                        f"{result.get('message')}",
                    )
                detail += f"; prefab {result['path']} ({result['status']})"
        return UnityResult(status="applied", detail=detail)

    # ---- everything in out/ -----------------------------------------------------------------

    async def _deliver_all(self, rigs: Sequence[BatchRig]) -> BatchResult:
        if not rigs:
            return BatchResult(status="failed", detail="there are no rigs to import")
        project = self._project_dir()
        folder = project / RIGS_DIR
        async with self._client() as unity:
            self.say(f"[unity] connected to {unity.url}")
            await unity.wait_until_ready(self.compile_wait)
            await self._ensure_scripts(unity, project)

            files = []
            (project / BATCH_DIR).mkdir(parents=True, exist_ok=True)
            for rig in rigs:
                (project / BATCH_DIR / f"{rig.name}.json").write_text(
                    rig.skeleton.model_dump_json(indent=2), encoding="utf-8"
                )
                files.append(f"{BATCH_DIR}/{rig.name}.json")
            (folder / BATCH_FILE).write_text(json.dumps({"files": files}), encoding="utf-8")

            report_path = folder / BATCH_REPORT_FILE
            before = report_path.stat().st_mtime_ns if report_path.exists() else 0
            await unity.clear_console()
            await unity.call_tool("execute_menu_item", {"menu_path": IMPORT_ALL_MENU})
            self.say(f"[unity] import of {len(rigs)} rig(s) triggered")
            report = await self._wait_for_json(report_path, before, "batch import report")

            by_name = {r.get("rig_name"): r for r in report.get("rigs") or []}
            outcomes: dict[str, RigOutcome] = {}
            for rig in rigs:
                one = by_name.get(rig.name)
                problems = (
                    compare_import(rig.skeleton, one) if one else ["Unity did not report this rig"]
                )
                more = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
                outcomes[rig.name] = (
                    RigOutcome(rig.name, "failed", "; ".join(problems[:3]) + more)
                    if problems
                    else RigOutcome(rig.name, "applied", f"{len(rig.skeleton.bones)} bones")
                )
                self.say(f"[unity] {rig.name}: {outcomes[rig.name].status}")

            errors = await unity.console_messages(["error"])  # before the prefab step clears it
            if self.prefab:
                await self._prefab_batch(unity, project, rigs, outcomes)
                errors += await unity.console_messages(["error"])

        result = BatchResult(
            status="applied" if all(o.status == "applied" for o in outcomes.values()) else "failed",
            rigs=list(outcomes.values()),
        )
        if errors:
            result.status, result.detail = "failed", f"Unity console errors: {errors[:3]}"
        return result

    async def _prefab_batch(
        self,
        unity: UnityMcpClient,
        project: Path,
        rigs: Sequence[BatchRig],
        outcomes: dict[str, RigOutcome],
    ) -> None:
        """Save prefabs for the rigs that imported cleanly and passed validation."""
        wanted = []
        for rig in rigs:
            if outcomes[rig.name].status != "applied":
                continue
            if rig.passed is True:
                wanted.append(rig.name)
            else:
                why = (
                    "it failed validation" if rig.passed is False else "it has no validation report"
                )
                outcomes[rig.name].detail += f"; no prefab, {why}"
        if not wanted:
            return
        for result in await self._save_prefabs(unity, project, wanted):
            outcome = outcomes[result["rig"]]
            if result["status"] == "failed":
                outcome.status = "failed"
                outcome.detail += f"; prefab not saved: {result.get('message')}"
            else:
                outcome.prefab = result["path"]
                outcome.detail += f"; prefab {result['status']}"

    # ---- prefabs ----------------------------------------------------------------------------

    async def _save_prefabs(
        self, unity: UnityMcpClient, project: Path, names: list[str]
    ) -> list[dict[str, Any]]:
        """Ask Unity to save the named rigs (already in the scene) as prefabs."""
        assert self.prefab is not None
        folder = project / RIGS_DIR
        request = {"folder": self.prefab.folder, "overwrite": self.prefab.overwrite, "rigs": names}
        (folder / PREFAB_FILE).write_text(json.dumps(request), encoding="utf-8")
        report_path = folder / PREFAB_REPORT_FILE
        before = report_path.stat().st_mtime_ns if report_path.exists() else 0
        await unity.clear_console()
        await unity.call_tool("execute_menu_item", {"menu_path": SAVE_PREFABS_MENU})
        self.say(f"[unity] saving {len(names)} prefab(s) to {self.prefab.folder}")
        report = await self._wait_for_json(report_path, before, "prefab report")

        results = {r.get("rig"): r for r in report.get("results") or []}
        out = []
        for name in names:
            result = results.get(name) or {"rig": name, "status": "failed"}
            if result["status"] == "failed" and not result.get("message"):
                result["message"] = "Unity did not report this rig" + (
                    "; " + "; ".join(report.get("errors") or []) if report.get("errors") else ""
                )
            self.say(f"[unity] prefab {name}: {result['status']}")
            out.append(result)
        return out

    async def _wait_for_json(self, path: Path, before: int, what: str) -> dict[str, Any]:
        """Wait until Unity has written this file anew (newer than `before`), then read it."""
        deadline = time.monotonic() + self.report_wait
        while True:
            if path.exists() and path.stat().st_mtime_ns > before:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass  # Unity is still writing it
            if time.monotonic() >= deadline:
                raise UnityMcpError(
                    f"Unity wrote no {what} within {self.report_wait:.0f}s. Check the "
                    f"Unity console for lines starting with {IMPORT_LOG_TAG}."
                )
            await asyncio.sleep(0.2)
