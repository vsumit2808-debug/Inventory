"""
CSV import / export.

Import highlights
-----------------
* Header aliases: accepts "Item Name", "item", "Current Quantity", "qty",
  "Reorder Threshold", "threshold", "reorder level" ... (see ALIASES).
* NLP-assisted de-duplication: fuzzy-matches incoming names against
  existing items (nlp.text.similarity) so "A4 Paper" vs "A4 paper ream"
  does not silently create a double stock record.
"""
import csv
import io

from ..models import Item, StockMovement
from ..nlp.text import similarity

ALIASES = {
    "name": ["item name", "item", "product", "product name", "name", "title"],
    "sku": ["sku", "code", "item code", "product code", "stock code"],
    "category": ["category", "type", "group", "department"],
    "quantity": [
        "current quantity", "qty", "quantity", "current qty", "stock",
        "stock quantity", "on hand", "on hand qty", "available",
    ],
    "reorder_threshold": [
        "reorder threshold", "threshold", "reorder level", "reorder point",
        "min", "minimum", "min stock", "min quantity", "low stock alert",
    ],
    "reorder_quantity": [
        "reorder quantity", "order quantity", "restock quantity",
        "order amount", "reorder qty",
    ],
    "unit_price": ["unit price", "price", "cost", "rate", "cost per unit"],
    "supplier": ["supplier", "vendor", "distributor"],
    "location": ["location", "warehouse", "bin", "shelf", "storage"],
    "notes": ["notes", "note", "description", "remarks", "comment"],
}

_LOOKUP = {
    alias: field for field, aliases in ALIASES.items() for alias in aliases
}

FUZZY_DUPLICATE_THRESHOLD = 0.87


def map_header(header):
    """Map a CSV header cell to a canonical field name (or None)."""
    key = " ".join(str(header or "").lower().split())
    if key in _LOOKUP:
        return _LOOKUP[key]
    # tolerate trailing/leading decorations like "qty (units)"
    for alias, field in _LOOKUP.items():
        if alias in key:
            return field
    return None


def normalize_headers(reader_rows, warnings):
    """Yield dicts with canonical keys from raw DictReader rows."""
    for raw in reader_rows:
        row = {}
        for key, value in raw.items():
            field = map_header(key)
            if field:
                row[field] = (value or "").strip()
            elif key and str(key).strip():
                warnings.append("Ignored unknown column: %r" % key)
        yield row


def import_rows(rows, update_existing=False, source="CSV import"):
    """
    Import normalized rows.

    Returns:
      {"created": [..], "updated": [..], "skipped": [..], "warnings": [..]}
    Each entry is a small dict with name/sku/reason for display.
    """
    result = {"created": [], "updated": [], "skipped": [], "warnings": []}
    existing = list(Item.objects.filter(is_active=True))
    by_sku = {i.sku.strip().lower(): i for i in existing if i.sku}

    for n, row in enumerate(normalize_headers(rows, result["warnings"]), start=1):
        name = row.get("name")
        if not name:
            result["skipped"].append(
                {"row": n, "name": "", "reason": "missing item name"}
            )
            continue

        qty = _parse_number(row.get("quantity"), 0)
        threshold = _parse_number(row.get("reorder_threshold"), 0)
        reorder_qty = _parse_number(row.get("reorder_quantity"), 0)
        price = _parse_number(row.get("unit_price"), 0)

        # -- locate an existing record: SKU exact match, else fuzzy name ----
        target = None
        match_reason = ""
        sku_key = (row.get("sku") or "").strip().lower()
        if sku_key and sku_key in by_sku:
            target, match_reason = by_sku[sku_key], "SKU match"
        else:
            best, score = None, 0.0
            for item in existing:
                s = similarity(name, item.name)
                if s > score:
                    best, score = item, s
            if best is not None and score >= FUZZY_DUPLICATE_THRESHOLD:
                target, match_reason = best, "fuzzy match %.0f%%" % (score * 100)

        if target is not None:
            if not update_existing:
                result["skipped"].append(
                    {
                        "row": n,
                        "name": name,
                        "reason": "duplicate of %s (%s)"
                        % (target.sku, match_reason),
                    }
                )
                continue
            delta = qty - target.quantity
            target.quantity = qty
            target.reorder_threshold = threshold
            target.reorder_quantity = reorder_qty
            target.unit_price = price
            for f in ("category", "supplier", "location", "notes"):
                if row.get(f):
                    setattr(target, f, row[f])
            target.save()
            StockMovement.objects.create(
                item=target,
                delta=delta,
                reason=StockMovement.Reason.ADJUSTMENT,
                note=source,
            )
            result["updated"].append(
                {"row": n, "name": name, "sku": target.sku, "reason": match_reason}
            )
            continue

        item = Item.objects.create(
            name=name,
            sku=row.get("sku") or "",           # blank -> auto-generated
            category=row.get("category") or "General",
            quantity=max(0, qty),
            reorder_threshold=max(0, threshold),
            reorder_quantity=max(0, reorder_qty),
            unit_price=price,
            supplier=row.get("supplier") or "",
            location=row.get("location") or "",
            notes=row.get("notes") or "",
        )
        StockMovement.objects.create(
            item=item,
            delta=item.quantity,
            reason=StockMovement.Reason.INITIAL,
            note=source,
        )
        existing.append(item)
        by_sku[item.sku.lower()] = item
        result["created"].append({"row": n, "name": name, "sku": item.sku})

    return result


def export_csv(queryset=None):
    """Return the current items as a CSV string (same column vocabulary)."""
    qs = queryset if queryset is not None else Item.objects.filter(is_active=True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Item Name", "SKU", "Category", "Current Quantity",
            "Reorder Threshold", "Reorder Quantity", "Unit Price",
            "Supplier", "Location", "Notes",
        ]
    )
    for it in qs:
        writer.writerow(
            [
                it.name, it.sku, it.category, it.quantity,
                it.reorder_threshold, it.reorder_quantity,
                str(it.unit_price), it.supplier, it.location, it.notes,
            ]
        )
    return buf.getvalue()


def _parse_number(value, default=0):
    try:
        number = float(str(value or "").replace(",", "").replace("$", ""))
        return int(number) if number == int(number) else round(number, 2)
    except (TypeError, ValueError):
        return default
