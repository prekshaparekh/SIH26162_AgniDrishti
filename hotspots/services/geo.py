"""Small geodesy helpers.

Deliberately dependency-light. The prototype needs distances and point-in-polygon
tests, neither of which justifies pulling in GDAL through GeoPandas or Rasterio --
those carry heavy C dependencies that are a poor trade for a handful of operations.
"""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def grid_key(lat: float, lon: float, cell_deg: float) -> str:
    """Snap a coordinate to a fixed grid and return a stable string key.

    Detections falling in the same cell are treated as the same physical site, which
    is what lets recurrence accumulate per location rather than per satellite pixel.
    """
    gy = math.floor(lat / cell_deg)
    gx = math.floor(lon / cell_deg)
    return f"{gy}:{gx}"


def grid_centre(key: str, cell_deg: float) -> tuple[float, float]:
    gy, gx = (int(p) for p in key.split(":"))
    return (gy + 0.5) * cell_deg, (gx + 0.5) * cell_deg


def in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    """bbox is (lon_min, lat_min, lon_max, lat_max)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def coefficient_of_variation(values: list[float]) -> float:
    """Standard deviation divided by the mean.

    Used as a stability measure for Fire Radiative Power: a gas flare burns at a
    consistent rate, an accidental fire does not.
    """
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return 0.0
    mean = sum(clean) / len(clean)
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in clean) / (len(clean) - 1)
    return math.sqrt(variance) / mean
