import itertools

import pytest

from rig_agent.builder.errors import BuildError
from rig_agent.builder.proportions import resolve_proportions
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.vocabulary.bones import OPTIONAL_TOKENS, token_views
from rig_agent.vocabulary.presets import BANDS, PRESETS


def spec(**kw):
    data = {"character_summary": "c", "style": "s", "view": "front", "rest_pose": "A_pose"}
    data.update(kw)
    return RigSpec.model_validate(data)


def column(p):
    return p.leg_length + p.torso_length + p.neck + p.head


def test_realistic_defaults_with_every_bone():
    p = resolve_proportions(spec(optional_bones=["chest", "neck", "hands"]))
    hu = 2.0 / 7.5
    assert p.head_unit == pytest.approx(hu)
    assert p.leg_length == pytest.approx(0.47 * 2.0)
    assert p.head == pytest.approx(hu) and p.neck == pytest.approx(0.30 * hu)
    assert p.torso_length == pytest.approx(2.0 - 0.94 - 0.30 * hu - hu)
    assert (p.hip, p.spine, p.chest) == pytest.approx(
        (0.20 * p.torso_length, 0.35 * p.torso_length, 0.45 * p.torso_length)
    )
    assert p.spine_2 == 0
    assert p.arm_length == pytest.approx(0.44 * 2.0)
    assert (p.upper_arm, p.forearm, p.hand) == pytest.approx(
        (0.43 * p.arm_length, 0.36 * p.arm_length, 0.21 * p.arm_length)
    )
    assert p.ankle_height == pytest.approx(0.08)
    assert p.thigh == pytest.approx(p.shin) and p.thigh + p.shin == pytest.approx(0.94 - 0.08)
    assert p.foot == pytest.approx(1.0 * hu)
    assert p.shoulder_width == pytest.approx(2.0 * hu) and p.hip_spacing == pytest.approx(0.9 * hu)
    assert p.root == pytest.approx(0.05)


@pytest.mark.parametrize("preset", list(PRESETS))
@pytest.mark.parametrize("height", [1.0, 2.0, 5.0])
def test_column_always_sums_to_the_height(preset, height):
    p = resolve_proportions(spec(preset=preset, height_units=height))
    assert column(p) == pytest.approx(height)


def test_overrides_change_proportions_not_the_height():
    plain = resolve_proportions(spec())
    lanky = resolve_proportions(
        spec(overrides={"leg_scale": 1.15, "arm_scale": 1.15, "torso_scale": 0.95})
    )
    assert column(lanky) == pytest.approx(2.0)
    assert lanky.leg_length > plain.leg_length
    assert lanky.torso_length < plain.torso_length
    assert lanky.arm_length == pytest.approx(0.44 * 2.0 * 1.15)


def test_head_scale_enlarges_the_head_and_keeps_the_height():
    p = resolve_proportions(spec(overrides={"head_scale": 1.5}))
    assert p.head_only > resolve_proportions(spec()).head_only
    assert column(p) == pytest.approx(2.0)


def test_base_values_replace_the_preset():
    p = resolve_proportions(spec(base={"heads_tall": 9, "leg_ratio": 0.5, "arm_ratio": 0.4}))
    assert p.head_unit == pytest.approx(2.0 / 9)
    assert p.leg_length == pytest.approx(1.0)
    assert p.arm_length == pytest.approx(0.8)
    assert column(p) == pytest.approx(2.0)


def test_chibi_is_short_legged_and_big_headed():
    chibi, real = resolve_proportions(spec(preset="chibi")), resolve_proportions(spec())
    assert chibi.leg_length / 2 < real.leg_length / 2
    assert chibi.head_only > real.head_only


def test_thigh_shin_bias_direction():
    longer_thigh = resolve_proportions(spec(overrides={"thigh_shin_bias": 1.3}))
    longer_shin = resolve_proportions(spec(overrides={"thigh_shin_bias": 0.7}))
    assert longer_thigh.thigh > longer_thigh.shin
    assert longer_shin.shin > longer_shin.thigh
    assert longer_thigh.thigh + longer_thigh.shin == pytest.approx(
        longer_shin.thigh + longer_shin.shin
    )


def test_upper_forearm_bias_keeps_the_arm_length():
    a = resolve_proportions(spec(optional_bones=["hands"], overrides={"upper_forearm_bias": 1.3}))
    b = resolve_proportions(spec(optional_bones=["hands"], overrides={"upper_forearm_bias": 0.7}))
    assert a.upper_arm > b.upper_arm and a.forearm < b.forearm
    for p in (a, b):
        assert p.upper_arm + p.forearm + p.hand == pytest.approx(p.arm_length)


def test_hand_size_grows_the_hand_and_shrinks_the_rest():
    big = resolve_proportions(spec(optional_bones=["hands"], overrides={"hand_size": 1.5}))
    plain = resolve_proportions(spec(optional_bones=["hands"]))
    assert big.hand > plain.hand and big.forearm < plain.forearm and big.upper_arm < plain.upper_arm
    assert big.upper_arm + big.forearm + big.hand == pytest.approx(big.arm_length)


