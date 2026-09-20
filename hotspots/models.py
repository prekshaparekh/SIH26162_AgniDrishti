"""Data model for thermal anomaly detections and the persistent sites they form.

The distinction between the three tables is the core modelling idea of the project:

* A ``Detection`` is one thermal anomaly reported by FIRMS at one moment in time.
* A ``Site`` is a *location* that has produced one or more detections over time.
* An ``Event`` is one continuous burning episode at a site -- a run of detections
  bounded by quiet gaps on either side.

The third table exists because site-level statistics alone cannot tell a furnace
that ran for two months from a handful of unrelated one-day fires: both collapse
into the same recurrence count. Only once the timeline is cut into episodes can
the system say "the longest continuous episode here lasted 55 days".

Classification happens at the ``Event`` level. The feature that separates an
industrial fire from a routine gas flare is temporal -- how long a burn ran and how
densely -- and that is a property of an episode, not of a location. A site that
runs a furnace for two months and then suffers an accident produces one of each,
and labelling the location as a whole can only report one of them.

``Site.label`` is a summary rolled up from the episodes so the map has one colour
per location; it is never computed independently.
"""
from django.db import models


class LandContext(models.TextChoices):
    """Land cover categories, named to match ESA WorldCover classes.

    The prototype derives these from OpenStreetMap land-use polygons. The names
    deliberately mirror WorldCover so that swapping in the 10 m raster later is a
    change of provider, not a change of schema.
    """

    BUILT_UP = "built_up", "Built-up"
    CROPLAND = "cropland", "Cropland"
    TREE_COVER = "tree_cover", "Tree cover"
    GRASS_SHRUB = "grass_shrub", "Grassland / shrubland"
    BARE = "bare", "Bare / sparse vegetation"
    WATER = "water", "Water"
    UNKNOWN = "unknown", "Unknown"


class IndustrialGroup(models.TextChoices):
    """Coarse industrial categories.

    OpenStreetMap carries dozens of industrial tags. With only a few hundred
    training examples a high-cardinality categorical fragments into splits too
    thin to learn from, so tags are collapsed into these six groups.
    """

    PETRO_CHEMICAL = "petro_chemical", "Petrochemical / refinery"
    POWER_GENERATION = "power_generation", "Power generation"
    METALS_HEAVY = "metals_heavy", "Metals / heavy manufacturing"
    LIGHT_MANUFACTURING = "light_manufacturing", "Light manufacturing / warehouse"
    WASTE_LANDFILL = "waste_landfill", "Waste / landfill"
    EXTRACTION_KILN = "extraction_kiln", "Extraction / quarry / kiln"
    NONE = "none", "No mapped feature nearby"


class HotspotClass(models.TextChoices):
    INDUSTRIAL_FIRE = "industrial_fire", "Industrial fire"
    PERSISTENT_SOURCE = "persistent_source", "Persistent thermal source"
    VEGETATION_FIRE = "vegetation_fire", "Vegetation fire"
    UNCERTAIN = "uncertain", "Other / uncertain"


CLASS_COLOURS = {
    HotspotClass.INDUSTRIAL_FIRE: "#dc2626",
    HotspotClass.PERSISTENT_SOURCE: "#ea580c",
    HotspotClass.VEGETATION_FIRE: "#16a34a",
    HotspotClass.UNCERTAIN: "#9ca3af",
}


class Site(models.Model):
    """A location that has produced thermal anomaly detections."""

    grid_key = models.CharField(max_length=32, unique=True, db_index=True)
    latitude = models.FloatField()
    longitude = models.FloatField()

    # --- temporal features ---
    first_seen = models.DateField()
    last_seen = models.DateField()
    detection_count = models.PositiveIntegerField(default=0)
    recurrence_days = models.PositiveIntegerField(
        default=0, help_text="Distinct days with a detection inside the recurrence window"
    )
    night_fraction = models.FloatField(default=0.0)

    # --- episode structure (rolled up from Event) ---
    # event_count on its own does NOT separate the classes: measured over 90 days
    # the Hazira steel plant and a site with four stray detections both produce
    # three events. max_event_duration is the field that does the separating --
    # 55 days against 6.
    event_count = models.PositiveIntegerField(default=0)
    max_event_duration = models.PositiveIntegerField(
        default=0, help_text="Longest continuous burning episode at this site, in days"
    )
    longest_episode_active_days = models.PositiveIntegerField(
        default=0,
        help_text="Days with a detection inside that longest episode. Paired with "
                  "max_event_duration it gives the episode's density, which is what "
                  "separates a sustained burn from two blips three weeks apart.",
    )
    mean_gap_days = models.FloatField(
        null=True, blank=True, help_text="Average quiet interval between episodes; null if only one"
    )
    has_ongoing_event = models.BooleanField(
        default=False, db_index=True,
        help_text="An episode here has not yet been closed by a quiet gap",
    )

    # --- radiative features ---
    frp_mean = models.FloatField(default=0.0)
    frp_max = models.FloatField(default=0.0)
    frp_cv = models.FloatField(
        default=0.0, help_text="Coefficient of variation of FRP: low means a stable source"
    )
    brightness_max = models.FloatField(default=0.0)
    best_confidence = models.CharField(max_length=16, default="nominal")

    # --- context features ---
    dist_industrial_m = models.FloatField(null=True, blank=True)
    industrial_group = models.CharField(
        max_length=32, choices=IndustrialGroup.choices, default=IndustrialGroup.NONE
    )
    industrial_name = models.CharField(max_length=200, blank=True)
    land_context = models.CharField(
        max_length=20, choices=LandContext.choices, default=LandContext.UNKNOWN
    )
    landcover_frac_builtup = models.FloatField(
        default=0.0,
        help_text="Share of the ~375 m detection footprint that is built-up or bare. "
                  "The majority class alone is a single 10 m reading and flips on which "
                  "pixel the centroid landed in; the fraction describes the whole pixel.",
    )

    # --- classification output ---
    # Rolled up from this site's episodes rather than computed independently: the
    # label of the most recent one. The map needs one colour per location, but the
    # judgement itself belongs to the episode, and the evidence panel shows every
    # episode with its own label.
    label = models.CharField(
        max_length=32, choices=HotspotClass.choices, default=HotspotClass.UNCERTAIN, db_index=True
    )
    label_confidence = models.CharField(max_length=16, default="low")
    evidence = models.JSONField(default=list, blank=True)
    matched_rule = models.CharField(max_length=80, blank=True)

    in_validation_corridor = models.BooleanField(default=False, db_index=True)
    enriched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-recurrence_days", "-frp_max"]
        indexes = [models.Index(fields=["latitude", "longitude"])]

    def __str__(self) -> str:
        return f"Site {self.pk} ({self.latitude:.4f}, {self.longitude:.4f}) [{self.label}]"

    @property
    def colour(self) -> str:
        return CLASS_COLOURS.get(self.label, "#9ca3af")

    @property
    def label_display(self) -> str:
        return self.get_label_display()


