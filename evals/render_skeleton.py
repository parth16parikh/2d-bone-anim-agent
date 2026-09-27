"""Offline skeleton renderer for the eval harness (LLD 4.3, Phase H2).

Draws a saved skeleton.json -- plus its validation_report.json when one sits next to it -- to a PNG
for human review and the vision judge. Not part of the agent: never called at runtime, needs no
model and no Unity. The picture follows the browser viewer (viewer/viewer.js) so a PNG and the
viewer look alike: diamond bones from pivot to tip, joint dots, dashed links where a bone does not
start on its parent's tail, a red ring on every bone the report names, bones drawn back to front.

    uv run python -m evals.render_skeleton out/knight out/elf      # writes out/<rig>/skeleton.png
    uv run python -m evals.render_skeleton --all out --dest renders --color depth
"""

from __future__ import annotations

import argparse
import colorsys
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from rig_agent.export.json_exporter import (
    RENDER_FILE,
    REPORT_FILE,
    SKELETON_FILE,
    load_report,
    load_skeleton,
)
from rig_agent.schemas.skeleton import Bone, Skeleton
from rig_agent.schemas.validation import ValidationReport

ColorMode = Literal["side", "depth", "ik"]
COLOR_MODES: tuple[ColorMode, ...] = ("side", "depth", "ik")

RGB = tuple[int, int, int]
Pt = tuple[float, float]
Px = Callable[[float], int]  # a logical size to image pixels


def _hex(code: str) -> RGB:
    return (int(code[1:3], 16), int(code[3:5], 16), int(code[5:7], 16))


# the viewer's light theme (viewer/index.html)
THEME: dict[str, RGB] = {
    name: _hex(code)
    for name, code in {
        "stage": "#fbfcfd",
        "panel": "#ffffff",
        "line": "#dde1e8",
        "grid": "#e7eaf0",
        "ground": "#8a93a5",
        "ink": "#1d2330",
        "muted": "#667085",
        "left": "#2f6fed",
        "right": "#e8590c",
        "center": "#2b8a3e",
        "extra": "#9c36b5",
        "none": "#8a93a5",
        "bad": "#e03131",
        "good": "#2b8a3e",
    }.items()
}
IK_COLORS: dict[str, RGB] = {
    "arm_L": _hex("#1c7ed6"),
    "arm_R": _hex("#e8590c"),
    "leg_L": _hex("#0ca678"),
    "leg_R": _hex("#ae3ec9"),
}

EXTRA_PREFIX = "extra_"
LINK_TOLERANCE = 0.005  # fraction of the height, as in the validator and the viewer
GRID_STEPS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
HEADER, FOOTER, PAD = 76, 30, 36  # logical pixels
SUPERSAMPLE = 2  # drawn at 2x and scaled down: Pillow's own lines are not anti-aliased
MIN_SIZE = 240


@dataclass(frozen=True)
class RenderOptions:
    size: int = 800  # the PNG is size x size
    labels: bool = True
    color: ColorMode = "side"


# ---- bone helpers (same rules as viewer.js) --------------------------------------------------


def kind_of(name: str) -> str:
    """left, right, center or extra: what the side colouring follows."""
    if name.startswith(EXTRA_PREFIX):
        return "extra"
    if name.endswith("_L"):
        return "left"
    if name.endswith("_R"):
        return "right"
    return "center"


def draw_key(bone: Bone) -> float:
    """Back-to-front key: depth, shifted by an extra bone's layer as the Unity importer does."""
    shift = {"behind": -0.5, "front": 0.5}.get(bone.layer or "", 0.0)
    return bone.depth + shift


def bone_shape(bone: Bone, height: float) -> list[Pt]:
    """The bone as a diamond from pivot to tip, in world coordinates."""
    (hx, hy), (tx, ty) = bone.world_head, bone.world_tail
    dx, dy = tx - hx, ty - hy
    length = math.hypot(dx, dy) or 1e-9
    nx, ny = -dy / length, dx / length
    w = min(max(0.18 * length, 0.006 * height), 0.045 * height)
    mx, my = hx + dx * 0.18, hy + dy * 0.18
    return [(hx, hy), (mx + nx * w, my + ny * w), (tx, ty), (mx - nx * w, my - ny * w)]


def link_gaps(skeleton: Skeleton) -> list[tuple[Pt, Pt]]:
    """(parent tail, child head) for every bone that does not start on its parent's tail."""
    by_id = {b.id: b for b in skeleton.bones}
    eps = LINK_TOLERANCE * skeleton.height
    gaps = []
    for bone in skeleton.bones:
        parent = by_id.get(bone.parent_id)
        if parent is not None and math.dist(bone.world_head, parent.world_tail) > eps:
            gaps.append((parent.world_tail, bone.world_head))
    return gaps


