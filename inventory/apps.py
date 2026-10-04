from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"
    verbose_name = "Inventory"

    def ready(self):
        # Register project-level system checks (MySQL/cryptography guidance).
        from stockwise import checks  # noqa: F401
