"""Attach geospatial context to a coordinate: what is near it, and what is under it."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from shapely.geometry import Point
from shapely.strtree import STRtree

from .geo import haversine_m

logger = logging.getLogger(__name__)

# Land contexts ordered from most to least built. Used only to break ties when a
# point falls inside overlapping polygons of equal area.
CONTEXT_PRIORITY = ["built_up", "bare", "cropland", "tree_cover", "grass_shrub", "water"]


@dataclass
class IndustrialMatch:
    distance_m: float | None
    group: str
    name: str


class ContextEnricher:
    """Spatial lookups against cached OpenStreetMap layers.

    Uses R-tree indexes so that enrichment stays linear in the number of sites
    rather than quadratic against every mapped feature.
    """

    def __init__(self, industrial: list[dict], landuse_polygons: list[tuple]):
        self.industrial = industrial
        self._industrial_points = [Point(f["lon"], f["lat"]) for f in industrial]
        self._industrial_tree = STRtree(self._industrial_points) if industrial else None

        self.landuse = landuse_polygons
        self._landuse_tree = (
            STRtree([poly for poly, _ in landuse_polygons]) if landuse_polygons else None
        )

    # --- nearest industrial feature -------------------------------------------

    def nearest_industrial(self, lat: float, lon: float) -> IndustrialMatch:
        """Distance in metres to the nearest mapped industrial feature.

        Candidates are gathered with a planar bounding-box query, then ranked by
        true great-circle distance. Ranking on degrees alone would be biased,
        because a degree of longitude is about 7% shorter than a degree of
        latitude at this location.
        """
        if self._industrial_tree is None:
            return IndustrialMatch(None, "none", "")

        point = Point(lon, lat)
        for radius_deg in (0.05, 0.25, 1.0):  # ~5 km, ~25 km, ~100 km
            candidates = self._industrial_tree.query(point.buffer(radius_deg))
            if len(candidates) == 0:
                continue
            best_index, best_distance = None, float("inf")
            for index in candidates:
                feature = self.industrial[int(index)]
                distance = haversine_m(lat, lon, feature["lat"], feature["lon"])
                if distance < best_distance:
                    best_index, best_distance = int(index), distance
            if best_index is not None:
                feature = self.industrial[best_index]
                return IndustrialMatch(best_distance, feature["group"], feature["name"])

        return IndustrialMatch(None, "none", "")

    # --- land cover under the point -------------------------------------------

    def land_context(self, lat: float, lon: float) -> str:
        """Land context from independently mapped land-use polygons.

        Note this is derived from OSM geometry, never from industrial distance --
        keeping the two independent is what stops the classifier from restating
        its own input.
        """
        if self._landuse_tree is None:
            return "unknown"

        point = Point(lon, lat)
        containing = [
            (self.landuse[int(i)][0].area, self.landuse[int(i)][1])
            for i in self._landuse_tree.query(point)
            if self.landuse[int(i)][0].contains(point)
        ]
        if not containing:
            return "unknown"

        # The smallest containing polygon is the most specific description of the
        # location: a factory footprint inside a larger residential zone wins.
        smallest_area = min(area for area, _ in containing)
        best = [ctx for area, ctx in containing if area == smallest_area]
        if len(best) == 1:
            return best[0]
        return min(best, key=lambda c: CONTEXT_PRIORITY.index(c) if c in CONTEXT_PRIORITY else 99)
