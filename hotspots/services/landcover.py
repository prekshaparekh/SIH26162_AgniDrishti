"""ESA WorldCover 10 m land cover lookup.

OpenStreetMap land-use polygons leave large gaps -- in our first statewide run,
56% of sites fell outside any mapped polygon and could not be classified at all.
WorldCover has no gaps: it is a wall-to-wall 10 m raster for the whole planet.

The tiles are Cloud Optimized GeoTIFFs served with HTTP range support, so they are
read remotely a few pixels at a time rather than downloaded. The four tiles
covering Gujarat total about 360 MB; the reads we actually need are a few KB.
"""
from __future__ import annotations

import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)

WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"

# GDAL tuning for remote COG access: without these it lists the whole bucket
# directory on every open, which is slow and unnecessary.
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "3")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
# Without these a stalled S3 connection hangs the read forever: GDAL retries a
# failed request but waits indefinitely on one that merely stops sending. An
# ingest run was observed sitting at 0% CPU with no open sockets, which is a poor
# way for a scheduled job -- or a live demo -- to behave. Fail fast instead; the
# caller already falls back to the OSM land-use layer.
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "30")
os.environ.setdefault("GDAL_HTTP_CONNECTTIMEOUT", "10")
os.environ.setdefault("VSI_CACHE", "TRUE")

# ESA WorldCover class codes mapped onto our LandContext values.
WORLDCOVER_CLASSES = {
    10: "tree_cover",      # Tree cover
    20: "grass_shrub",     # Shrubland
    30: "grass_shrub",     # Grassland
    40: "cropland",        # Cropland
    50: "built_up",        # Built-up
    60: "bare",            # Bare / sparse vegetation
    70: "bare",            # Snow and ice
    80: "water",           # Permanent water bodies
    90: "grass_shrub",     # Herbaceous wetland -- vegetated, and it burns
    95: "tree_cover",      # Mangroves
    100: "grass_shrub",    # Moss and lichen
}

TILE_SIZE_DEG = 3

# Nominal VIIRS pixel size. The land cover under a detection is read across this
# whole square rather than at its centre point.
VIIRS_FOOTPRINT_M = 375.0

# Classes the rules treat as industrial ground. Bare counts here because a furnace
# yard, a slag heap and a quarry all read as bare -- but see BUILT_ONLY: a fire
# needs something to burn, and bare ground on its own is not evidence of that.
BUILT_CLASSES = ("built_up", "bare")
BUILT_ONLY = ("built_up",)


def tile_name(lat: float, lon: float) -> str:
    """WorldCover tiles are 3x3 degrees, named after their south-west corner."""
    tile_lat = math.floor(lat / TILE_SIZE_DEG) * TILE_SIZE_DEG
    tile_lon = math.floor(lon / TILE_SIZE_DEG) * TILE_SIZE_DEG
    ns = "N" if tile_lat >= 0 else "S"
    ew = "E" if tile_lon >= 0 else "W"
    return f"{ns}{abs(tile_lat):02d}{ew}{abs(tile_lon):03d}"


def tile_url(name: str) -> str:
    return f"{WORLDCOVER_BASE}/ESA_WorldCover_10m_2021_v200_{name}_Map.tif"


def _summarise(block) -> tuple[str, float, float]:
    """Majority class, industrial-ground fraction, and built-up-only fraction."""
    from collections import Counter

    values = [int(v) for v in block.flatten() if v]
    if not values:
        return "unknown", 0.0, 0.0
    classes = [WORLDCOVER_CLASSES.get(v, "unknown") for v in values]
    counts = Counter(classes)
    total = len(classes)
    built = sum(counts[c] for c in BUILT_CLASSES) / total
    built_only = sum(counts[c] for c in BUILT_ONLY) / total
    return counts.most_common(1)[0][0], built, built_only


class WorldCoverProvider:
    """Samples land cover for a batch of coordinates.

    Points are grouped by tile so each raster is opened once, regardless of how
    many sites fall inside it.
    """

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else None

    def _source(self, name: str) -> str:
        """Prefer a locally cached tile; otherwise stream it over HTTP."""
        if self.cache_dir:
            local = self.cache_dir / f"ESA_WorldCover_10m_2021_v200_{name}_Map.tif"
            if local.exists():
                return str(local)
        return f"/vsicurl/{tile_url(name)}"

    def sample(
        self, points: list[tuple[float, float]], footprint_m: float = VIIRS_FOOTPRINT_M
    ) -> list[tuple[str, float, float]]:
        """Land cover across each point's detection footprint.

        Returns ``(majority_class, built_fraction, built_only_fraction)`` per
        point, in input order. ``built_fraction`` is the share that is built-up or
        bare -- industrial ground as Rule 2 understands it. ``built_only_fraction``
        excludes bare, because a fire needs structures to burn and bare ground on
        its own is not evidence of any.

        **Why a footprint and not a point.** This method used to read a single
        10 m pixel at the detection centroid. A VIIRS detection covers about
        375 m -- some 14 hectares -- and at an industrial site, where buildings,
        bare yard and trees along the fence sit within one pixel, that single
        reading is close to a coin flip. Measured across the 280 sites within 3 km
        of mapped industry, the centre pixel disagreed with the footprint majority
        28% of the time, and 17 sites whose footprint was majority built-up were
        stored as vegetation. Because the rules gate on land cover, that did not
        merely lower confidence -- it put the industrial classes out of reach.

        One windowed read per point replaces 10 m guesswork with the whole
        footprint, and costs no more requests than the old point sampling did.
        """
        import rasterio
        from rasterio.windows import from_bounds

        results: list[tuple[str, float, float]] = [("unknown", 0.0, 0.0)] * len(points)
        by_tile: dict[str, list[int]] = {}
        for index, (lat, lon) in enumerate(points):
            by_tile.setdefault(tile_name(lat, lon), []).append(index)

        half = footprint_m / 2.0
        for name, indices in by_tile.items():
            source = self._source(name)
            try:
                with rasterio.open(source) as dataset:
                    for index in indices:
                        lat, lon = points[index]
                        dlat = half / 111_320.0
                        dlon = half / (111_320.0 * max(0.01, math.cos(math.radians(lat))))
                        window = from_bounds(
                            lon - dlon, lat - dlat, lon + dlon, lat + dlat, dataset.transform
                        )
                        # boundless reads pad with 0, which is also WorldCover's
                        # nodata, so padding and genuine gaps drop out together.
                        block = dataset.read(1, window=window, boundless=True, fill_value=0)
                        results[index] = _summarise(block)
                logger.info("WorldCover %s: read %d footprints", name, len(indices))
            except Exception as exc:
                # A missing or unreachable tile must not abort ingestion; those
                # sites simply fall back to the OSM land-use layer.
                logger.warning("WorldCover tile %s unavailable (%s)", name, exc)

        return results
