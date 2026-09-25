"""resolve_proportions: a RigSpec becomes concrete segment lengths (LLD 2.4)."""

from dataclasses import dataclass

from rig_agent.builder.errors import BuildError
from rig_agent.schemas.rig_spec import RigSpec
from rig_agent.vocabulary.bones import View, present_bones
from rig_agent.vocabulary.poses import JAW_LENGTH_HU, ROOT_LENGTH_RATIO, TOE_LENGTH_FACTOR
from rig_agent.vocabulary.presets import PRESETS, SPINE_2_TAKE


@dataclass(frozen=True)
class ResolvedProportions:
    """Every length the layouts need, in world units. Absent bones have length 0."""

    height: float
    head_unit: float  # nominal head unit, H / heads_tall
    root: float
    leg_length: float  # hip joint to ground
    ankle_height: float
    thigh: float
    shin: float
    foot: float
    toe: float
    hip: float
    spine: float
    spine_2: float
    chest: float
    neck: float
    head: float  # includes the neck when the neck bone is absent
    head_only: float  # the head without any absorbed neck
    arm_length: float  # shoulder joint to fingertips
    upper_arm: float
    forearm: float
    hand: float
    jaw: float
    shoulder_width: float
    hip_spacing: float
    derived: dict[str, float]  # design values in the units of the plausibility bands

    @property
    def torso_length(self) -> float:
        return self.hip + self.spine + self.spine_2 + self.chest

    def derived_values(self, view: View) -> dict[str, float]:
        """Values to check against the plausibility bands (LLD 2.4.4) for the given view."""
        return {
            name: value
            for name, value in self.derived.items()
            if not (view == "side" and name == "shoulder_width_hu")
        }


def _pick(value: float | None, default: float) -> float:
    return default if value is None else value


def _bias_split(a: float, c: float, bias: float) -> tuple[float, float]:
    """Redistribute a + c with a' ∝ a·bias and c' ∝ c/bias, keeping the total (LLD 2.4.3)."""
    wa, wc = a * bias, c / bias
    total = a + c
    return total * wa / (wa + wc), total * wc / (wa + wc)


def resolve_proportions(spec: RigSpec) -> ResolvedProportions:
    preset = PRESETS[spec.preset]
    base, mult = spec.base, spec.overrides
    present = present_bones(spec.optional_bones)
    height = spec.height_units

    heads_tall = _pick(base.heads_tall, preset.heads_tall)
    leg_ratio = _pick(base.leg_ratio, preset.leg_ratio)
    arm_ratio = _pick(base.arm_ratio, preset.arm_ratio)
    shoulder_width_hu = _pick(base.shoulder_width_hu, preset.shoulder_width_hu)
    hip_spacing_hu = _pick(base.hip_spacing_hu, preset.hip_spacing_hu)
    hu = height / heads_tall

    # Vertical column: leg + torso + neck + head, rescaled uniformly back to H (LLD 2.4.3).
    nominal_torso = height - leg_ratio * height - preset.neck_hu * hu - hu
    if nominal_torso <= 0:
        raise BuildError(
            f"the proportions leave no room for a torso: {heads_tall} heads tall with legs "
            f"{leg_ratio:.2f} of the height. Use more heads or shorter legs."
        )
    leg0 = leg_ratio * height * mult.leg_scale
    head0 = hu * mult.head_scale
    neck0 = preset.neck_hu * hu * mult.neck_scale
    torso0 = nominal_torso * mult.torso_scale
    k = height / (leg0 + head0 + neck0 + torso0)
    leg, head_only, neck, torso = leg0 * k, head0 * k, neck0 * k, torso0 * k

    ankle = preset.ankle_ratio * height
    if leg <= ankle:
        raise BuildError("the legs are too short for the ankle height")

    # Leg: thigh and shin split the hip-to-ankle span.
    thigh_share, _ = _bias_split(preset.thigh_share, 1 - preset.thigh_share, mult.thigh_shin_bias)
    thigh = (leg - ankle) * thigh_share
    shin = (leg - ankle) - thigh
    foot = preset.foot_length_hu * hu * mult.foot_size

    # Arm: pair bias first, then the hand share, then absorb the hand if there are no hands.
    upper_s, fore_s, hand_s = preset.arm_split
    upper_s, fore_s = _bias_split(upper_s, fore_s, mult.upper_forearm_bias)
    upper_pair_share = upper_s / (upper_s + fore_s)
    hand_s = hand_s * mult.hand_size
    upper_s, fore_s = (1 - hand_s) * upper_pair_share, (1 - hand_s) * (1 - upper_pair_share)
    hands = "hand_L" in present
    if not hands:
        fore_s, hand_s_kept = fore_s + hand_s, 0.0
    else:
        hand_s_kept = hand_s
    arm = arm_ratio * height * mult.arm_scale

    # Torso: chest bias, absorb an absent chest, then spine_2 takes a share.
    hip_s, spine_s, chest_s = preset.torso_split
    chest_s, spine_s = _bias_split(chest_s, spine_s, mult.chest_bias)
    chest_design_share = chest_s
    if "chest" not in present:
        spine_s, chest_s = spine_s + chest_s, 0.0
    spine_2_s = 0.0
    if "spine_2" in present:
        spine_2_s = SPINE_2_TAKE * (spine_s + chest_s)
        spine_s *= 1 - SPINE_2_TAKE
        chest_s *= 1 - SPINE_2_TAKE

    neck_present = "neck" in present
    derived = {
        "heads_tall": height / head_only,
        "shoulder_width_hu": shoulder_width_hu * hu * mult.shoulder_width_scale / head_only,
        "hip_spacing_hu": hip_spacing_hu * hu / head_only,
        "leg_ratio": leg / height,
        "arm_ratio": arm / height,
        "thigh_share": thigh_share,
        "upper_arm_share": upper_pair_share,
        "foot_length_hu": foot / head_only,
    }
    if hands:
        derived["hand_share"] = hand_s
    if neck_present:
        derived["neck_hu"] = neck / head_only
    if "chest" in present:
        derived["chest_share"] = chest_design_share

    return ResolvedProportions(
        height=height,
        head_unit=hu,
        root=ROOT_LENGTH_RATIO * height,
        leg_length=leg,
        ankle_height=ankle,
        thigh=thigh,
        shin=shin,
        foot=foot,
        toe=foot * TOE_LENGTH_FACTOR,
        hip=torso * hip_s,
        spine=torso * spine_s,
        spine_2=torso * spine_2_s,
        chest=torso * chest_s,
        neck=neck if neck_present else 0.0,
        head=head_only if neck_present else head_only + neck,
        head_only=head_only,
        arm_length=arm,
        upper_arm=arm * upper_s,
        forearm=arm * fore_s,
        hand=arm * hand_s_kept,
        jaw=JAW_LENGTH_HU * hu,
        shoulder_width=shoulder_width_hu * hu * mult.shoulder_width_scale,
        hip_spacing=hip_spacing_hu * hu,
        derived=derived,
    )
