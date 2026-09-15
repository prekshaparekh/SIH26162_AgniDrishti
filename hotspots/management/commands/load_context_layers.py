"""Download and cache the OpenStreetMap context layers.

Run this once before ingesting detections. The layers change slowly, so they are
cached on disk and reused; pass --refresh to re-download.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from hotspots.services import osm


class Command(BaseCommand):
    help = "Fetch and cache OSM industrial features and land-use polygons."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bbox",
            choices=["validation", "ingest"],
            default="validation",
            help="Which configured bounding box to fetch (default: validation corridor).",
        )
        parser.add_argument("--refresh", action="store_true", help="Ignore the on-disk cache.")

    def handle(self, *args, **options):
        bbox = (
            settings.VALIDATION_BBOX if options["bbox"] == "validation" else settings.INGEST_BBOX
        )
        data_dir = Path(settings.DATA_DIR)
        self.stdout.write(f"Bounding box ({options['bbox']}): {bbox}")

        self.stdout.write("Fetching industrial features from Overpass...")
        industrial = osm.fetch_industrial(
            bbox, data_dir / f"osm_industrial_{options['bbox']}.json", options["refresh"]
        )
        self.stdout.write(self.style.SUCCESS(f"  {len(industrial)} industrial features"))

        groups: dict[str, int] = {}
        for feature in industrial:
            groups[feature["group"]] = groups.get(feature["group"], 0) + 1
        for group, count in sorted(groups.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"    {group:22s} {count}")

        self.stdout.write("Fetching land-use polygons from Overpass...")
        landuse = osm.fetch_landuse(
            bbox, data_dir / f"osm_landuse_{options['bbox']}.json", options["refresh"]
        )
        self.stdout.write(self.style.SUCCESS(f"  {len(landuse)} land-use polygons"))

        contexts: dict[str, int] = {}
        for feature in landuse:
            contexts[feature["context"]] = contexts.get(feature["context"], 0) + 1
        for context, count in sorted(contexts.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"    {context:22s} {count}")

        self.stdout.write(self.style.SUCCESS("Context layers ready."))
