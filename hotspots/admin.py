from django.contrib import admin

from .models import Detection, Event, Site


class EventInline(admin.TabularInline):
    """A site's episodes, in order -- the quickest way to see whether a location
    burned once for a long time or repeatedly for short ones."""

    model = Event
    extra = 0
    can_delete = False
    fields = (
        "start_date", "end_date", "duration_days", "active_days", "density",
        "frp_max", "gap_before_days", "is_ongoing", "label", "label_confidence",
        "matched_rule",
    )
    readonly_fields = fields
    ordering = ("start_date",)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = (
        "id", "latitude", "longitude", "label", "recurrence_days",
        "event_count", "max_event_duration", "has_ongoing_event",
        "frp_max", "dist_industrial_m", "land_context",
    )
    list_filter = (
        "label", "land_context", "industrial_group",
        "in_validation_corridor", "has_ongoing_event",
    )
    search_fields = ("grid_key", "industrial_name")
    inlines = [EventInline]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "id", "site", "start_date", "end_date", "duration_days",
        "active_days", "density", "frp_max", "is_ongoing", "label", "label_confidence",
    )
    list_filter = ("label", "label_confidence", "is_ongoing", "site__label")
    date_hierarchy = "start_date"


@admin.register(Detection)
class DetectionAdmin(admin.ModelAdmin):
    list_display = ("id", "acq_date", "acq_time", "latitude", "longitude", "frp", "confidence")
    list_filter = ("confidence", "daynight", "satellite")