def reported_bones(report: ValidationReport | None, skeleton: Skeleton) -> set[str]:
    """Bone names the report points at. A spec name such as extra_horn also covers the built
    bones extra_horn_L, extra_horn_1 ... (as in the viewer)."""
    names: set[str] = set()
    if report is None:
        return names
    built = [b.name for b in skeleton.bones]
    for issue in report.issues:
        for name in issue.bones:
            names.add(name)
            names.update(
                x for x in built if x.startswith(EXTRA_PREFIX) and x.startswith(name + "_")
            )
    return names


def _hsl(hue: float, sat: float, light: float) -> RGB:
    r, g, b = colorsys.hls_to_rgb(hue / 360, light, sat)
    return (round(r * 255), round(g * 255), round(b * 255))


def color_for(bone: Bone, mode: ColorMode, depth_min: int, depth_max: int) -> RGB:
    if mode == "depth":
        d = bone.depth
        if d == 0:
            return THEME["center"]
        if d > 0:
            return _hsl(24, 0.90, (58 - 14 * d / max(depth_max, 1)) / 100)
        return _hsl(214, 0.80, (62 - 14 * d / min(depth_min, -1)) / 100)
    if mode == "ik":
        return IK_COLORS.get(bone.ik_chain or "", THEME["none"])
    return THEME[kind_of(bone.name)]


# ---- drawing ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _View:
    """World (Unity units, Y up) to image pixels (Y down), fitted into one stage rectangle."""

    cx: float
    cy: float
    zoom: float  # image pixels per world unit
    mid_x: float
    mid_y: float

    def x(self, wx: float) -> float:
        return self.mid_x + (wx - self.cx) * self.zoom

    def y(self, wy: float) -> float:
        return self.mid_y - (wy - self.cy) * self.zoom

    def p(self, point: Sequence[float]) -> Pt:
        return (self.x(point[0]), self.y(point[1]))


def fit_view(skeleton: Skeleton, box: tuple[float, float, float, float], pad: float) -> _View:
    """Fit the rig, the origin and the height line into box = (left, top, right, bottom)."""
    xs = [0.0] + [c for b in skeleton.bones for c in (b.world_head[0], b.world_tail[0])]
    ys = [0.0, skeleton.height] + [
        c for b in skeleton.bones for c in (b.world_head[1], b.world_tail[1])
    ]
    width, height = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
    left, top, right, bottom = box
    zoom = min((right - left - 2 * pad) / width, (bottom - top - 2 * pad) / height)
    return _View(
        cx=(min(xs) + max(xs)) / 2,
        cy=(min(ys) + max(ys)) / 2,
        zoom=zoom,
        mid_x=(left + right) / 2,
        mid_y=(top + bottom) / 2,
    )


def grid_step(zoom: float) -> float:
    """The smallest step that keeps grid lines at least 56 logical pixels apart."""
    return next((s for s in GRID_STEPS if s * zoom >= 56), GRID_STEPS[-1])


@lru_cache(maxsize=16)
def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=px)


def _dashed(
    draw: ImageDraw.ImageDraw, a: Pt, b: Pt, fill: RGB, width: int, dash: float, gap: float
) -> None:
    length = math.dist(a, b)
    if length == 0:
        return
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    t = 0.0
    while t < length:
        end = min(t + dash, length)
        draw.line(
            [(a[0] + ux * t, a[1] + uy * t), (a[0] + ux * end, a[1] + uy * end)],
            fill=fill,
            width=width,
        )
        t += dash + gap


def _fit_text(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: float
) -> str:
    if font.getlength(text) <= max_width:
        return text
    while text and font.getlength(text + "...") > max_width:
        text = text[:-1]
    return text + "..."


