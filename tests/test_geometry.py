import math
import random

import pytest

from rig_agent.builder.geometry import (
    Placed,
    advance,
    distance,
    local_to_world,
    mirror_angle,
    mirror_x,
    normalize_angle,
    world_to_local,
)


@pytest.mark.parametrize(
    ("deg", "expected"),
    [
        (0, 0),
        (90, 90),
        (180, 180),
        (-180, 180),
        (181, -179),
        (-181, 179),
        (360, 0),
        (450, 90),
        (-450, -90),
    ],
)
def test_normalize_angle(deg, expected):
    assert normalize_angle(deg) == pytest.approx(expected)


def test_advance_along_the_axes():
    assert advance((1, 2), 0, 3) == pytest.approx((4, 2))
    assert advance((1, 2), 90, 3) == pytest.approx((1, 5))
    assert advance((0, 0), -90, 2) == pytest.approx((0, -2))
    assert advance((0, 0), 180, 2) == pytest.approx((-2, 0))
    assert advance((0, 0), 45, math.sqrt(2)) == pytest.approx((1, 1))


def test_mirror_point_and_angle():
    assert mirror_x((0.3, 1.2)) == (-0.3, 1.2)
    assert mirror_angle(-45) == pytest.approx(-135)
    assert mirror_angle(0) == pytest.approx(180)
    assert mirror_angle(90) == pytest.approx(90)
    assert mirror_angle(-90) == pytest.approx(-90)
    assert mirror_angle(180) == pytest.approx(0)


def test_mirroring_a_bone_mirrors_its_tail():
    bone = Placed("a", None, (0.2, 1.0), -45, 0.5)
    twin = Placed("b", None, mirror_x(bone.head), mirror_angle(bone.angle), bone.length)
    assert twin.tail == pytest.approx(mirror_x(bone.tail))


def test_distance():
    assert distance((0, 0), (3, 4)) == 5


def test_placed_tail():
    assert Placed("root", None, (0, 0), 90, 0.05).tail == pytest.approx((0, 0.05))
    assert Placed("arm", "chest", (0.2, 1.4), -45, math.sqrt(2)).tail == pytest.approx((1.2, 0.4))


def test_local_position_of_a_child_on_the_parents_tail_is_along_local_x():
    parent = Placed("upper_arm", None, (0.2, 1.4), -45, 0.29)
    child_head = parent.tail
    local, rotation = world_to_local(parent.head, parent.angle, child_head, -45)
    assert local == pytest.approx((0.29, 0.0))
    assert rotation == pytest.approx(0.0)


def test_root_child_offset_in_a_rotated_frame():
    local, rotation = world_to_local((0, 0), 90, (0, 0.94), 90)
    assert local == pytest.approx((0.94, 0.0))
    assert rotation == pytest.approx(0.0)


def test_local_rotation_is_relative_and_normalised():
    _, rotation = world_to_local((0, 0), -135, (1, 1), 170)
    assert rotation == pytest.approx(normalize_angle(305))


def test_world_local_world_round_trip():
    rng = random.Random(7)
    for _ in range(200):
        parent_head = (rng.uniform(-2, 2), rng.uniform(-2, 2))
        parent_deg = rng.uniform(-180, 180)
        child_head = (rng.uniform(-2, 2), rng.uniform(-2, 2))
        child_deg = rng.uniform(-180, 180)
        local, rotation = world_to_local(parent_head, parent_deg, child_head, child_deg)
        head, deg = local_to_world(parent_head, parent_deg, local, rotation)
        assert head == pytest.approx(child_head, abs=1e-9)
        assert normalize_angle(deg - child_deg) == pytest.approx(0, abs=1e-9)