def test_without_hands_the_forearm_absorbs_the_hand():
    with_h = resolve_proportions(spec(optional_bones=["hands"]))
    without = resolve_proportions(spec())
    assert without.hand == 0
    assert without.forearm == pytest.approx(with_h.forearm + with_h.hand)
    assert without.upper_arm == pytest.approx(with_h.upper_arm)
    assert without.upper_arm + without.forearm == pytest.approx(without.arm_length)


def test_without_a_chest_the_spine_absorbs_it():
    with_c = resolve_proportions(spec(optional_bones=["chest"]))
    without = resolve_proportions(spec())
    assert without.chest == 0
    assert without.spine == pytest.approx(with_c.spine + with_c.chest)
    assert without.torso_length == pytest.approx(with_c.torso_length)


def test_without_a_neck_the_head_absorbs_it():
    with_n = resolve_proportions(spec(optional_bones=["neck"]))
    without = resolve_proportions(spec())
    assert without.neck == 0
    assert without.head == pytest.approx(with_n.head + with_n.neck)
    assert without.head_only == pytest.approx(with_n.head_only)
    assert column(without) == pytest.approx(2.0)


def test_spine_2_takes_a_quarter_of_spine_and_chest():
    without = resolve_proportions(spec(optional_bones=["chest"]))
    with_2 = resolve_proportions(spec(optional_bones=["chest", "spine_2"]))
    assert with_2.spine_2 == pytest.approx(0.25 * (without.spine + without.chest))
    assert with_2.spine == pytest.approx(0.75 * without.spine)
    assert with_2.chest == pytest.approx(0.75 * without.chest)
    assert with_2.torso_length == pytest.approx(without.torso_length)


def test_spine_2_without_a_chest_takes_from_the_spine_only():
    p = resolve_proportions(spec(optional_bones=["spine_2"]))
    assert p.chest == 0
    assert p.spine_2 / (p.spine + p.spine_2) == pytest.approx(0.25)


def test_chest_bias_moves_length_between_spine_and_chest():
    long_chest = resolve_proportions(spec(optional_bones=["chest"], overrides={"chest_bias": 1.3}))
    plain = resolve_proportions(spec(optional_bones=["chest"]))
    assert long_chest.chest > plain.chest and long_chest.spine < plain.spine
    assert long_chest.hip == pytest.approx(plain.hip)


def test_neck_scale_and_foot_size():
    assert resolve_proportions(
        spec(optional_bones=["neck"], overrides={"neck_scale": 1.5})
    ).neck > (resolve_proportions(spec(optional_bones=["neck"])).neck)
    assert resolve_proportions(spec(overrides={"foot_size": 1.5})).foot == pytest.approx(
        1.5 * resolve_proportions(spec()).foot
    )


def test_toe_and_jaw_lengths():
    p = resolve_proportions(spec())
    assert p.toe == pytest.approx(0.3 * p.foot)
    assert p.jaw == pytest.approx(0.4 * p.head_unit)


def test_shoulder_width_scale():
    wide = resolve_proportions(spec(overrides={"shoulder_width_scale": 1.5}))
    assert wide.shoulder_width == pytest.approx(1.5 * resolve_proportions(spec()).shoulder_width)


def test_impossible_proportions_raise_a_build_error():
    with pytest.raises(BuildError, match="no room for a torso"):
        resolve_proportions(spec(base={"heads_tall": 2.0, "leg_ratio": 0.6}))


def test_derived_values_are_inside_the_bands_for_every_preset():
    for preset in PRESETS:
        derived = resolve_proportions(
            spec(preset=preset, optional_bones=["chest", "neck", "hands"])
        ).derived
        for name, value in derived.items():
            low, high = BANDS[name]
            assert low <= value <= high, (preset, name, value)


def test_the_bias_range_alone_never_leaves_the_bands():
    for preset, bias in itertools.product(PRESETS, (0.7, 1.3)):
        overrides = {
            "thigh_shin_bias": bias,
            "upper_forearm_bias": bias,
            "chest_bias": bias,
        }
        derived = resolve_proportions(
            spec(preset=preset, optional_bones=["chest", "hands"], overrides=overrides)
        ).derived
        for name in ("thigh_share", "upper_arm_share", "chest_share"):
            low, high = BANDS[name]
            assert low <= derived[name] <= high, (preset, bias, name, derived[name])


def test_derived_values_leave_out_absent_bones_and_side_view_shoulders():
    plain = resolve_proportions(spec()).derived_values("front")
    assert "hand_share" not in plain and "neck_hu" not in plain and "chest_share" not in plain
    assert "shoulder_width_hu" in plain
    assert "shoulder_width_hu" not in resolve_proportions(spec()).derived_values("side")


def test_every_optional_subset_keeps_the_column_at_the_height():
    front = [t for t in OPTIONAL_TOKENS if "front" in token_views(t)]
    for size in range(len(front) + 1):
        for tokens in itertools.combinations(front, size):
            p = resolve_proportions(spec(optional_bones=list(tokens)))
            assert column(p) == pytest.approx(2.0)