def render(
    skeleton: Skeleton, report: ValidationReport | None = None, options: RenderOptions | None = None
) -> Image.Image:
    """The whole picture: a header (name, pass/fail, prompt), the rig on a grid, and a legend."""
    o = options or RenderOptions()
    if o.size < MIN_SIZE:
        raise ValueError(f"size must be at least {MIN_SIZE} pixels, got {o.size}")
    s = SUPERSAMPLE
    w = h = o.size * s

    def px(n: float) -> int:  # a logical line width or font size, in image pixels
        return max(1, round(n * s))

    img = Image.new("RGB", (w, h), THEME["stage"])
    draw = ImageDraw.Draw(img, "RGBA")
    stage_top, stage_bottom = HEADER * s, h - FOOTER * s
    view = fit_view(skeleton, (0, stage_top, w, stage_bottom), PAD * s)
    H = skeleton.height

    # grid, ground, origin axis, height line
    tick = _font(px(10))
    step = grid_step(view.zoom / s)
    for k in range(
        math.floor((view.cx - w / 2 / view.zoom) / step),
        math.ceil((view.cx + w / 2 / view.zoom) / step) + 1,
    ):
        x = view.x(k * step)
        draw.line([(x, stage_top), (x, stage_bottom)], fill=THEME["grid"], width=px(1))
        text = f"{k * step:g}"
        # x ticks sit along the bottom; skip the left corner (the y ticks) and any cut off at the edge
        if x > px(40) and x + px(3) + tick.getlength(text) < w:
            draw.text(
                (x + px(3), stage_bottom - px(6)), text, font=tick, fill=THEME["muted"], anchor="ls"
            )
    half = (stage_bottom - stage_top) / 2 / view.zoom
    for k in range(math.floor((view.cy - half) / step), math.ceil((view.cy + half) / step) + 1):
        y = view.y(k * step)
        if stage_top <= y <= stage_bottom:
            draw.line([(0, y), (w, y)], fill=THEME["grid"], width=px(1))
            if (
                stage_top + px(12) < y < stage_bottom - px(18)
            ):  # clear of the header and the x ticks
                draw.text(
                    (px(6), y - px(3)), f"{k * step:g}", font=tick, fill=THEME["muted"], anchor="ls"
                )
    draw.line([(0, view.y(0)), (w, view.y(0))], fill=THEME["ground"], width=px(2.5))
    draw.line(
        [(view.x(0), stage_top), (view.x(0), stage_bottom)], fill=THEME["grid"], width=px(1.5)
    )
    _dashed(draw, (0, view.y(H)), (w, view.y(H)), THEME["muted"], px(1), 6 * s, 5 * s)
    draw.text(
        (w - px(8), view.y(H) - px(4)), f"height {H:g}", font=tick, fill=THEME["muted"], anchor="rs"
    )

    for a, b in link_gaps(skeleton):
        _dashed(draw, view.p(a), view.p(b), THEME["muted"], px(1.3), 3 * s, 3 * s)

    bones = sorted(skeleton.bones, key=lambda b: (draw_key(b), b.id))
    bad = reported_bones(report, skeleton)
    depths = [b.depth for b in skeleton.bones]
    for bone in bones:
        color = color_for(bone, o.color, min(depths), max(depths))
        points = [view.p(p) for p in bone_shape(bone, H)]
        draw.polygon(points, fill=(*color, 140), outline=color, width=px(1.6))
    for bone in bones:
        r = px(2.3 if kind_of(bone.name) == "extra" else 3.2)
        cx, cy = view.p(bone.world_head)
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=THEME["panel"],
            outline=THEME["ink"],
            width=px(1.2),
        )
    for bone in bones:
        if bone.name in bad:
            mx, my = view.p(
                (
                    (bone.world_head[0] + bone.world_tail[0]) / 2,
                    (bone.world_head[1] + bone.world_tail[1]) / 2,
                )
            )
            r = px(14)
            draw.ellipse([mx - r, my - r, mx + r, my + r], outline=THEME["bad"], width=px(2.5))

    if o.labels:
        label = _font(px(11))
        for bone in bones:
            kind = kind_of(bone.name)
            natural = "start" if bone.world_tail[0] - bone.world_head[0] >= 0 else "end"
            # left labels go right and right labels go left, so a near and a far limb do not collide
            # in the side view; extras go opposite their own direction, clear of the spine labels
            anchor = {"left": "start", "right": "end"}.get(kind) or (
                ("end" if natural == "start" else "start") if kind == "extra" else natural
            )
            tx, ty = view.p(bone.world_tail)
            draw.text(
                (tx + (px(5) if anchor == "start" else -px(5)), ty),
                bone.name,
                font=label,
                fill=THEME["ink"],
                anchor="lm" if anchor == "start" else "rm",
                stroke_width=px(1.5),
                stroke_fill=THEME["stage"],
            )

    _header(draw, skeleton, report, w, px)
    _footer(draw, o.color, bool(bad), w, h, px)
    return img.resize((o.size, o.size), Image.Resampling.LANCZOS)


