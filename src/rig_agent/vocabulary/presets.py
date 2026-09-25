"""Preset proportions (LLD 2.4.1, 2.4.2) and the plausibility bands (LLD 2.4.4)."""

from dataclasses import dataclass
from typing import Literal

Preset = Literal["realistic", "heroic", "stylized", "chibi"]


@dataclass(frozen=True)
class PresetDef:
    name: Preset
    heads_tall: float
    shoulder_width_hu: float
    hip_spacing_hu: float
    leg_ratio: float  # hip joint to ground, fraction of H
    arm_ratio: float  # shoulder joint to fingertips, fraction of H
    ankle_ratio: float  # ankle height, fraction of H
    thigh_share: float  # share of (thigh + shin)
    arm_split: tuple[float, float, float]  # upper arm, forearm, hand: shares of the arm
    foot_length_hu: float
    neck_hu: float
    torso_split: tuple[float, float, float]  # hip, spine, chest: shares of the torso


PRESETS: dict[str, PresetDef] = {
    p.name: p
    for p in (
        PresetDef(
            "realistic", 7.5, 2.0, 0.9, 0.47, 0.44, 0.04,
            0.50, (0.43, 0.36, 0.21), 1.0, 0.30, (0.20, 0.35, 0.45),
        ),
        PresetDef(
            "heroic", 8.0, 2.3, 0.9, 0.50, 0.45, 0.04,
            0.50, (0.43, 0.35, 0.22), 1.1, 0.35, (0.20, 0.35, 0.45),
        ),
        PresetDef(
            "stylized", 6.0, 1.8, 0.8, 0.42, 0.40, 0.04,
            0.48, (0.42, 0.35, 0.23), 1.0, 0.20, (0.20, 0.35, 0.45),
        ),
        PresetDef(
            "chibi", 3.0, 1.2, 0.6, 0.30, 0.30, 0.05,
            0.45, (0.38, 0.34, 0.28), 0.9, 0.10, (0.20, 0.30, 0.50),
        ),
    )
}  # fmt: skip

SPINE_2_TAKE = 0.25  # share of the spine and of the chest that spine_2 takes (LLD 2.4.2)

# Inclusive (low, high) bands. The first five are also the bounds on RigSpec.base.
BANDS: dict[str, tuple[float, float]] = {
    "heads_tall": (2.0, 10.0),
    "shoulder_width_hu": (0.8, 3.0),
    "hip_spacing_hu": (0.4, 1.5),
    "leg_ratio": (0.25, 0.60),
    "arm_ratio": (0.25, 0.55),
    "thigh_share": (0.25, 0.70),  # of (thigh + shin)
    "upper_arm_share": (0.33, 0.70),  # of (upper arm + forearm)
    "hand_share": (0.10, 0.45),  # of the arm
    "foot_length_hu": (0.4, 1.7),
    "neck_hu": (0.05, 0.8),
    "chest_share": (0.30, 0.65),  # of the torso
}
