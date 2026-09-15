"""Client for the NASA FIRMS active fire / thermal anomaly API.

FIRMS serves CSV over a simple URL scheme. The two constraints that shape this
client are that a single request covers at most 10 days, and that near-real-time
products only reach back about two months -- older data needs the standard
processing (``_SP``) archive.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
PUBLIC_BASE = "https://firms.modaps.eosdis.nasa.gov/data/active_fire"

# Regional standard products, published openly and without an API key. They cover
# a rolling 7-day window, against the 90 days the keyed API can reach. Used so the
# pipeline is demonstrable before a MAP_KEY is configured.
PUBLIC_FEEDS = {
    "VIIRS_SNPP": f"{PUBLIC_BASE}/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_{{region}}_{{span}}.csv",
    "VIIRS_NOAA20": f"{PUBLIC_BASE}/noaa-20-viirs-c2/csv/J1_VIIRS_C2_{{region}}_{{span}}.csv",
    "VIIRS_NOAA21": f"{PUBLIC_BASE}/noaa-21-viirs-c2/csv/J2_VIIRS_C2_{{region}}_{{span}}.csv",
}
HEADERS = {"User-Agent": "AgniDrishti/0.1 (SIH prototype; thermal anomaly classification)"}
MAX_DAYS_PER_REQUEST = 10
REQUEST_TIMEOUT = 120

# VIIRS is the default: 375 m pixels against MODIS's 1 km, and more detections.
DEFAULT_SOURCE = "VIIRS_SNPP_NRT"


class FirmsError(RuntimeError):
    """Raised when FIRMS returns something that is not usable CSV."""


@dataclass
class FirmsRecord:
    latitude: float
    longitude: float
    acq_date: date
    acq_time: str
    frp: float
    confidence: str
    daynight: str
    satellite: str
    instrument: str
    bright_ti4: float | None = None
    bright_ti5: float | None = None


def _parse_float(value: str | None) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_csv(text: str) -> list[FirmsRecord]:
    """Parse a FIRMS CSV payload into records.

    Handles both VIIRS (``bright_ti4``/``bright_ti5``) and MODIS (``brightness``/
    ``bright_t31``) column naming so that adding MODIS later does not require a
    second parser.
    """
    stripped = text.lstrip()
    if not stripped or not stripped.lower().startswith("latitude"):
        # FIRMS reports errors as plain text rather than an HTTP error status.
        raise FirmsError(f"Unexpected response from FIRMS: {stripped[:300]!r}")

    records: list[FirmsRecord] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            acq = date.fromisoformat(row["acq_date"])
        except (KeyError, ValueError):
            continue
        records.append(
            FirmsRecord(
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
                acq_date=acq,
                acq_time=str(row.get("acq_time", "")).zfill(4),
                frp=_parse_float(row.get("frp")) or 0.0,
                confidence=(row.get("confidence") or "").strip().lower(),
                daynight=(row.get("daynight") or "").strip().upper()[:1],
                satellite=(row.get("satellite") or "").strip(),
                instrument=(row.get("instrument") or "").strip(),
                bright_ti4=_parse_float(row.get("bright_ti4") or row.get("brightness")),
                bright_ti5=_parse_float(row.get("bright_ti5") or row.get("bright_t31")),
            )
        )
    return records


def fetch(
    map_key: str,
    bbox: tuple[float, float, float, float],
    days: int = 90,
    source: str = DEFAULT_SOURCE,
    end: date | None = None,
) -> list[FirmsRecord]:
    """Fetch detections for a bounding box, chunked to respect the 10-day limit.

    ``bbox`` is (lon_min, lat_min, lon_max, lat_max), matching the order FIRMS
    expects (west, south, east, north).
    """
    if not map_key:
        raise FirmsError(
            "No FIRMS MAP_KEY configured. Get one free at "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and set FIRMS_MAP_KEY in .env"
        )

    area = ",".join(str(round(v, 4)) for v in bbox)
    end = end or date.today()
    start = end - timedelta(days=days)

    records: list[FirmsRecord] = []
    cursor = start
    while cursor < end:
        span = min(MAX_DAYS_PER_REQUEST, (end - cursor).days)
        url = f"{BASE_URL}/{map_key}/{source}/{area}/{span}/{cursor.isoformat()}"
        logger.info("FIRMS request: %s %s +%sd", source, cursor, span)
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            chunk = parse_csv(response.text)
        except FirmsError as exc:
            # One bad window should not abort a 90-day backfill: near-real-time
            # products simply have no data beyond their retention period.
            logger.warning("Skipping window starting %s: %s", cursor, exc)
            chunk = []
        except requests.RequestException as exc:
            logger.warning("Network error for window starting %s: %s", cursor, exc)
            chunk = []
        records.extend(chunk)
        cursor += timedelta(days=span)

    return records


def fetch_public(
    region: str = "South_Asia",
    span: str = "7d",
    feeds: tuple[str, ...] = tuple(PUBLIC_FEEDS),
) -> list[FirmsRecord]:
    """Fetch the open regional VIIRS feeds, no API key required.

    All three VIIRS platforms are pulled and merged. Suomi-NPP, NOAA-20 and
    NOAA-21 cross at different local times, so combining them materially increases
    the number of observations per day -- which matters when the available window
    is only a week long and recurrence has to be estimated from it.
    """
    records: list[FirmsRecord] = []
    for name in feeds:
        url = PUBLIC_FEEDS[name].format(region=region, span=span)
        try:
            logger.info("FIRMS public feed: %s", name)
            response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            chunk = parse_csv(response.text)
            logger.info("  %s -> %d records", name, len(chunk))
            records.extend(chunk)
        except (requests.RequestException, FirmsError) as exc:
            logger.warning("Public feed %s failed: %s", name, exc)
    return records


def load_csv_file(path: str) -> list[FirmsRecord]:
    """Load detections from a FIRMS CSV downloaded manually.

    Provided so the pipeline can be demonstrated without network access or an API
    key, using an archive export from the FIRMS download page.
    """
    with open(path, encoding="utf-8") as handle:
        return parse_csv(handle.read())
