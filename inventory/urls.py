from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("items/", views.item_list, name="item_list"),
    path("items/add/", views.item_create, name="item_create"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("items/<int:pk>/edit/", views.item_update, name="item_update"),
    path("items/<int:pk>/delete/", views.item_confirm_delete, name="item_confirm_delete"),
    path("items/<int:pk>/delete/confirm/", views.item_delete, name="item_delete"),
    path("items/<int:pk>/adjust/", views.item_adjust, name="item_adjust"),
    path("csv/import/", views.import_csv, name="import_csv"),
    path("csv/export/", views.export_csv_view, name="export_csv"),
    path("reports/", views.reports, name="reports"),
    path("reports/generate/", views.reports_generate, name="reports_generate"),
    path("reports/download/<str:name>/", views.report_download, name="report_download"),
    path("assistant/", views.assistant, name="assistant"),
    path("how-ai-works/", views.about, name="about"),
]
