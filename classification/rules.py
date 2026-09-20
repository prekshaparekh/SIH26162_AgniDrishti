"""Version 1 classifier: a transparent, documented rule set over burning episodes.

This is not a machine learning model and is not presented as one. Its purpose is
threefold:

1. to make the pipeline demonstrable end to end before a labelled dataset exists,
2. to state our domain hypothesis explicitly so it can be argued with, and
3. to pre-label candidates in the annotation interface, so that human reviewers
   correct predictions rather than label from scratch.

The thresholds below are informed estimates, not validated science. No accuracy is
claimed for them. In v2 a Random Forest learns these boundaries from labelled data
instead of having them written here by hand.

**Why episodes rather than sites.** The rules used to run over a location's whole
history, which meant a site that burned for three days in March and two days in May
was indistinguishable from one that burned five days straight: both reported
``recurrence_days = 5``, which is too many to look episodic and too few to look
routine, so both were abstained on. Judging each episode separately is what lets
the March fire and the May fire each be called a fire.
"""
from __future__ import annotations

from .base import Classification, Classifier, EventFeatures

INDUSTRIAL_PROXIMITY_M = 1000.0
INDUSTRIAL_FIRE_MIN_FRP = 10.0
STABLE_FRP_CV = 0.5

# Thresholds are expressed as a FRACTION of the observation window, not as a fixed
# number of days. "A 20-day episode" means something entirely different inside a
# 90-day archive than inside a 7-day public feed, so a fixed count would silently
# change meaning with the data source. The reference values are 20 and 3 days
# out of 90.
PERSISTENT_FRACTION = 20 / 90
EPISODIC_FRACTION = 3 / 90

# Floors that stop small windows from producing statistically meaningless rules.
PERSISTENT_FLOOR_DAYS = 3
EPISODIC_FLOOR_DAYS = 1

# A long episode must actually be burning through it. A 20-day span holding two
# detections is two blips three weeks apart, not a sustained burn. The persistent
# sources measured so far sit at 0.32 to 0.58, so the floor is set below all of
# them with margin -- an informed estimate like every other threshold here.
MIN_EPISODE_DENSITY = 0.25

# Above this, an episode is dense enough that its length is not an artefact of a
# couple of lucky cloud-free days.
CONFIDENT_EPISODE_DENSITY = 0.4


def thresholds_for_window(window_days: int) -> tuple[int, int]:
    """Return (sustained_min, brief_max) episode spans for a window."""
    persistent = max(PERSISTENT_FLOOR_DAYS, round(PERSISTENT_FRACTION * window_days))
    episodic = max(EPISODIC_FLOOR_DAYS, int(EPISODIC_FRACTION * window_days))
    # The two bands must not overlap, or an episode could match both rules.
    episodic = min(episodic, persistent - 1)
    return persistent, episodic


BUILT_CONTEXTS = {"built_up", "bare"}
VEGETATED_CONTEXTS = {"tree_cover", "grass_shrub", "cropland"}

# Land cover is judged over the whole detection footprint, not at its centre.
# A VIIRS pixel is ~375 m across; the majority class is a single 10 m reading that
# flips depending on which pixel the centroid happened to land in. Measured on the
# sites near mapped industry, the centre pixel disagreed with the footprint
# majority 28% of the time, and three adjacent pixels inside one Hazira steel plant
# came back "tree cover" -- each then classified as a vegetation fire burning for
# 40 to 71 days. Ground that is mostly built-up or bare counts as industrial
# regardless of what the centre pixel says, and ground that is mostly built-up is
# not eligible to be called a vegetation fire.
BUILT_FRACTION_THRESHOLD = 0.5

# Vegetation burns for days, not weeks. Cropland and scrub in Gujarat are consumed
# in hours; even a forest fire is over long before a month. An episode that keeps
# producing detections across a span this long is therefore evidence that the land
# cover reading is wrong, not that the vegetation is unusually persistent -- three
# pixels inside the Hazira steel plant came back "tree cover" and were reported as
# vegetation fires burning for 40, 41 and 71 days.
#
# The response is to abstain, not to assert the opposite. We know enough to say the
# vegetation label is not credible; we do not know enough to call it industrial,
# and the footprint here really is mostly vegetated. These are exactly the cases
# the annotation queue should see first.
VEGETATION_IMPLAUSIBLE_SPAN = 20


def _distance_phrase(distance: float | None) -> str:
    if distance is None:
        return "no mapped industrial feature nearby"
    if distance < 1000:
        return f"{distance:.0f} m from nearest mapped industrial feature"
    return f"{distance / 1000:.1f} km from nearest mapped industrial feature"