class Detection(models.Model):
    """One thermal anomaly record as reported by NASA FIRMS."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="detections")

    latitude = models.FloatField()
    longitude = models.FloatField()
    acq_date = models.DateField(db_index=True)
    acq_time = models.CharField(max_length=8, help_text="UTC HHMM as reported by FIRMS")

    bright_ti4 = models.FloatField(null=True, blank=True)
    bright_ti5 = models.FloatField(null=True, blank=True)
    frp = models.FloatField(default=0.0)
    confidence = models.CharField(max_length=16, blank=True)
    daynight = models.CharField(max_length=1, blank=True)
    satellite = models.CharField(max_length=16, blank=True)
    instrument = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ["-acq_date", "-acq_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["latitude", "longitude", "acq_date", "acq_time", "satellite"],
                name="unique_detection",
            )
        ]

    def __str__(self) -> str:
        return f"{self.acq_date} {self.acq_time} FRP={self.frp}"


class Event(models.Model):
    """One continuous burning episode at a site.

    A site's detection history is cut wherever it falls quiet for longer than
    ``settings.EVENT_GAP_DAYS``; everything between two cuts is one event. A
    location that burns for three days in March and two days in May stores two
    events, not one five-day blur -- which is the whole point, because the site
    row alone reports ``recurrence_days = 5`` and cannot distinguish the two
    situations.

    Events are rebuilt from scratch on every ingest rather than appended to, which
    keeps the pipeline idempotent.
    """

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="events")

    # --- extent ---
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    duration_days = models.PositiveIntegerField(
        help_text="Calendar days from first to last detection, inclusive"
    )
    active_days = models.PositiveIntegerField(
        help_text="Distinct days inside the span that actually had a detection"
    )
    density = models.FloatField(
        help_text="active_days / duration_days; 1.0 means it burned on every day of the span"
    )
    detection_count = models.PositiveIntegerField(default=0)

    # --- intensity, measured WITHIN this episode ---
    # Pooled across a whole site these are close to meaningless when two fires sit
    # months apart. Confined to one episode they describe a single burn.
    frp_mean = models.FloatField(default=0.0)
    frp_max = models.FloatField(default=0.0)
    frp_cv = models.FloatField(default=0.0)
    brightness_max = models.FloatField(default=0.0)
    peak_date = models.DateField(null=True, blank=True)
    night_fraction = models.FloatField(default=0.0)
    best_confidence = models.CharField(max_length=16, default="nominal")

    # --- position in the site's history ---
    # Deliberately backward-looking. A forward "gap to next event" would be null
    # for the most recent episode -- which is exactly the one an operator needs to
    # act on -- and would have to be rewritten every time a new event appeared.
    gap_before_days = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Days from the previous episode's last detection to this one's first; "
                  "null for the first episode at a site",
    )
    is_ongoing = models.BooleanField(
        default=False,
        help_text="Not yet closed by a quiet gap, so it may still be burning",
    )

    # --- classification output ---
    # This is where the label now lives. A location can produce a routine furnace
    # run and, months later, an accident; judging the two separately is the entire
    # reason episodes are modelled.
    label = models.CharField(
        max_length=32, choices=HotspotClass.choices, default=HotspotClass.UNCERTAIN, db_index=True
    )
    label_confidence = models.CharField(max_length=16, default="low")
    evidence = models.JSONField(default=list, blank=True)
    matched_rule = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["site_id", "start_date"]
        indexes = [models.Index(fields=["site", "start_date"])]
        constraints = [
            models.UniqueConstraint(fields=["site", "start_date"], name="unique_event_start")
        ]

    @property
    def colour(self) -> str:
        return CLASS_COLOURS.get(self.label, "#9ca3af")

    def __str__(self) -> str:
        return (
            f"Event {self.pk} @ site {self.site_id}: {self.start_date} to {self.end_date} "
            f"({self.duration_days}d span, {self.active_days}d active) [{self.label}]"
        )
