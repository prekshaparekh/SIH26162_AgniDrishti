"""Turn a stored Event into the feature vector the classifier consumes."""
from __future__ import annotations

from .base import EventFeatures


def extract(event, site=None) -> EventFeatures:
    """Build the vector for one episode.

    ``site`` may be passed explicitly so the caller can supply an in-memory site
    whose roll-up fields have just been recomputed but not yet written, which is
    exactly the state the ingestion pipeline is in when it classifies.
    """
    site = site if site is not None else event.site
    site_age = (site.last_seen - site.first_seen).days if site.first_seen else 0
    return EventFeatures(
        duration_days=event.duration_days,
        active_days=event.active_days,
        density=event.density,
        detection_count=event.detection_count,
        frp_mean=event.frp_mean,
        frp_max=event.frp_max,
        frp_cv=event.frp_cv,
        brightness_max=event.brightness_max,
        night_fraction=event.night_fraction,
        confidence=event.best_confidence,
        gap_before_days=event.gap_before_days,
        is_ongoing=event.is_ongoing,
        dist_industrial_m=site.dist_industrial_m,
        industrial_group=site.industrial_group,
        land_context=site.land_context,
        landcover_frac_builtup=site.landcover_frac_builtup,
        site_event_count=site.event_count,
        site_recurrence_days=site.recurrence_days,
        site_max_event_duration=site.max_event_duration,
        site_age_days=site_age,
    )
