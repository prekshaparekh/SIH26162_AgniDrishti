"""Data model for thermal anomaly detections and the persistent sites they form.

The distinction between the two tables is the core modelling idea of the project:

* A ``Detection`` is one thermal anomaly reported by FIRMS at one moment in time.
* A ``Site`` is a *location* that has produced one or more detections over time.

Classification happens at the ``Site`` level, not the ``Detection`` level, because
the feature that separates an industrial fire from a routine gas flare is temporal
-- how often this location burns -- and that is only visible once detections are
grouped by place.
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

    # --- classification output ---
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
