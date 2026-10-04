"""
Data model for StockWise.

Item            - one SKU of physical stock (the CSV row, materialised).
StockMovement   - immutable audit trail of every +/- quantity change.
StockAlert      - snapshot created by the daily check_stock job.
QueryLog        - every question asked to the NLP/RAG assistant (analytics).
"""
from django.db import models
from django.utils import timezone


class Item(models.Model):
    """A single stocked item. Mirrors one row of the stock CSV file."""

    class Status(models.TextChoices):
        OK = "OK", "Healthy"
        LOW = "LOW", "Low stock"
        OUT = "OUT", "Out of stock"

    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64, unique=True, blank=True)
    category = models.CharField(max_length=100, blank=True, default="General")
    quantity = models.PositiveIntegerField(default=0)
    reorder_threshold = models.PositiveIntegerField(
        default=10,
        help_text="When quantity falls to or below this, the item is flagged.",
    )
    reorder_quantity = models.PositiveIntegerField(
        default=0,
        help_text="How much to order when restocking. 0 = auto-suggest.",
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    supplier = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["is_active"]),
        ]

    def save(self, *args, **kwargs):
        if not self.sku:
            import uuid

            self.sku = "ITM-" + uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    # ---- low-stock logic (single source of truth) ------------------------
    @property
    def needs_reorder(self):
        """The core conditional: current quantity vs. reorder threshold."""
        return self.quantity <= self.reorder_threshold

    @property
    def status(self):
        if self.quantity <= 0:
            return self.Status.OUT
        if self.needs_reorder:
            return self.Status.LOW
        return self.Status.OK

    @property
    def status_label(self):
        return self.Status(self.status).label

    @property
    def shortfall(self):
        """Units below the reorder threshold (0 when healthy)."""
        return max(0, self.reorder_threshold - self.quantity)

    @property
    def suggested_order(self):
        """Configured reorder quantity, or an auto-suggested amount."""
        if self.reorder_quantity > 0:
            return self.reorder_quantity
        return max(self.shortfall, self.reorder_threshold // 2)

    @property
    def stock_value(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.name} ({self.sku})"


class StockMovement(models.Model):
    """Immutable audit trail: every quantity change is recorded here."""

    class Reason(models.TextChoices):
        INITIAL = "INITIAL", "Initial stock"
        PURCHASE = "PURCHASE", "Purchase received"
        SALE = "SALE", "Sale / issued out"
        ADJUSTMENT = "ADJUSTMENT", "Manual adjustment"
        RETURN = "RETURN", "Customer return"
        DAMAGE = "DAMAGE", "Damage / loss"

    item = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name="movements"
    )
    delta = models.IntegerField(help_text="Positive = stock in, negative = out.")
    reason = models.CharField(
        max_length=20, choices=Reason.choices, default=Reason.ADJUSTMENT
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.item.sku} {self.delta:+d} ({self.reason})"


class StockAlert(models.Model):
    """Daily snapshot of an item flagged by the check_stock job."""

    class Severity(models.TextChoices):
        LOW = "LOW", "Low stock"
        OUT = "OUT", "Out of stock"

    item = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alerts",
    )
    item_name = models.CharField(max_length=200)
    item_sku = models.CharField(max_length=64)
    quantity_at_alert = models.PositiveIntegerField()
    threshold_at_alert = models.PositiveIntegerField()
    severity = models.CharField(max_length=10, choices=Severity.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "stock alerts"

    def __str__(self):
        return f"[{self.severity}] {self.item_name} @ {self.created_at:%Y-%m-%d}"


class QueryLog(models.Model):
    """Every question asked to the assistant - fuels usage analytics."""

    question = models.TextField()
    intent = models.CharField(max_length=40, blank=True)
    confidence = models.FloatField(default=0.0)
    answer = models.TextField(blank=True)
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "query logs"

    def __str__(self):
        return f"Q: {self.question[:60]}"


def today_local():
    return timezone.localdate()
