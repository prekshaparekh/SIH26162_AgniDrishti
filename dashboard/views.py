"""Views for the AgniDrishti dashboard.

The map is driven by a GeoJSON endpoint rather than server-rendered markers, so
that filtering is a single fetch instead of a full page reload. Evidence panels are
HTMX partials -- the interaction is small enough that a client-side framework would
add a build step without adding capability.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.conf import settings
from django.db.models import Avg, Count, Max, Min
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from hotspots.models import CLASS_COLOURS, Detection, HotspotClass, Site


def _filtered_sites(request):
    """Apply the sidebar filters to the site queryset."""
    sites = Site.objects.all()

    labels = request.GET.getlist("label")
    if labels:
        sites = sites.filter(label__in=labels)

    min_frp = request.GET.get("min_frp")
    if min_frp:
        try:
            sites = sites.filter(frp_max__gte=float(min_frp))
        except ValueError:
            pass

    min_recurrence = request.GET.get("min_recurrence")
    if min_recurrence:
        try:
            sites = sites.filter(recurrence_days__gte=int(min_recurrence))
        except ValueError:
            pass

    if request.GET.get("corridor_only") == "1":
        sites = sites.filter(in_validation_corridor=True)

    confidence = request.GET.getlist("confidence")
    if confidence:
        sites = sites.filter(best_confidence__in=confidence)

    return sites


def map_view(request):
    sites = Site.objects.all()
    counts = Counter(sites.values_list("label", flat=True))

    summary = [
        {
            "key": choice.value,
            "label": choice.label,
            "colour": CLASS_COLOURS[choice],
            "count": counts.get(choice.value, 0),
        }
        for choice in HotspotClass
    ]

    lon_min, lat_min, lon_max, lat_max = settings.VALIDATION_BBOX
    context = {
        "summary": summary,
        "total_sites": sites.count(),
        "total_detections": Detection.objects.count(),
        "corridor_bounds": [[lat_min, lon_min], [lat_max, lon_max]],
        "classes": HotspotClass.choices,
        "has_data": sites.exists(),
    }
    return render(request, "dashboard/map.html", context)


def sites_geojson(request):
    """Classified sites as GeoJSON, ready for Leaflet."""
    sites = _filtered_sites(request).only(
        "id", "latitude", "longitude", "label", "label_confidence",
        "frp_max", "recurrence_days", "dist_industrial_m", "land_context",
    )[:8000]

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [site.longitude, site.latitude]},
            "properties": {
                "id": site.id,
                "label": site.label,
                "label_display": site.get_label_display(),
                "colour": site.colour,
                "confidence": site.label_confidence,
                "frp_max": round(site.frp_max, 1),
                "recurrence": site.recurrence_days,
                "distance": round(site.dist_industrial_m) if site.dist_industrial_m else None,
                "land": site.get_land_context_display(),
            },
        }
        for site in sites
    ]
    return JsonResponse({"type": "FeatureCollection", "features": features})


def site_detail(request, pk: int):
    """Evidence panel for a single site.

    Every classification is shown together with the features that produced it --
    a user should never see a bare label.
    """
    site = get_object_or_404(Site.objects.prefetch_related("detections"), pk=pk)
    detections = list(site.detections.all()[:400])

    # Recurrence is only interpretable against the period actually observed, so the
    # panel reports the real span of ingested data rather than a nominal 90 days.
    span = Detection.objects.aggregate(lo=Min("acq_date"), hi=Max("acq_date"))
    window_days = (
        (span["hi"] - span["lo"]).days + 1 if span["lo"] and span["hi"] else 0
    )

    timeline = defaultdict(float)
    for detection in detections:
        timeline[detection.acq_date.isoformat()] = max(
            timeline[detection.acq_date.isoformat()], detection.frp
        )

    return render(
        request,
        "dashboard/partials/_evidence.html",
        {
            "site": site,
            "recent": detections[:12],
            "timeline_dates": sorted(timeline),
            "timeline_frp": [round(timeline[d], 1) for d in sorted(timeline)],
            "window_days": window_days,
        },
    )


def charts_json(request):
    """Aggregates for the Plotly panels."""
    sites = _filtered_sites(request)

    class_counts = Counter(sites.values_list("label", flat=True))
    distribution = [
        {
            "label": choice.label,
            "count": class_counts.get(choice.value, 0),
            "colour": CLASS_COLOURS[choice],
        }
        for choice in HotspotClass
    ]

    # Detections per day, split by the class of their parent site: this is the
    # chart that shows persistent sources forming a flat daily baseline while
    # vegetation fires arrive in bursts.
    daily = (
        Detection.objects.filter(site__in=sites)
        .values("acq_date", "site__label")
        .annotate(n=Count("id"))
        .order_by("acq_date")
    )
    series: dict[str, dict[str, int]] = defaultdict(dict)
    for row in daily:
        series[row["site__label"]][row["acq_date"].isoformat()] = row["n"]

    all_dates = sorted({d for label in series.values() for d in label})
    timeseries = [
        {
            "label": dict(HotspotClass.choices).get(label, label),
            "colour": CLASS_COLOURS.get(label, "#9ca3af"),
            "dates": all_dates,
            "counts": [series[label].get(d, 0) for d in all_dates],
        }
        for label in series
    ]

    # Recurrence is the feature that separates a routine flare from an incident,
    # so it gets its own distribution.
    recurrence = [
        {
            "label": dict(HotspotClass.choices).get(label, label),
            "colour": CLASS_COLOURS.get(label, "#9ca3af"),
            "values": list(
                sites.filter(label=label).values_list("recurrence_days", flat=True)[:2000]
            ),
        }
        for label in class_counts
    ]

    stats = sites.aggregate(avg_frp=Avg("frp_max"), max_frp=Max("frp_max"), n=Count("id"))

    return JsonResponse(
        {
            "distribution": distribution,
            "timeseries": timeseries,
            "recurrence": recurrence,
            "stats": {
                "count": stats["n"] or 0,
                "avg_frp": round(stats["avg_frp"] or 0, 1),
                "max_frp": round(stats["max_frp"] or 0, 1),
            },
        }
    )
