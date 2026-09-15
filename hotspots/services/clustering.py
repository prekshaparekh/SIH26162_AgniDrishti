"""Group detections into persistent sites and derive their temporal features.

This is where the project's central idea is implemented. A single detection cannot
distinguish a refinery flare from an accidental fire -- both are hot, both sit on
industrial land. What separates them is history: a flare recurs at the same
coordinates for months at a stable radiative power, while a fire is an anomaly
against that baseline. Grouping by location is what makes that history visible.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.conf import settings

from ..models import Detection, Site
from .geo import coefficient_of_variation, grid_centre, grid_key

CONFIDENCE_RANK = {"low": 0, "nominal": 1, "n": 1, "high": 2, "h": 2, "l": 0}


def _best_confidence(values: list[str]) -> str:
    """Highest confidence seen at a site.

    VIIRS reports low/nominal/high. MODIS reports 0-100, which is normalised here
    so that both instruments can share one field.
    """
    best, best_rank = "low", -1
    for value in values:
        value = (value or "").strip().lower()
        if value.isdigit():  # MODIS numeric confidence
            numeric = int(value)
            value = "high" if numeric >= 80 else "nominal" if numeric >= 30 else "low"
        rank = CONFIDENCE_RANK.get(value, 1)
        if rank > best_rank:
            best, best_rank = value, rank
    return best


def assign_site_keys(records) -> dict[str, list]:
    """Bucket FIRMS records by the grid cell they fall into."""
    cell = settings.SITE_GRID_DEG
    buckets: dict[str, list] = defaultdict(list)
    for record in records:
        buckets[grid_key(record.latitude, record.longitude, cell)].append(record)
    return buckets


def rebuild_site_features(site: Site, window_days: int | None = None) -> Site:
    """Recompute every derived feature for a site from its stored detections."""
    window_days = window_days or settings.RECURRENCE_WINDOW_DAYS
    detections = list(site.detections.all())
    if not detections:
        return site

    dates = [d.acq_date for d in detections]
    frps = [d.frp for d in detections if d.frp is not None]
    brightnesses = [d.bright_ti4 for d in detections if d.bright_ti4 is not None]

    site.first_seen = min(dates)
    site.last_seen = max(dates)
    site.detection_count = len(detections)

    # Recurrence counts distinct DAYS, not detections. Several satellite passes on
    # one day describe a single day of burning, and counting them separately would
    # make a brief, intensely observed fire look like a persistent source.
    window_start = site.last_seen - timedelta(days=window_days)
    site.recurrence_days = len({d for d in dates if d >= window_start})

    night = sum(1 for d in detections if d.daynight == "N")
    site.night_fraction = night / len(detections)

    site.frp_mean = sum(frps) / len(frps) if frps else 0.0
    site.frp_max = max(frps) if frps else 0.0
    site.frp_cv = coefficient_of_variation(frps)
    site.brightness_max = max(brightnesses) if brightnesses else 0.0
    site.best_confidence = _best_confidence([d.confidence for d in detections])

    # Site coordinates are the mean of member detections rather than the grid
    # centre, so the marker sits on the observed heat, not on a lattice point.
    site.latitude = sum(d.latitude for d in detections) / len(detections)
    site.longitude = sum(d.longitude for d in detections) / len(detections)
    return site


def get_or_create_site(key: str) -> Site:
    cell = settings.SITE_GRID_DEG
    lat, lon = grid_centre(key, cell)
    site, _ = Site.objects.get_or_create(
        grid_key=key,
        defaults={
            "latitude": lat,
            "longitude": lon,
            "first_seen": date.today(),
            "last_seen": date.today(),
        },
    )
    return site
