from django.contrib import admin

from .models import Detection, Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = (
        "id", "latitude", "longitude", "label", "recurrence_days",
        "frp_max", "dist_industrial_m", "land_context",
    )
    list_filter = ("label", "land_context", "industrial_group", "in_validation_corridor")
    search_fields = ("grid_key", "industrial_name")


@admin.register(Detection)
class DetectionAdmin(admin.ModelAdmin):
    list_display = ("id", "acq_date", "acq_time", "latitude", "longitude", "frp", "confidence")
    list_filter = ("confidence", "daynight", "satellite")
