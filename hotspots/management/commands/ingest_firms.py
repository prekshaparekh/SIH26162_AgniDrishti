"""Fetch thermal anomalies, group them into sites, enrich, and classify.

This is the whole pipeline in one command:

    FIRMS -> cluster by location -> derive temporal features -> attach OSM
    context -> apply the classifier -> store

It is idempotent. Re-running it adds new detections and recomputes every derived
feature, so it can be run on a schedule without producing duplicates.
"""
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone

from classification.features import extract
from classification.rules import EventRuleClassifier
from hotspots.models import Detection, Event, Site
from hotspots.services import clustering, firms, osm
from hotspots.services.enrichment import ContextEnricher
from hotspots.services.landcover import WorldCoverProvider
from hotspots.services.geo import in_bbox


class Command(BaseCommand):
    help = "Ingest FIRMS detections, then enrich and classify the resulting sites."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90, help="Days of history (default 90).")
        parser.add_argument(
            "--source", default=firms.DEFAULT_SOURCE,
            help="FIRMS product for the public-feed path (keyed path auto-selects NRT/archive).",
        )
        parser.add_argument("--bbox", choices=["validation", "ingest"], default="validation")
        parser.add_argument("--csv", help="Load from a local FIRMS CSV instead of the API.")
        parser.add_argument(
            "--public",
            action="store_true",
            help="Use the open 7-day regional feeds instead of the keyed API (no MAP_KEY needed).",
        )
        parser.add_argument(
            "--no-worldcover",
            action="store_true",
            help="Skip ESA WorldCover and use only OSM land-use polygons.",
        )
        parser.add_argument(
            "--classify-only",
            action="store_true",
            help="Skip fetching; re-enrich and re-classify existing sites.",
        )

    def handle(self, *args, **options):
        bbox = (
            settings.VALIDATION_BBOX if options["bbox"] == "validation" else settings.INGEST_BBOX
        )
        data_dir = Path(settings.DATA_DIR)

        window_days = options["days"]
        if not options["classify_only"]:
            records, window_days = self._load_records(options, bbox)
            self.stdout.write(f"Fetched {len(records)} detections.")
            records = [r for r in records if in_bbox(r.latitude, r.longitude, bbox)]
            self.stdout.write(
                self.style.SUCCESS(f"{len(records)} inside the bounding box.")
            )
            if records:
                self._store(records)

        self._enrich_and_classify(
            bbox, data_dir, options["bbox"], window_days,
            use_worldcover=not options["no_worldcover"],
        )

    # --- fetch -----------------------------------------------------------------

    def _load_records(self, options, bbox):
        """Returns (records, effective_window_days).

        The window matters downstream: recurrence thresholds are expressed as a
        fraction of the observation period, so the classifier has to be told how
        long that period actually was.
        """
        if options["csv"]:
            self.stdout.write(f"Loading detections from {options['csv']}")
            return firms.load_csv_file(options["csv"]), options["days"]

        use_public = options["public"] or not settings.FIRMS_MAP_KEY
        if use_public:
            if not settings.FIRMS_MAP_KEY:
                self.stdout.write(
                    self.style.WARNING(
                        "No FIRMS_MAP_KEY set - using the open 7-day regional feeds. "
                        "Set a key in .env to reach the full 90-day archive."
                    )
                )
            return firms.fetch_public(region="South_Asia", span="7d"), 7

        try:
            return (
                firms.fetch(
                    map_key=settings.FIRMS_MAP_KEY,
                    bbox=bbox,
                    days=options["days"],
                ),
                options["days"],
            )
        except firms.FirmsError as exc:
            raise CommandError(str(exc)) from exc

    # --- store + cluster -------------------------------------------------------

    @transaction.atomic
    def _store(self, records):
        buckets = clustering.assign_site_keys(records)
        self.stdout.write(f"Grouped into {len(buckets)} candidate sites.")

        created = 0
        for key, site_records in buckets.items():
            site = clustering.get_or_create_site(key)
            existing = {
                (d.acq_date, d.acq_time, d.satellite)
                for d in site.detections.all().only("acq_date", "acq_time", "satellite")
            }
            new_rows = []
            for record in site_records:
                signature = (record.acq_date, record.acq_time, record.satellite)
                if signature in existing:
                    continue
                existing.add(signature)
                new_rows.append(
                    Detection(
                        site=site,
                        latitude=record.latitude,
                        longitude=record.longitude,
                        acq_date=record.acq_date,
                        acq_time=record.acq_time,
                        bright_ti4=record.bright_ti4,
                        bright_ti5=record.bright_ti5,
                        frp=record.frp,
                        confidence=record.confidence,
                        daynight=record.daynight,
                        satellite=record.satellite,
                        instrument=record.instrument,
                    )
                )
            if new_rows:
                Detection.objects.bulk_create(new_rows, ignore_conflicts=True)
                created += len(new_rows)

        self.stdout.write(self.style.SUCCESS(f"Stored {created} new detections."))

    # --- enrich + classify -----------------------------------------------------

    def _enrich_and_classify(
        self, bbox, data_dir, bbox_name, window_days=90, use_worldcover=True
    ):
        industrial_cache = data_dir / f"osm_industrial_{bbox_name}.json"
        landuse_cache = data_dir / f"osm_landuse_{bbox_name}.json"
        if not industrial_cache.exists():
            raise CommandError(
                f"Context layers missing ({industrial_cache}). "
                "Run: python manage.py load_context_layers"
            )

        industrial = osm.fetch_industrial(bbox, industrial_cache)
        landuse = osm.to_polygons(osm.fetch_landuse(bbox, landuse_cache))
        self.stdout.write(
            f"Context: {len(industrial)} industrial features, {len(landuse)} land-use polygons."
        )
        enricher = ContextEnricher(industrial, landuse)

        # The nominal window is what we asked for; the observed span is what the
        # feed actually returned. Recurrence can never exceed the latter, so the
        # thresholds must be derived from it or they misrepresent the evidence.
        span = Detection.objects.aggregate(lo=Min("acq_date"), hi=Max("acq_date"))
        if span["lo"] and span["hi"]:
            observed = (span["hi"] - span["lo"]).days + 1
            if observed < window_days:
                self.stdout.write(
                    self.style.WARNING(
                        f"Requested {window_days} days but the feed covers {observed} "
                        f"({span['lo']} to {span['hi']}); using the observed span."
                    )
                )
                window_days = observed

        # The most recent day any detection exists for. An episode ending close to
        # this date has not yet been closed by a quiet gap, so it may still be
        # burning; one ending long before it is definitively over.
        latest_date = span["hi"]

        classifier = EventRuleClassifier(window_days=window_days)
        self.stdout.write(
            f"Classifier window: {window_days} days - episodes are sustained at "
            f">= {classifier.sustained_min} days and brief at <= {classifier.brief_max}"
        )

        sites = list(Site.objects.prefetch_related("detections").all())
        total = len(sites)
        self.stdout.write(f"Enriching and classifying {total} sites...")

        # Land cover is sampled for every site in one batch, because WorldCover
        # groups points by raster tile and opens each tile once. Doing it per site
        # would reopen the same remote raster hundreds of times.
        land_cover: list[tuple[str, float]] = [("unknown", 0.0)] * total
        if use_worldcover and total:
            self.stdout.write("Sampling ESA WorldCover (10 m)...")
            try:
                land_cover = WorldCoverProvider(cache_dir=data_dir).sample(
                    [(s.latitude, s.longitude) for s in sites]
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"WorldCover unavailable ({exc}); falling back to OSM.")
                )

        counts: dict[str, int] = {}
        event_counts: dict[str, int] = {}
        land_sources = {"worldcover": 0, "osm": 0, "none": 0}
        updated = []
        all_events: list[Event] = []
        for index, site in enumerate(sites, start=1):
            clustering.rebuild_site_features(site)
            # Episodes are cut here but classified further down: an episode cannot
            # be judged before we know what is under it and what is near it.
            events = clustering.rebuild_site_events(site, latest_date=latest_date)

            match = enricher.nearest_industrial(site.latitude, site.longitude)
            site.dist_industrial_m = match.distance_m
            site.industrial_group = match.group
            site.industrial_name = match.name[:200]
            # WorldCover is wall-to-wall, so it answers for almost every site.
            # OSM land-use remains the fallback for the rare gap.
            context, built_fraction = land_cover[index - 1]
            if context != "unknown":
                land_sources["worldcover"] += 1
            else:
                # The OSM land-use fallback is polygon-based and cannot report a
                # footprint fraction, so the rules fall back to the class alone.
                context = enricher.land_context(site.latitude, site.longitude)
                built_fraction = 0.0
                land_sources["osm" if context != "unknown" else "none"] += 1
            site.land_context = context
            site.landcover_frac_builtup = built_fraction
            site.in_validation_corridor = in_bbox(
                site.latitude, site.longitude, settings.VALIDATION_BBOX
            )

            # Now that the site carries its context, judge each episode on its
            # own, then summarise the location from what they say.
            for event in events:
                result = classifier.predict(extract(event, site))
                event.label = result.label
                event.label_confidence = result.confidence
                event.evidence = result.evidence
                event.matched_rule = result.matched_rule
                event_counts[result.label] = event_counts.get(result.label, 0) + 1

            clustering.summarise_site_from_events(site, events)
            site.enriched_at = timezone.now()

            counts[site.label] = counts.get(site.label, 0) + 1
            all_events.extend(events)
            updated.append(site)

            if index % 500 == 0:
                self.stdout.write(f"  {index}/{total}")

        Site.objects.bulk_update(
            updated,
            [
                "latitude", "longitude", "first_seen", "last_seen", "detection_count",
                "recurrence_days", "night_fraction", "frp_mean", "frp_max", "frp_cv",
                "brightness_max", "best_confidence", "dist_industrial_m", "industrial_group",
                "industrial_name", "land_context", "landcover_frac_builtup",
                "label", "label_confidence", "evidence",
                "matched_rule", "in_validation_corridor", "enriched_at",
                "event_count", "max_event_duration", "longest_episode_active_days",
                "mean_gap_days", "has_ongoing_event",
            ],
            batch_size=500,
        )

        # Episodes are rebuilt wholesale rather than appended to. Detections can
        # arrive late and close a gap that previously split one burn in two, so
        # incremental updates would leave stale boundaries behind.
        Event.objects.all().delete()
        Event.objects.bulk_create(all_events, batch_size=1000)

        ongoing = sum(1 for s in updated if s.has_ongoing_event)
        multi = sum(1 for s in updated if s.event_count > 1)
        longest = max((s.max_event_duration for s in updated), default=0)
        self.stdout.write(
            f"Episodes: {len(all_events)} across {total} sites "
            f"({multi} sites with more than one, {ongoing} with an open episode, "
            f"longest run {longest} days)."
        )
        self.stdout.write(
            f"Land cover source: {land_sources['worldcover']} WorldCover, "
            f"{land_sources['osm']} OSM fallback, {land_sources['none']} unresolved."
        )
        n_events = len(all_events)
        self.stdout.write(self.style.SUCCESS(f"Episodes classified ({n_events}):"))
        for label, count in sorted(event_counts.items(), key=lambda kv: -kv[1]):
            share = 100 * count / n_events if n_events else 0
            self.stdout.write(f"  {label:20s} {count:6d}  ({share:5.1f}%)")

        self.stdout.write(self.style.SUCCESS(f"Site summary labels ({total}):"))
        for label, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            share = 100 * count / total if total else 0
            self.stdout.write(f"  {label:20s} {count:6d}  ({share:5.1f}%)")
