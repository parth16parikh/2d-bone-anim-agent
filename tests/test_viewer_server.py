import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from layout_helpers import good_skeleton
from rig_agent.viewer_server import create_server, list_rigs


def make_rig(out, folder, view="front", rest_pose="A_pose", **kw):
    skeleton = good_skeleton(view=view, rest_pose=rest_pose, **kw)
    target = out / folder
    target.mkdir(parents=True)
    (target / "skeleton.json").write_text(skeleton.model_dump_json())
    return target


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "out"
    make_rig(folder, "knight")
    make_rig(folder, "runner", view="side", rest_pose="side_neutral")
    return folder


@pytest.fixture
def server(out, tmp_path):
    viewer = tmp_path / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text("<html>viewer</html>")
    (tmp_path / ".env").write_text("SECRET=1")
    srv = create_server(out, 0, viewer_dir=viewer)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as res:
        return res.status, res.read(), res.headers


def status_of(url):
    try:
        return get(url)[0]
    except urllib.error.HTTPError as error:
        return error.code


def test_rigs_are_listed_with_their_details(out):
    rigs = {r["name"]: r for r in list_rigs(out)}
    assert set(rigs) == {"knight", "runner"}
    assert rigs["runner"]["view"] == "side" and rigs["runner"]["bones"] >= 14
    assert rigs["knight"]["path"] == "/out/knight/skeleton.json"
    assert rigs["knight"]["report"] is None and rigs["knight"]["passed"] is None


def test_the_report_status_is_included_when_there_is_one(out):
    (out / "knight" / "validation_report.json").write_text(json.dumps({"passed": False}))
    rigs = {r["name"]: r for r in list_rigs(out)}
    assert rigs["knight"]["passed"] is False
    assert rigs["knight"]["report"] == "/out/knight/validation_report.json"


def test_folders_without_a_valid_skeleton_are_skipped(out):
    (out / "empty").mkdir()
    broken = out / "broken"
    broken.mkdir()
    (broken / "skeleton.json").write_text("{not json")
    (out / "other").mkdir()
    (out / "other" / "skeleton.json").write_text('{"no": "bones"}')
    assert {r["name"] for r in list_rigs(out)} == {"knight", "runner"}


def test_a_missing_out_folder_lists_nothing(tmp_path):
    assert list_rigs(tmp_path / "nope") == []


def test_newest_rig_comes_first(out):
    os.utime(out / "knight" / "skeleton.json", (1_000_000, 1_000_000))
    assert list_rigs(out)[0]["name"] == "runner"


def test_a_skeleton_directly_in_out_is_listed(out):
    (out / "skeleton.json").write_text((out / "knight" / "skeleton.json").read_text())
    assert "(out)" in {r["name"] for r in list_rigs(out)}


def test_the_api_returns_the_list(server):
    status, body, headers = get(server + "/api/rigs")
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert {r["name"] for r in json.loads(body)["rigs"]} == {"knight", "runner"}


def test_the_root_goes_to_the_viewer(server):
    status, body, _ = get(server + "/")
    assert status == 200 and b"viewer" in body


def test_rig_files_are_served(server):
    status, body, headers = get(server + "/out/knight/skeleton.json")
    assert status == 200 and json.loads(body)["bones"]
    assert headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/viewer/../.env",
        "/out/../.env",
        "/out/%2e%2e/.env",
        "/%2e%2e/.env",
        "/src/rig_agent/cli.py",
        "/out/..%2f..%2f.env",
        "/nothing",
    ],
)
def test_nothing_outside_viewer_and_out_is_served(server, path):
    assert status_of(server + path) == 404


def test_the_server_only_listens_on_localhost(server):
    assert server.startswith("http://127.0.0.1:")


def test_a_rig_lists_its_animation_clips_with_their_status(out):
    clips = out / "runner" / "animations"
    clips.mkdir()
    (clips / "walk.json").write_text(
        json.dumps({"clip": "walk", "rotations": {}, "frame_count": 2})
    )
    (clips / "walk.report.json").write_text(json.dumps({"issues": [], "passed": True}))
    (clips / "draft.json").write_text(
        json.dumps({"clip": "run", "rotations": {}, "frame_count": 2})
    )
    (clips / "notes.json").write_text(json.dumps({"hello": "world"}))  # not a clip: skipped
    runner = next(r for r in list_rigs(out) if r["name"] == "runner")
    assert runner["animations"] == [
        {
            "name": "draft",
            "clip": "run",
            "path": "/out/runner/animations/draft.json",
            "report": None,
            "passed": None,
        },
        {
            "name": "walk",
            "clip": "walk",
            "path": "/out/runner/animations/walk.json",
            "report": "/out/runner/animations/walk.report.json",
            "passed": True,
        },
    ]
    knight = next(r for r in list_rigs(out) if r["name"] == "knight")
    assert knight["animations"] == []
