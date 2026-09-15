"""Version 1 classifier: a transparent, documented rule set.

This is not a machine learning model and is not presented as one. Its purpose is
threefold:

1. to make the pipeline demonstrable end to end before a labelled dataset exists,
2. to state our domain hypothesis explicitly so it can be argued with, and
3. to pre-label candidates in the annotation interface, so that human reviewers
   correct predictions rather than label from scratch.

The thresholds below are informed estimates, not validated science. No accuracy is
claimed for them. In v2 a Random Forest learns these boundaries from labelled data
instead of having them written here by hand.
"""
from __future__ import annotations

from .base import Classification, Classifier, SiteFeatures

INDUSTRIAL_PROXIMITY_M = 1000.0
INDUSTRIAL_FIRE_MIN_FRP = 10.0
STABLE_FRP_CV = 0.5

# Recurrence thresholds are expressed as a FRACTION of the observation window, not
# as a fixed number of days. "Detected on 20 days" means something entirely
# different over a 90-day archive than over a 7-day public feed, so a fixed count
# would silently change meaning with the data source. The reference values are the
# documented 20 and 3 days out of 90.
PERSISTENT_FRACTION = 20 / 90
EPISODIC_FRACTION = 3 / 90

# Floors that stop small windows from producing statistically meaningless rules:
# one detection day out of seven is noise, not evidence of a persistent source.
PERSISTENT_FLOOR_DAYS = 3
EPISODIC_FLOOR_DAYS = 1


def thresholds_for_window(window_days: int) -> tuple[int, int]:
    """Return (persistent_min, episodic_max) recurrence counts for a window."""
    persistent = max(PERSISTENT_FLOOR_DAYS, round(PERSISTENT_FRACTION * window_days))
    episodic = max(EPISODIC_FLOOR_DAYS, int(EPISODIC_FRACTION * window_days))
    # The two bands must not overlap, or a site could match both rules.
    episodic = min(episodic, persistent - 1)
    return persistent, episodic

BUILT_CONTEXTS = {"built_up", "bare"}
VEGETATED_CONTEXTS = {"tree_cover", "grass_shrub", "cropland"}


def _distance_phrase(distance: float | None) -> str:
    if distance is None:
        return "no mapped industrial feature nearby"
    if distance < 1000:
        return f"{distance:.0f} m from nearest mapped industrial feature"
    return f"{distance / 1000:.1f} km from nearest mapped industrial feature"


