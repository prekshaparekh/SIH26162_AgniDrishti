"""OpenStreetMap context layers, fetched via the Overpass API and cached on disk.

Two different layers are fetched, and the distinction matters:

1. **Industrial features** -- used to compute ``dist_industrial_m``.
2. **Land-use polygons** -- used to determine ``land_context``.

They are kept separate on purpose. If land cover were derived from distance to
industry, then the "is it vegetation?" rule and the "is it industrial?" rule would
collapse into a single distance test, and the classifier would be re-stating its
own input. Land context must come from independently mapped land-use geometry.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests
from shapely.geometry import Polygon, shape

logger = logging.getLogger(__name__)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
REQUEST_TIMEOUT = 300
MAX_ATTEMPTS = 3

# The OSM API usage policy requires a descriptive User-Agent identifying the
# application. Requests sent with the default library agent are refused with a
# 406, so this header is a requirement rather than a nicety.
HEADERS = {
    "User-Agent": "AgniDrishti/0.1 (SIH prototype; industrial thermal anomaly classification)",
    "Accept": "application/json",
}

INDUSTRIAL_QUERY = """
[out:json][timeout:180];
(
  nwr["landuse"="industrial"]({bbox});
  nwr["landuse"="landfill"]({bbox});
  nwr["landuse"="quarry"]({bbox});
  nwr["man_made"="works"]({bbox});
  nwr["man_made"="flare"]({bbox});
  nwr["man_made"="kiln"]({bbox});
  nwr["power"="plant"]({bbox});
  nwr["industrial"]({bbox});
);
out center tags;
"""

LANDUSE_QUERY = """
[out:json][timeout:180];
(
  way["landuse"~"^(farmland|farm|orchard|vineyard|allotments|meadow|grass|forest|residential|commercial|retail|industrial|military|construction|quarry|landfill|basin|reservoir)$"]({bbox});
  way["natural"~"^(wood|scrub|grassland|heath|water|bare_rock|sand|beach)$"]({bbox});
);
out geom;
"""


def _overpass(query: str) -> dict:
    """Run an Overpass query, trying mirrors in turn.

    The main instance is frequently rate limited, so a fallback endpoint keeps the
    ingestion pipeline usable during a demo.
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                logger.info("Overpass query (attempt %d) -> %s", attempt, endpoint)
                response = requests.post(
                    endpoint, data={"data": query}, headers=HEADERS, timeout=REQUEST_TIMEOUT
                )
                # 429 means this mirror is busy, not that the query is wrong;
                # move on to the next mirror rather than giving up.
                if response.status_code in (429, 504):
                    logger.warning("%s is rate limited (%s)", endpoint, response.status_code)
                    last_error = RuntimeError(f"{endpoint} returned {response.status_code}")
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)
                last_error = exc
        if attempt < MAX_ATTEMPTS:
            backoff = 5 * attempt
            logger.info("All mirrors busy; retrying in %ds", backoff)
            time.sleep(backoff)
    raise RuntimeError(f"All Overpass endpoints failed: {last_error}")


def _bbox_str(bbox: tuple[float, float, float, float]) -> str:
    """Overpass wants (south, west, north, east); our bboxes are (W, S, E, N)."""
    lon_min, lat_min, lon_max, lat_max = bbox
    return f"{lat_min},{lon_min},{lat_max},{lon_max}"


# --- tag interpretation --------------------------------------------------------

PETRO_HINTS = ("refinery", "petrochemical", "petroleum", "oil", "chemical", "lng", "gas")
METAL_HINTS = ("steel", "foundry", "smelter", "metal", "aluminium", "aluminum", "iron")


