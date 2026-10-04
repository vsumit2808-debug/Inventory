from django.contrib import admin

from .models import Item, QueryLog, StockAlert, StockMovement


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sku",
        "category",
        "quantity",
        "reorder_threshold",
        "status",
        "supplier",
        "location",
    )
    list_filter = ("category", "is_active")
    search_fields = ("name", "sku", "supplier")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("item", "delta", "reason", "note", "created_at")
    list_filter = ("reason",)
    search_fields = ("item__name", "item__sku")


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = (
        "severity",
        "item_name",
        "item_sku",
        "quantity_at_alert",
        "threshold_at_alert",
        "created_at",
    )
    list_filter = ("severity",)


@admin.register(QueryLog)
class QueryLogAdmin(admin.ModelAdmin):
    list_display = ("question", "intent", "confidence", "created_at")
    search_fields = ("question",)
