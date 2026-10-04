"""StockWise URL configuration - everything lives in the inventory app."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("inventory.urls")),
]
