"""The classifier interface.

Everything downstream of this module depends only on ``Classifier``. Version 1 is
a transparent rule set; version 2 will be a Random Forest trained on labelled data.
Swapping one for the other is an implementation change behind this protocol, not a
change to the ingestion pipeline, the models, or the user interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SiteFeatures:
    """The feature vector for one site.

    The same vector feeds the v1 rules and the planned v2 model, so that the
    training data collected now remains valid when the model replaces the rules.
    """

    frp_mean: float
    frp_max: float
    frp_cv: float
    brightness_max: float
    confidence: str
    recurrence_days: int
    detection_count: int
    night_fraction: float
    site_age_days: int
    dist_industrial_m: float | None
    industrial_group: str
    land_context: str


@dataclass
class Classification:
    label: str
    confidence: str
    evidence: list[str] = field(default_factory=list)
    matched_rule: str = ""


class Classifier(Protocol):
    def predict(self, features: SiteFeatures) -> Classification: ...
