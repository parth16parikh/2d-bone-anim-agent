from typing import get_args

import pytest

from rig_agent.vocabulary.presets import BANDS, PRESETS, Preset


def test_four_presets_and_the_literal_matches():
    assert set(PRESETS) == {"realistic", "heroic", "stylized", "chibi"}
    assert set(get_args(Preset)) == set(PRESETS)


def test_lld_values_for_realistic_and_chibi():
    r, c = PRESETS["realistic"], PRESETS["chibi"]
    assert (r.heads_tall, r.shoulder_width_hu, r.hip_spacing_hu) == (7.5, 2.0, 0.9)
    assert (r.leg_ratio, r.arm_ratio, r.ankle_ratio) == (0.47, 0.44, 0.04)
    assert (c.heads_tall, c.leg_ratio, c.arm_ratio, c.ankle_ratio) == (3.0, 0.30, 0.30, 0.05)
    assert c.torso_split == (0.20, 0.30, 0.50)


@pytest.mark.parametrize("preset", PRESETS.values(), ids=list(PRESETS))
def test_splits_sum_to_one(preset):
    assert sum(preset.arm_split) == pytest.approx(1.0)
    assert sum(preset.torso_split) == pytest.approx(1.0)


@pytest.mark.parametrize("preset", PRESETS.values(), ids=list(PRESETS))
def test_every_preset_value_is_inside_its_band(preset):
    upper, forearm, hand = preset.arm_split
    values = {
        "heads_tall": preset.heads_tall,
        "shoulder_width_hu": preset.shoulder_width_hu,
        "hip_spacing_hu": preset.hip_spacing_hu,
        "leg_ratio": preset.leg_ratio,
        "arm_ratio": preset.arm_ratio,
        "thigh_share": preset.thigh_share,
        "upper_arm_share": upper / (upper + forearm),
        "hand_share": hand,
        "foot_length_hu": preset.foot_length_hu,
        "neck_hu": preset.neck_hu,
        "chest_share": preset.torso_split[2],
    }
    assert set(values) == set(BANDS)
    for name, value in values.items():
        low, high = BANDS[name]
        assert low <= value <= high, name


def test_bands_are_ordered():
    assert all(low < high for low, high in BANDS.values())


@pytest.mark.parametrize("preset", PRESETS.values(), ids=list(PRESETS))
def test_column_leaves_room_for_a_torso(preset):
    head_unit = 1 / preset.heads_tall
    torso = 1 - preset.leg_ratio - (preset.neck_hu + 1) * head_unit
    assert torso > 0
