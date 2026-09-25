import re

import pytest

from rig_agent.vocabulary.bones import (
    BONES,
    MAX_CANONICAL_BONES,
    OPTIONAL_TOKENS,
    REQUIRED_BONES,
    expand_optional,
    token_views,
)

EXPECTED_REQUIRED = {
    "root", "hip", "spine", "head",
    "upper_arm_L", "upper_arm_R", "forearm_L", "forearm_R",
    "thigh_L", "thigh_R", "shin_L", "shin_R", "foot_L", "foot_R",
}  # fmt: skip


def test_required_set_is_the_fourteen_from_the_lld():
    assert REQUIRED_BONES == EXPECTED_REQUIRED


def test_at_most_24_canonical_bones():
    assert MAX_CANONICAL_BONES == 24 == len(BONES)


def test_names_are_snake_case_and_unique():
    assert all(re.fullmatch(r"[a-z0-9_]+?(_[LR])?", name) for name in BONES)
    assert len(BONES) == len({b.name for b in BONES.values()})


def test_every_sided_bone_has_its_twin():
    for name in BONES:
        if name.endswith("_L"):
            assert name[:-2] + "_R" in BONES


def test_optional_tokens():
    assert set(OPTIONAL_TOKENS) == {
        "chest", "neck", "spine_2", "hands", "shoulders", "toes", "jaw",
    }  # fmt: skip


def test_every_optional_bone_belongs_to_a_token_and_required_ones_do_not():
    for b in BONES.values():
        assert (b.token is None) == b.required


@pytest.mark.parametrize(
    ("token", "bones"),
    [
        ("hands", ["hand_L", "hand_R"]),
        ("shoulders", ["shoulder_L", "shoulder_R"]),
        ("toes", ["toe_L", "toe_R"]),
        ("chest", ["chest"]),
        ("neck", ["neck"]),
        ("spine_2", ["spine_2"]),
        ("jaw", ["jaw"]),
    ],
)
def test_expand_single_token(token, bones):
    assert expand_optional([token]) == bones


def test_expand_is_in_table_order_and_deduplicated():
    assert expand_optional(["jaw", "hands", "chest", "hands"]) == [
        "chest", "hand_L", "hand_R", "jaw",
    ]  # fmt: skip


def test_expand_nothing():
    assert expand_optional([]) == []


def test_expand_all_gives_the_ten_optional_bones():
    assert len(expand_optional(OPTIONAL_TOKENS)) == 10


def test_unknown_token_is_rejected():
    with pytest.raises(ValueError, match="shoulder_L"):
        expand_optional(["shoulder_L"])


def test_view_limits():
    assert token_views("shoulders") == {"front"}
    assert token_views("toes") == {"side"}
    for token in ("chest", "neck", "spine_2", "hands", "jaw"):
        assert token_views(token) == {"front", "side"}


def test_token_views_rejects_unknown_token():
    with pytest.raises(ValueError):
        token_views("wings")
