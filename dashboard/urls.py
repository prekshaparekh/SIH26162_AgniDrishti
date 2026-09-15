from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.map_view, name="map"),
    path("api/sites/", views.sites_geojson, name="sites_geojson"),
    path("api/charts/", views.charts_json, name="charts_json"),
    path("site/<int:pk>/", views.site_detail, name="site_detail"),
]