def _header(
    draw: ImageDraw.ImageDraw, skeleton: Skeleton, report: ValidationReport | None, w: int, px: Px
) -> None:
    bottom = HEADER * SUPERSAMPLE
    draw.rectangle([0, 0, w, bottom], fill=THEME["panel"])
    draw.line([(0, bottom), (w, bottom)], fill=THEME["line"], width=px(1))
    title, small = _font(px(16)), _font(px(12))
    if report is None:
        verdict, color = "no validation report", THEME["muted"]
    elif report.passed:
        verdict = "PASSED" + (f" - {len(report.warnings)} warning(s)" if report.warnings else "")
        color = THEME["good"]
    else:
        verdict, color = f"FAILED - {len(report.errors)} error(s)", THEME["bad"]
    right = w - px(16)
    draw.text((right, px(14)), verdict, font=small, fill=color, anchor="ra")
    room = right - small.getlength(verdict) - px(32)
    draw.text(
        (px(16), px(12)), _fit_text(skeleton.rig_name, title, room), font=title, fill=THEME["ink"]
    )
    facts = f"{skeleton.view} view - {skeleton.rest_pose} - {len(skeleton.bones)} bones - height {skeleton.height:g} - {skeleton.style}"
    draw.text(
        (px(16), px(36)), _fit_text(facts, small, w - px(32)), font=small, fill=THEME["muted"]
    )
    prompt = f'"{skeleton.source_prompt}"'
    draw.text((px(16), px(54)), _fit_text(prompt, small, w - px(32)), font=small, fill=THEME["ink"])


def _footer(
    draw: ImageDraw.ImageDraw, mode: ColorMode, has_issues: bool, w: int, h: int, px: Px
) -> None:
    top = h - FOOTER * SUPERSAMPLE
    draw.rectangle([0, top, w, h], fill=THEME["panel"])
    draw.line([(0, top), (w, top)], fill=THEME["line"], width=px(1))
    entries: list[tuple[RGB, str]] = {
        "side": [
            (THEME["left"], "left"),
            (THEME["right"], "right"),
            (THEME["center"], "center"),
            (THEME["extra"], "extra"),
        ],
        "depth": [
            (_hsl(214, 0.80, 0.55), "behind"),
            (THEME["center"], "torso plane"),
            (_hsl(24, 0.90, 0.51), "in front"),
        ],
        "ik": [*((c, n) for n, c in IK_COLORS.items()), (THEME["none"], "no IK")],
    }[mode]
    font = _font(px(11))
    x, mid = float(px(16)), top + (h - top) / 2
    for color, text in entries:
        box = px(9)
        draw.rectangle([x, mid - box / 2, x + box, mid + box / 2], fill=color)
        x += box + px(5)
        draw.text((x, mid), text, font=font, fill=THEME["muted"], anchor="lm")
        x += font.getlength(text) + px(14)
    note = "dashed = offset from the parent's tail" + (
        "; red ring = reported issue" if has_issues else ""
    )
    draw.text((w - px(16), mid), note, font=font, fill=THEME["muted"], anchor="rm")


# ---- files and command line ------------------------------------------------------------------


def render_folder(
    folder: str | Path, dest: str | Path | None = None, options: RenderOptions | None = None
) -> Path:
    """Render one rig folder. Writes <folder>/skeleton.png, or <dest>/<folder name>.png."""
    directory = Path(folder)
    skeleton = load_skeleton(directory / SKELETON_FILE)
    report_path = directory / REPORT_FILE
    report = load_report(report_path) if report_path.is_file() else None
    target = Path(dest) / f"{directory.resolve().name}.png" if dest else directory / RENDER_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    render(skeleton, report, options).save(target)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.render_skeleton",
        description="Draw saved rigs (skeleton.json) to PNG for review and the vision judge.",
    )
    parser.add_argument("folders", nargs="*", help="rig folders, each holding a skeleton.json")
    parser.add_argument("--all", metavar="OUT_DIR", help="render every rig folder inside OUT_DIR")
    parser.add_argument(
        "--dest", metavar="DIR", help="write <DIR>/<rig>.png instead of into each rig folder"
    )
    parser.add_argument(
        "--size", type=int, default=RenderOptions.size, help="image width and height (default 800)"
    )
    parser.add_argument(
        "--color",
        choices=COLOR_MODES,
        default="side",
        help="colour bones by side, depth or IK chain",
    )
    parser.add_argument("--no-labels", action="store_true", help="leave bone names off")
    args = parser.parse_args(argv)

    folders = [Path(f) for f in args.folders]
    if args.all:
        root = Path(args.all)
        if not root.is_dir():
            parser.error(f"'{root}' is not a folder")
        folders += sorted(d for d in root.iterdir() if (d / SKELETON_FILE).is_file())
    if not folders:
        parser.error("give one or more rig folders, or --all OUT_DIR with rigs in it")
    if args.size < MIN_SIZE:
        parser.error(f"--size must be at least {MIN_SIZE}")

    options = RenderOptions(size=args.size, labels=not args.no_labels, color=args.color)
    failed = 0
    for folder in folders:
        try:
            print(render_folder(folder, args.dest, options))
        except (OSError, ValueError) as exc:  # missing/unreadable file, or not a valid skeleton
            print(f"skipped {folder}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
