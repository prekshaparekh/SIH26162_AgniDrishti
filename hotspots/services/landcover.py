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


def tile_name(lat: float, lon: float) -> str:
    """WorldCover tiles are 3x3 degrees, named after their south-west corner."""
    tile_lat = math.floor(lat / TILE_SIZE_DEG) * TILE_SIZE_DEG
    tile_lon = math.floor(lon / TILE_SIZE_DEG) * TILE_SIZE_DEG
    ns = "N" if tile_lat >= 0 else "S"
    ew = "E" if tile_lon >= 0 else "W"
    return f"{ns}{abs(tile_lat):02d}{ew}{abs(tile_lon):03d}"


def tile_url(name: str) -> str:
    return f"{WORLDCOVER_BASE}/ESA_WorldCover_10m_2021_v200_{name}_Map.tif"


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

    def sample(self, points: list[tuple[float, float]]) -> list[str]:
        """Return a land context for each (lat, lon), in the same order."""
        import rasterio

        results: list[str] = ["unknown"] * len(points)
        by_tile: dict[str, list[int]] = {}
        for index, (lat, lon) in enumerate(points):
            by_tile.setdefault(tile_name(lat, lon), []).append(index)

        for name, indices in by_tile.items():
            source = self._source(name)
            coords = [(points[i][1], points[i][0]) for i in indices]  # rasterio wants (x, y)
            try:
                with rasterio.open(source) as dataset:
                    for index, values in zip(indices, dataset.sample(coords)):
                        results[index] = WORLDCOVER_CLASSES.get(int(values[0]), "unknown")
                logger.info("WorldCover %s: sampled %d points", name, len(indices))
            except Exception as exc:
                # A missing or unreachable tile must not abort ingestion; those
                # sites simply fall back to the OSM land-use layer.
                logger.warning("WorldCover tile %s unavailable (%s)", name, exc)

        return results
