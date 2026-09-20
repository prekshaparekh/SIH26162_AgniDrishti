"""The classifier interface.

Everything downstream of this module depends only on ``Classifier``. Version 1 is
a transparent rule set; version 2 will be a Random Forest trained on labelled data.
Swapping one for the other is an implementation change behind this protocol, not a
change to the ingestion pipeline, the models, or the user interface.

**Classification operates on episodes, not locations.** A site that runs a furnace
for two months and then suffers an accident produces one of each, and a vector
describing the location as a whole can represent neither: both collapse into the
same recurrence count. The site-level vector this module used to define could not
express the difference, so no classifier consuming it could either.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class EventFeatures:
    """The feature vector for one burning episode.

    Three groups, and the split is deliberate. The episode's own shape is what the
    rules judge. The site context says where it happened. The site history says
    what is normal there -- which is how a short burn at a refinery can be read
    against that refinery's own baseline rather than against the whole dataset.

    The same vector feeds the v1 rules and the planned v2 model, so labels
    collected now remain valid when the model replaces the rules.
    """

    # --- the episode itself ---
    duration_days: int
    active_days: int
    density: float
    detection_count: int
    frp_mean: float
    frp_max: float
    frp_cv: float
    brightness_max: float
    night_fraction: float
    confidence: str
    gap_before_days: int | None
    is_ongoing: bool

    # --- where it happened ---
    dist_industrial_m: float | None
    industrial_group: str
    land_context: str
    landcover_frac_builtup: float

    # --- what is normal at this location ---
    site_event_count: int
    site_recurrence_days: int
    site_max_event_duration: int
    site_age_days: int


@dataclass
class Classification:
    label: str
    confidence: str
    evidence: list[str] = field(default_factory=list)
    matched_rule: str = ""


class Classifier(Protocol):
    def predict(self, features: EventFeatures) -> Classification: ...
