"""evals/metrics/extras.py: accessory names grouped by kind, and F1 over the groups (Q8)."""

import pytest

from evals.metrics.extras import OTHER, chains_by_group, extras_f1, group_of
from rig_agent.schemas.rig_spec import ExtraBoneSpec


@pytest.mark.parametrize(
    ("name", "group"),
    [
        ("extra_cape", "cloth"),  # not headwear, although "cap" is inside it
        ("extra_cap", "headwear"),
        ("extra_ponytail", "hair"),  # not tail
        ("extra_twin_ponytail_2", "hair"),
        ("extra_fluffy_tail", "tail"),
        ("extra_coat_tail", "cloth"),
        ("extra_greatsword", "held"),
        ("extra_longbow", "held"),
        ("extra_spike_hammer", "held"),
        ("extra_horns", "horns"),
        ("extra_bat_wing", "wings"),
        ("extra_ear", "ears"),
        ("extra_earring", OTHER),  # not ears
        ("extra_halo", "headwear"),
        ("extra_quiver", "gear"),
        ("extra_round_shield", "shield"),
        ("extra_braid_1", "hair"),
        ("extra_belt", OTHER),
    ],
)
def test_group_of(name, group):
    assert group_of(name) == group


def extra(name, mirror=False):
    return ExtraBoneSpec(name=name, parent="head", direction_deg=0, length_ratio=0.1, mirror=mirror)


def test_a_mirrored_chain_counts_twice():
    counts = chains_by_group([extra("extra_ponytail", mirror=True), extra("extra_cape")])
    assert counts == {"hair": 2, "cloth": 1}


def test_f1_perfect_partial_and_none():
    assert extras_f1({"hair": 2, "cloth": 1}, {"hair": 2, "cloth": 1}) == 1.0
    assert extras_f1({}, {}) == 1.0  # nothing asked, nothing made
    assert extras_f1({"hair": 2}, {"held": 1}) == 0.0
    # 2 hair expected, 1 made: precision 1, recall 0.5 -> F1 2/3
    assert extras_f1({"hair": 2}, {"hair": 1}) == pytest.approx(2 / 3)
    # an extra, unasked-for accessory costs precision
    assert extras_f1({"hair": 1}, {"hair": 1, "held": 1}) == pytest.approx(2 / 3)
    assert extras_f1({}, {"held": 1}) == 0.0
