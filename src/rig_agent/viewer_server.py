"""A small local server for the rig viewer.

It serves only the viewer/ folder and your out/ folder (nothing else in the project, so .env and
the source stay private), plus /api/rigs, a list of every rig found in out/ and the animation
clips baked for it, which the viewer shows as pickers. It listens on 127.0.0.1 only.
"""

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VIEWER_DIR = PROJECT_ROOT / "viewer"
SKELETON_FILE = "skeleton.json"
REPORT_FILE = "validation_report.json"
ANIMATIONS_DIR = "animations"
CLIP_REPORT_SUFFIX = ".report.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_clips(folder: Path, prefix: str) -> list[dict[str, Any]]:
    """The animation clips baked for one rig (its animations/ folder), by name."""
    directory = folder / ANIMATIONS_DIR
    if not directory.is_dir():
        return []
    clips = []
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(CLIP_REPORT_SUFFIX):
            continue
        data = _read_json(path)
        if data is None or not isinstance(data.get("rotations"), dict):
            continue
        report_path = path.with_name(path.stem + CLIP_REPORT_SUFFIX)
        report = _read_json(report_path) if report_path.is_file() else None
        url = f"{prefix}/{ANIMATIONS_DIR}"
        clips.append(
            {
                "name": path.stem,
                "clip": data.get("clip", ""),
                "path": f"{url}/{path.name}",
                "report": f"{url}/{report_path.name}" if report else None,
                "passed": report.get("passed") if report else None,
            }
        )
    return clips


def list_rigs(out_dir: Path) -> list[dict[str, Any]]:
    """Every rig in out_dir (one folder each, or a skeleton.json directly inside), newest first."""
    rigs = []
    folders = [p for p in sorted(out_dir.iterdir()) if p.is_dir()] if out_dir.is_dir() else []
    for folder in [out_dir, *folders]:
        skeleton_path = folder / SKELETON_FILE
        if not skeleton_path.is_file():
            continue
        data = _read_json(skeleton_path)
        if data is None or not isinstance(data.get("bones"), list):
            continue
        report_path = folder / REPORT_FILE
        report = _read_json(report_path) if report_path.is_file() else None
        prefix = "/out" if folder == out_dir else f"/out/{folder.name}"
        rigs.append(
            {
                "name": folder.name if folder != out_dir else "(out)",
                "rig_name": data.get("rig_name", ""),
                "view": data.get("view", ""),
                "bones": len(data["bones"]),
                "modified": skeleton_path.stat().st_mtime,
                "passed": report.get("passed") if report else None,
                "path": f"{prefix}/{SKELETON_FILE}",
                "report": f"{prefix}/{REPORT_FILE}" if report else None,
                "animations": list_clips(folder, prefix),
            }
        )
    return sorted(rigs, key=lambda r: r["modified"], reverse=True)


class ViewerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, viewer_dir: Path, out_dir: Path, **kwargs: Any):
        self.viewer_dir = viewer_dir.resolve()
        self.out_dir = out_dir.resolve()
        super().__init__(*args, directory=str(viewer_dir), **kwargs)

    def translate_path(self, path: str) -> str:
        """Map a URL to a file inside viewer/ or out/, or to a path that does not exist."""
        dead_end = str(self.viewer_dir / ".does-not-exist")
        parts = [unquote(p) for p in urlparse(path).path.split("/") if p]
        if not parts or any(p in (".", "..") or p.startswith(".") or "\\" in p for p in parts):
            return dead_end
        base = {"viewer": self.viewer_dir, "out": self.out_dir}.get(parts[0])
        if base is None:
            return dead_end
        target = base.joinpath(*parts[1:])
        try:
            if not target.resolve().is_relative_to(base):
                return dead_end
        except OSError:
            return dead_end
        return str(target)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_response(302)
            self.send_header("Location", "/viewer/index.html")
            self.end_headers()
            return
        if path == "/api/rigs":
            body = json.dumps({"root": "/out/", "rigs": list_rigs(self.out_dir)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")  # the viewer polls files that change
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def create_server(
    out_dir: str | Path = "out",
    port: int = 8000,
    viewer_dir: Path = VIEWER_DIR,
    host: str = "127.0.0.1",
) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1. Use port 0 to let the system pick a free one."""
    handler = partial(ViewerHandler, viewer_dir=viewer_dir, out_dir=Path(out_dir))
    return ThreadingHTTPServer((host, port), handler)