class RuleClassifier(Classifier):
    """Applies the documented rules in priority order; first match wins."""

    version = "rules-v1"

    def __init__(self, window_days: int = 90):
        self.window_days = window_days
        self.persistent_min, self.episodic_max = thresholds_for_window(window_days)

    def predict(self, features: SiteFeatures) -> Classification:
        distance = features.dist_industrial_m
        window = self.window_days
        near_industry = distance is not None and distance <= INDUSTRIAL_PROXIMITY_M
        built = features.land_context in BUILT_CONTEXTS
        vegetated = features.land_context in VEGETATED_CONTEXTS

        base_evidence = [
            f"detected on {features.recurrence_days} of the last {window} days",
            _distance_phrase(distance),
            f"land context: {features.land_context.replace('_', ' ')}",
        ]

        # Rule 1 -- refuse to classify what the instrument itself is unsure about.
        if features.confidence == "low":
            return Classification(
                label="uncertain",
                confidence="low",
                evidence=["FIRMS reported low detection confidence"] + base_evidence,
                matched_rule="R1: low detection confidence",
            )

        # Rule 2 -- persistent thermal source: industrial context, burning most
        # days, at a stable radiative power. This is a flare or a furnace.
        if (
            features.recurrence_days >= self.persistent_min
            and near_industry
            and built
            and features.frp_cv < STABLE_FRP_CV
        ):
            return Classification(
                label="persistent_source",
                confidence="high"
                if features.recurrence_days >= 0.5 * window
                else "medium",
                evidence=[
                    f"recurs on {features.recurrence_days} of {window} days",
                    f"FRP stable at {features.frp_mean:.1f} MW "
                    f"(coefficient of variation {features.frp_cv:.2f})",
                    _distance_phrase(distance),
                    f"nearest feature type: {features.industrial_group.replace('_', ' ')}",
                    f"land context: {features.land_context.replace('_', ' ')}",
                ],
                matched_rule="R2: recurrent + industrial + stable FRP",
            )

        # Rule 3 -- industrial fire: industrial context, releasing enough energy to
        # matter, and anomalous against the site's own baseline in one of two ways.
        #
        # Anything reaching this rule has already failed R2, so it is not a stable
        # recurrent source. It qualifies as a fire if it is either RARE (few
        # detection days) or ERRATIC (radiative power varies widely). The second
        # condition matters: a fire that burns for several days is still a fire,
        # and an earlier version of this rule mislabelled exactly those cases as
        # uncertain because it tested recurrence alone. A flare is steady; a fire
        # flares up and dies down.
        episodic = features.recurrence_days <= self.episodic_max
        erratic = features.frp_cv >= STABLE_FRP_CV
        if near_industry and built and features.frp_max >= INDUSTRIAL_FIRE_MIN_FRP and (
            episodic or erratic
        ):
            anomaly = (
                f"only {features.recurrence_days} detection day(s) in {window} "
                f"- episodic, not routine"
                if episodic
                else f"radiative power is unstable "
                f"(coefficient of variation {features.frp_cv:.2f}), unlike a routine flare"
            )
            return Classification(
                label="industrial_fire",
                confidence="medium" if features.confidence == "high" else "low",
                evidence=[
                    anomaly,
                    f"peak FRP {features.frp_max:.1f} MW",
                    _distance_phrase(distance),
                    f"nearest feature type: {features.industrial_group.replace('_', ' ')}",
                    f"land context: {features.land_context.replace('_', ' ')}",
                ],
                matched_rule="R3: industrial context + anomalous (episodic or erratic FRP)",
            )

        # Rule 4 -- vegetation fire: the burning surface is vegetated.
        #
        # Land cover leads here, and proximity to industry only moderates
        # confidence. An earlier version required the site to be more than a
        # kilometre from any mapped industrial feature, which denied the label to
        # 18 of 106 sites that were burning on cropland merely because a factory
        # stood nearby. That was the wrong way round: a hot pixel on cropland is
        # cropland burning, whatever sits next door.
        #
        # Proximity still matters, because WorldCover can misread a small facility
        # as the vegetation surrounding it -- so a nearby plant lowers confidence
        # and is recorded in the evidence rather than silently overriding the
        # land cover. Rules 2 and 3 run first and both require built-up or bare
        # ground, so a genuine industrial site is claimed before reaching here.
        if vegetated:
            confidence = "medium" if features.confidence == "high" else "low"
            evidence = [
                f"land context: {features.land_context.replace('_', ' ')} (ESA WorldCover, 10 m)",
                _distance_phrase(distance),
                f"peak FRP {features.frp_max:.1f} MW",
            ]
            if near_industry:
                confidence = "low"
                evidence.append(
                    "industrial infrastructure mapped within 1 km - "
                    "land cover may be misattributed at this scale"
                )
            return Classification(
                label="vegetation_fire",
                confidence=confidence,
                evidence=evidence,
                matched_rule="R4: vegetated land cover",
            )

        # Rule 5 -- everything else. An honest abstention is more useful than a
        # confident guess, and these are the cases the annotation queue prioritises.
        reason = (
            "land cover is unmapped in OpenStreetMap"
            if features.land_context == "unknown"
            else "feature combination does not match any rule"
        )
        return Classification(
            label="uncertain",
            confidence="low",
            evidence=[reason] + base_evidence,
            matched_rule="R5: no rule matched",
        )