def _land_phrase(features: EventFeatures) -> str:
    return (
        f"land context: {features.land_context.replace('_', ' ')} "
        f"({features.landcover_frac_builtup:.0%} of the footprint built-up or bare)"
    )


def _span_phrase(features: EventFeatures) -> str:
    return (
        f"episode ran {features.duration_days} day(s), with detections on "
        f"{features.active_days} of them ({features.density:.0%})"
    )


class EventRuleClassifier(Classifier):
    """Applies the documented rules in priority order; first match wins."""

    version = "event-rules-v1"

    def __init__(self, window_days: int = 90):
        self.window_days = window_days
        self.sustained_min, self.brief_max = thresholds_for_window(window_days)

    def predict(self, features: EventFeatures) -> Classification:
        distance = features.dist_industrial_m
        near_industry = distance is not None and distance <= INDUSTRIAL_PROXIMITY_M
        mostly_built = features.landcover_frac_builtup >= BUILT_FRACTION_THRESHOLD
        built = features.land_context in BUILT_CONTEXTS or mostly_built
        vegetated = features.land_context in VEGETATED_CONTEXTS and not mostly_built

        # Rule 3 needs a stricter test than Rule 2. `built` counts bare ground as
        # industrial, which is right for a furnace yard, a slag heap or a quarry --
        # those are real persistent sources. It is wrong for a fire: a fire needs
        # something to burn, and bare ground on its own is not evidence of any.
        #
        # Three of the four industrial fires reported before this rule existed sat
        # on the bare scrubland of the Dholera Solar Park, and their footprints
        # contain 0% built-up pixels across the full 375 m. There is no structure
        # there. The centre-pixel class is still accepted on its own because it is
        # the one reading we know is taken inside the detection.
        on_structures = (
            features.land_context == "built_up"
            or features.landcover_frac_built_only >= BUILT_FRACTION_THRESHOLD
        )

        base_evidence = [
            _span_phrase(features),
            _distance_phrase(distance),
            _land_phrase(features),
        ]

        # Rule 1 -- refuse to classify what the instrument itself is unsure about.
        if features.confidence == "low":
            return Classification(
                label="uncertain",
                confidence="low",
                evidence=["FIRMS reported low detection confidence"] + base_evidence,
                matched_rule="R1: low detection confidence",
            )

        # Rule 2 -- persistent thermal source: a long, genuinely sustained burn in
        # an industrial setting.
        #
        # An earlier version also demanded stable radiative power (cv < 0.5), on
        # the assumption that a flare burns steadily. Measured over 90 days that is
        # false, and backwards: median cv RISES with recurrence, because a site
        # observed more often is sampled across more viewing angles, atmospheres
        # and times of day. The gate was rejecting precisely the most persistent
        # sources and the class came back empty. cv is still reported and still
        # shapes confidence, but it no longer decides the class.
        #
        # Density is the gate instead. Length alone is not enough: cloud leaves
        # long spans with very few detections in them.
        if (
            near_industry
            and built
            and features.duration_days >= self.sustained_min
            and features.density >= MIN_EPISODE_DENSITY
        ):
            corroborated = features.site_recurrence_days >= self.sustained_min
            confidence = (
                "high"
                if features.density >= CONFIDENT_EPISODE_DENSITY or corroborated
                else "medium"
            )
            evidence = [
                f"sustained burn: {_span_phrase(features)}",
                f"FRP averages {features.frp_mean:.1f} MW "
                f"(coefficient of variation {features.frp_cv:.2f})",
            ]
            if features.is_ongoing:
                evidence.append("this episode has not yet ended")
            if features.site_event_count > 1:
                evidence.append(
                    f"one of {features.site_event_count} episodes at this location"
                )
            evidence += [
                _distance_phrase(distance),
                f"nearest feature type: {features.industrial_group.replace('_', ' ')}",
                _land_phrase(features),
            ]
            return Classification(
                label="persistent_source",
                confidence=confidence,
                evidence=evidence,
                matched_rule="R2: sustained episode + industrial context",
            )

        # Rule 3 -- industrial fire: a brief, energetic burn in an industrial
        # setting.
        #
        # Brevity is measured on THIS episode, not on the location's total
        # detection count. That is the whole point of the move to episodes: two
        # fires two months apart used to sum to five detection days and fall
        # between the rules, so neither was reported. Each is now three days and
        # two days, and each is a fire.
        #
        # Note this rule can fire at a location that also hosts a persistent
        # source, because Rule 2 tested this episode rather than the site. That is
        # intended -- an accident inside an operating plant is the single most
        # important thing this system is meant to surface, and a site-level
        # persistent label would have hidden it.
        if (
            near_industry
            and on_structures
            and features.duration_days <= self.brief_max
            and features.frp_max >= INDUSTRIAL_FIRE_MIN_FRP
        ):
            evidence = [
                f"brief and energetic: {_span_phrase(features)}",
                f"built-up ground: {features.landcover_frac_built_only:.0%} of the "
                f"footprint carries structures",
                f"peak FRP {features.frp_max:.1f} MW",
            ]
            if features.site_max_event_duration >= self.sustained_min:
                evidence.append(
                    "this location also hosts a long-running episode, so the burn "
                    "may be routine operation seen through a gap in cloud"
                )
            if features.gap_before_days:
                evidence.append(
                    f"{features.gap_before_days} quiet days preceded it"
                )
            evidence += [
                _distance_phrase(distance),
                f"nearest feature type: {features.industrial_group.replace('_', ' ')}",
                _land_phrase(features),
            ]
            return Classification(
                label="industrial_fire",
                confidence="medium" if features.confidence == "high" else "low",
                evidence=evidence,
                matched_rule="R3: brief episode + industrial context + high FRP",
            )

        # Rule 4 -- vegetation fire: the burning surface is vegetated.
        #
        # Land cover leads here, and proximity to industry only moderates
        # confidence. An earlier version required the site to be more than a
        # kilometre from any mapped industrial feature, which denied the label to
        # 18 of 106 sites burning on cropland merely because a factory stood
        # nearby. A hot pixel on cropland is cropland burning, whatever sits next
        # door. Proximity still lowers confidence, because WorldCover can misread a
        # small facility as the vegetation around it.
        if vegetated and features.duration_days >= VEGETATION_IMPLAUSIBLE_SPAN:
            evidence = [
                f"land cover reads {features.land_context.replace('_', ' ')}, but the "
                f"episode ran {features.duration_days} days - too long for vegetation, "
                f"which burns in hours to days",
                _span_phrase(features),
                _land_phrase(features),
                _distance_phrase(distance),
            ]
            if near_industry:
                evidence.append(
                    f"mapped industry {distance:.0f} m away "
                    f"({features.industrial_group.replace('_', ' ')}) - the land cover "
                    f"reading is the likely error"
                )
            return Classification(
                label="uncertain",
                confidence="low",
                evidence=evidence,
                matched_rule="R4b: vegetation label implausible for the span",
            )

        if vegetated:
            confidence = "medium" if features.confidence == "high" else "low"
            evidence = [
                _land_phrase(features) + " (ESA WorldCover, 10 m)",
                _span_phrase(features),
                f"peak FRP {features.frp_max:.1f} MW",
                _distance_phrase(distance),
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
        if features.land_context == "unknown":
            reason = "land cover is unmapped"
        elif features.land_context in VEGETATED_CONTEXTS and mostly_built:
            reason = (
                f"centre pixel reads {features.land_context.replace('_', ' ')}, but "
                f"{features.landcover_frac_builtup:.0%} of the footprint is built-up "
                f"or bare - too contradictory to call a vegetation fire"
            )
        elif (
            near_industry
            and built
            and not on_structures
            and features.duration_days <= self.brief_max
            and features.frp_max >= INDUSTRIAL_FIRE_MIN_FRP
        ):
            reason = (
                f"brief and energetic in an industrial area, but only "
                f"{features.landcover_frac_built_only:.0%} of the footprint is "
                f"built-up - bare ground alone is not something that burns"
            )
        elif near_industry and built and features.duration_days <= self.brief_max:
            # It was brief enough to be a fire; the energy was the missing part.
            reason = (
                f"brief industrial-context episode, but peak FRP "
                f"{features.frp_max:.1f} MW is below the "
                f"{INDUSTRIAL_FIRE_MIN_FRP:.0f} MW threshold for a fire"
            )
        elif near_industry and built:
            reason = (
                f"industrial setting, but the episode is neither sustained "
                f"(>= {self.sustained_min} days) nor brief (<= {self.brief_max} days)"
            )
        else:
            reason = "feature combination does not match any rule"
        return Classification(
            label="uncertain",
            confidence="low",
            evidence=[reason] + base_evidence,
            matched_rule="R5: no rule matched",
        )
