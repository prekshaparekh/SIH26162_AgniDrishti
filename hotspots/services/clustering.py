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

from ..models import Detection, Event, Site
from .geo import coefficient_of_variation, grid_centre, grid_key

CONFIDENCE_RANK = {"low": 0, "nominal": 1, "high": 2}

# FIRMS is not consistent about this field: the keyed Area API writes
# "low"/"nominal"/"high", the open regional feeds write "l"/"n"/"h", and MODIS
# writes an integer 0-100. Storing whichever spelling happened to arrive meant the
# rules -- which compare against the full words -- silently failed on the short
# form: 27 of 32 low-confidence episodes escaped the R1 abstention, and 8 of 9
# high-confidence ones were denied their confidence bump. Everything is now
# canonicalised on the way in, so downstream code compares against one vocabulary.
CONFIDENCE_ALIASES = {
    "l": "low", "low": "low",
    "n": "nominal", "nominal": "nominal", "": "nominal",
    "h": "high", "high": "high",
}


def normalise_confidence(value: str) -> str:
    """Map any FIRMS confidence spelling onto low / nominal / high."""
    value = (value or "").strip().lower()
    if value.isdigit():  # MODIS numeric confidence
        numeric = int(value)
        return "high" if numeric >= 80 else "nominal" if numeric >= 30 else "low"
    # An unrecognised value is treated as nominal rather than discarded: it is a
    # spelling we have not seen, not evidence that the detection is poor.
    return CONFIDENCE_ALIASES.get(value, "nominal")


def _best_confidence(values: list[str]) -> str:
    """Highest confidence seen, in canonical form."""
    best, best_rank = "low", -1
    for value in values:
        canonical = normalise_confidence(value)
        rank = CONFIDENCE_RANK[canonical]
        if rank > best_rank:
            best, best_rank = canonical, rank
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


def segment_days(days: list, gap_days: int) -> list[list]:
    """Cut a sorted list of dates into runs separated by quiet gaps.

    The entire episode-detection algorithm. Walk the days in order; whenever the
    quiet stretch since the previous detection exceeds ``gap_days``, start a new
    run. Everything else extends the current one.
    """
    if not days:
        return []
    runs = [[days[0]]]
    for previous, day in zip(days, days[1:]):
        if (day - previous).days > gap_days:
            runs.append([day])
        else:
            runs[-1].append(day)
    return runs


def rebuild_site_events(
    site: Site, gap_days: int | None = None, latest_date: date | None = None
) -> list[Event]:
    """Rebuild a site's episodes and roll their statistics up onto the site.

    Returns unsaved ``Event`` rows for the caller to bulk-create, and mutates
    ``site`` in place with the roll-up fields. It does not touch the database, so
    one pass over every site produces a single bulk insert rather than hundreds.
    """
    gap_days = settings.EVENT_GAP_DAYS if gap_days is None else gap_days
    detections = list(site.detections.all())

    if not detections:
        site.event_count = 0
        site.max_event_duration = 0
        site.longest_episode_active_days = 0
        site.mean_gap_days = None
        site.has_ongoing_event = False
        return []

    by_day: dict = defaultdict(list)
    for detection in detections:
        by_day[detection.acq_date].append(detection)

    events: list[Event] = []
    previous_end: date | None = None
    for run in segment_days(sorted(by_day), gap_days):
        start, end = run[0], run[-1]
        span = (end - start).days + 1
        members = [d for day in run for d in by_day[day]]

        frps = [d.frp for d in members if d.frp is not None]
        brightnesses = [d.bright_ti4 for d in members if d.bright_ti4 is not None]
        peak_day = max(run, key=lambda day: max((d.frp or 0.0) for d in by_day[day]))

        events.append(
            Event(
                site=site,
                start_date=start,
                end_date=end,
                duration_days=span,
                active_days=len(run),
                density=len(run) / span,
                detection_count=len(members),
                frp_mean=sum(frps) / len(frps) if frps else 0.0,
                frp_max=max(frps) if frps else 0.0,
                frp_cv=coefficient_of_variation(frps),
                brightness_max=max(brightnesses) if brightnesses else 0.0,
                peak_date=peak_day,
                night_fraction=sum(1 for d in members if d.daynight == "N") / len(members),
                best_confidence=_best_confidence([d.confidence for d in members]),
                gap_before_days=(start - previous_end).days if previous_end else None,
                # An episode is only "closed" once the site has stayed quiet for
                # longer than the gap threshold. Anything more recent than that
                # could still be burning -- we simply have not waited long enough
                # to know.
                is_ongoing=latest_date is not None and (latest_date - end).days <= gap_days,
            )
        )
        previous_end = end

    gaps = [e.gap_before_days for e in events if e.gap_before_days is not None]
    longest = max(events, key=lambda e: e.duration_days)
    site.event_count = len(events)
    site.max_event_duration = longest.duration_days
    site.longest_episode_active_days = longest.active_days
    site.mean_gap_days = sum(gaps) / len(gaps) if gaps else None
    site.has_ongoing_event = any(e.is_ongoing for e in events)
    return events


# Operational priority for the map's one colour per location: how much attention a
# finding warrants, not how confident or how recent it is.
#
# Vegetation and abstention share a tier deliberately. Ranking "vegetation fire"
# above "uncertain" outright let a trivial episode mask a serious one: site #4 near
# Hazira has a 7-day grass fire and a 71-day unexplained burn that the vegetation
# label could not account for, and the site rendered green on the strength of the
# 7-day one. Neither class is actionable on its own, so within the tier the larger
# episode is the more informative thing to show.
SUMMARY_TIERS = {
    "industrial_fire": 0,
    "persistent_source": 1,
    "vegetation_fire": 2,
    "uncertain": 2,
}


def summarise_site_from_events(site: Site, events: list[Event]) -> None:
    """Roll the episode labels up into the site's summary label.

    The map needs one colour per location, but the judgement itself belongs to the
    episode -- a second, independent opinion computed from site-wide averages is
    precisely the ambiguity episodes were introduced to remove. So the summary
    simply promotes one episode's label.

    **Which episode, and why not the most recent.** Taking the latest episode is
    the obvious choice and it is wrong for a screening tool: measured on the
    current build it hid four of the seven detected fires behind whatever quieter
    thing happened next at the same location. A fire inside the observation window
    is the finding that warrants attention, so severity leads and recency only
    breaks ties. The chosen episode's dates go into the evidence, so a June fire is
    never mistaken for an active one, and every episode keeps its own label in the
    panel.
    """
    if not events:
        return

    def rank(event: Event) -> tuple[int, int, int]:
        tier = SUMMARY_TIERS.get(event.label, max(SUMMARY_TIERS.values()) + 1)
        # Lowest tier wins; among equals the longest episode, then the most recent.
        return tier, -event.duration_days, -event.end_date.toordinal()

    chosen = min(events, key=rank)
    site.label = chosen.label
    site.label_confidence = chosen.label_confidence
    site.matched_rule = chosen.matched_rule

    evidence = list(chosen.evidence)
    if len(events) > 1:
        distinct = {e.label for e in events}
        note = (
            f"this location has {len(events)} episodes; the label below describes "
            f"the most significant ({chosen.start_date} to {chosen.end_date})"
        )
        if len(distinct) > 1:
            note += " - other episodes here were classified differently"
        evidence.insert(0, note)
    site.evidence = evidence