def classify_industrial(tags: dict) -> str:
    """Collapse an OSM tag set into one of the six coarse industrial groups."""
    industrial = (tags.get("industrial") or "").lower()
    name = (tags.get("name") or "").lower()
    landuse = (tags.get("landuse") or "").lower()
    man_made = (tags.get("man_made") or "").lower()

    if man_made == "flare" or any(h in industrial for h in PETRO_HINTS) or any(
        h in name for h in PETRO_HINTS
    ):
        return "petro_chemical"
    if tags.get("power") == "plant":
        return "power_generation"
    if any(h in industrial for h in METAL_HINTS) or any(h in name for h in METAL_HINTS):
        return "metals_heavy"
    if landuse == "landfill" or industrial in ("waste", "scrap_yard", "recycling"):
        return "waste_landfill"
    if landuse == "quarry" or man_made == "kiln" or industrial in ("brickyard", "mine", "quarry"):
        return "extraction_kiln"
    return "light_manufacturing"


LANDUSE_TO_CONTEXT = {
    "farmland": "cropland", "farm": "cropland", "orchard": "cropland",
    "vineyard": "cropland", "allotments": "cropland",
    "forest": "tree_cover",
    "meadow": "grass_shrub", "grass": "grass_shrub",
    "residential": "built_up", "commercial": "built_up", "retail": "built_up",
    "industrial": "built_up", "military": "built_up", "construction": "built_up",
    "quarry": "bare", "landfill": "bare",
    "basin": "water", "reservoir": "water",
}
NATURAL_TO_CONTEXT = {
    "wood": "tree_cover",
    "scrub": "grass_shrub", "grassland": "grass_shrub", "heath": "grass_shrub",
    "water": "water",
    "bare_rock": "bare", "sand": "bare", "beach": "bare",
}


def classify_landuse(tags: dict) -> str | None:
    if tags.get("landuse") in LANDUSE_TO_CONTEXT:
        return LANDUSE_TO_CONTEXT[tags["landuse"]]
    if tags.get("natural") in NATURAL_TO_CONTEXT:
        return NATURAL_TO_CONTEXT[tags["natural"]]
    return None


# --- fetch + cache -------------------------------------------------------------

def fetch_industrial(bbox, cache: Path, refresh: bool = False) -> list[dict]:
    """Industrial features as points (Overpass ``out center`` gives a centroid)."""
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())

    payload = _overpass(INDUSTRIAL_QUERY.format(bbox=_bbox_str(bbox)))
    features = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        if element["type"] == "node":
            lat, lon = element.get("lat"), element.get("lon")
        else:
            centre = element.get("center") or {}
            lat, lon = centre.get("lat"), centre.get("lon")
        if lat is None or lon is None:
            continue
        features.append({
            "osm_id": f"{element['type']}/{element['id']}",
            "lat": lat,
            "lon": lon,
            "name": tags.get("name", ""),
            "group": classify_industrial(tags),
        })

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(features))
    logger.info("Cached %d industrial features -> %s", len(features), cache)
    return features


def fetch_landuse(bbox, cache: Path, refresh: bool = False) -> list[dict]:
    """Land-use polygons, stored as GeoJSON-ish dicts with a land context label."""
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())

    payload = _overpass(LANDUSE_QUERY.format(bbox=_bbox_str(bbox)))
    features = []
    for element in payload.get("elements", []):
        geometry = element.get("geometry")
        if not geometry or len(geometry) < 4:
            continue
        context = classify_landuse(element.get("tags") or {})
        if context is None:
            continue
        ring = [[p["lon"], p["lat"]] for p in geometry]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        features.append({
            "osm_id": f"{element['type']}/{element['id']}",
            "context": context,
            "polygon": ring,
        })

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(features))
    logger.info("Cached %d land-use polygons -> %s", len(features), cache)
    return features


def to_polygons(features: list[dict]) -> list[tuple[Polygon, str]]:
    """Materialise cached land-use records into Shapely polygons."""
    polygons = []
    for feature in features:
        try:
            poly = shape({"type": "Polygon", "coordinates": [feature["polygon"]]})
            if poly.is_valid and not poly.is_empty:
                polygons.append((poly, feature["context"]))
        except Exception:  # malformed geometry from OSM; skip rather than abort
            continue
    return polygons
