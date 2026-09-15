"""Turn a stored Site into the feature vector the classifier consumes."""
from __future__ import annotations

from .base import SiteFeatures


def extract(site) -> SiteFeatures:
    age_days = (site.last_seen - site.first_seen).days if site.first_seen else 0
    return SiteFeatures(
        frp_mean=site.frp_mean,
        frp_max=site.frp_max,
        frp_cv=site.frp_cv,
        brightness_max=site.brightness_max,
        confidence=site.best_confidence,
        recurrence_days=site.recurrence_days,
        detection_count=site.detection_count,
        night_fraction=site.night_fraction,
        site_age_days=age_days,
        dist_industrial_m=site.dist_industrial_m,
        industrial_group=site.industrial_group,
        land_context=site.land_context,
    )
