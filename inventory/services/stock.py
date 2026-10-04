"""
The low-stock engine - the "quiet backend job".

Design note
-----------
Everything flows through *plain dictionaries* (`evaluate_rows`), exactly as
one would loop over a list of dicts from a CSV:

    for row in rows:
        if row["quantity"] <= row["reorder_threshold"]:
            restock.append(row)

Because the comparison logic is dict-based, the SAME engine runs for:
  * ORM items            (the web app / daily job)
  * raw CSV rows         (import preview)
  * unit tests           (no database required)
"""
import csv
import io
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from ..models import Item, StockAlert

REPORT_CSV_COLUMNS = [
    "name", "sku", "category", "severity", "quantity", "reorder_threshold",
    "shortfall", "suggested_order", "unit_price", "supplier", "location",
]


# ---------------------------------------------------------------------------
# 1. Pure dict-based evaluation (loop + conditionals + collect)
# ---------------------------------------------------------------------------
def evaluate_rows(rows):
    """
    Loop through stock rows (dicts), compare quantity vs threshold,
    collect everything that needs restocking.

    rows: iterable of dicts with at least `quantity` and `reorder_threshold`.
          Unknown/blank numbers are treated as 0.

    Returns (restock_rows, stats):
      restock_rows - list of dicts, each enriched with severity / shortfall /
                     suggested_order / unit_price float
      stats        - {"total": n, "ok": n, "low": n, "out": n}
    """
    restock = []
    stats = {"total": 0, "ok": 0, "low": 0, "out": 0}

    for raw in rows:
        row = dict(raw)  # never mutate the caller's dict
        qty = _to_int(row.get("quantity"))
        thr = _to_int(row.get("reorder_threshold"))
        rq = _to_int(row.get("reorder_quantity"))
        row["quantity"] = qty
        row["reorder_threshold"] = thr
        row["shortfall"] = max(0, thr - qty)
        row["suggested_order"] = rq if rq > 0 else max(row["shortfall"], thr // 2)
        try:
            row["unit_price"] = float(Decimal(str(row.get("unit_price") or 0)))
        except Exception:
            row["unit_price"] = 0.0

        stats["total"] += 1
        if qty <= 0:                      # condition 1: nothing left
            row["severity"] = "OUT"
            stats["out"] += 1
            restock.append(row)
        elif qty <= thr:                  # condition 2: at/below threshold
            row["severity"] = "LOW"
            stats["low"] += 1
            restock.append(row)
        else:
            stats["ok"] += 1

    return restock, stats


def _to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 2. ORM -> dict bridge
# ---------------------------------------------------------------------------
def iter_item_dicts(queryset=None):
    """Yield every active item as a plain dict for evaluate_rows()."""
    qs = queryset if queryset is not None else Item.objects.filter(is_active=True)
    for it in qs:
        yield {
            "id": it.pk,
            "name": it.name,
            "sku": it.sku,
            "category": it.category,
            "quantity": it.quantity,
            "reorder_threshold": it.reorder_threshold,
            "reorder_quantity": it.reorder_quantity,
            "unit_price": it.unit_price,
            "supplier": it.supplier,
            "location": it.location,
            "notes": it.notes,
        }


# ---------------------------------------------------------------------------
# 3. Alert snapshots (history of what was flagged, when)
# ---------------------------------------------------------------------------
def refresh_alerts():
    """Create today's StockAlert for every item currently needing reorder."""
    restock, _ = evaluate_rows(iter_item_dicts())
    today = timezone.localdate()
    created = []
    for row in restock:
        exists = StockAlert.objects.filter(
            item_id=row.get("id"),
            severity=row["severity"],
            created_at__date=today,
        ).exists()
        if not exists:
            created.append(
                StockAlert.objects.create(
                    item_id=row.get("id"),
                    item_name=row["name"],
                    item_sku=row["sku"],
                    quantity_at_alert=row["quantity"],
                    threshold_at_alert=row["reorder_threshold"],
                    severity=row["severity"],
                )
            )
    return created


# ---------------------------------------------------------------------------
# 4. Report rendering: console table + TXT file + CSV file
# ---------------------------------------------------------------------------
def build_restock_report(report_dir=None, write_files=True):
    """
    Produce the "RESTOCK NEEDED" report.

    Returns a dict:
      rows, stats, text (full console-ready report), txt_path, csv_path
    Paths are None when write_files is False.
    """
    from django.conf import settings

    restock, stats = evaluate_rows(iter_item_dicts())
    now_local = timezone.localtime()
    stamp = now_local.strftime("%Y-%m-%d %H:%M")
    date_tag = now_local.strftime("%Y-%m-%d")

    lines = []
    lines.append("=" * 78)
    lines.append(" RESTOCK NEEDED - DAILY STOCK REPORT")
    lines.append(" Generated : %s" % stamp)
    lines.append("=" * 78)
    lines.append(
        " %d item(s) checked | %d need restocking | %d low | %d out of stock"
        % (stats["total"], len(restock), stats["low"], stats["out"])
    )
    lines.append("")

    if restock:
        header = (
            "%-8s %-26s %-10s %-14s %5s %5s %6s %6s  %s"
            % ("SEVERITY", "ITEM", "SKU", "CATEGORY", "QTY", "THR", "SHORT", "ORDER", "SUPPLIER")
        )
        lines.append(header)
        lines.append("-" * len(header))
        for r in sorted(restock, key=lambda x: (x["severity"] != "OUT", x["name"])):
            lines.append(
                "%-8s %-26s %-10s %-14s %5d %5d %6d %6d  %s"
                % (
                    r["severity"], _clip(r["name"], 26), _clip(r["sku"], 10),
                    _clip(r.get("category") or "-", 14), r["quantity"],
                    r["reorder_threshold"], r["shortfall"],
                    r["suggested_order"], _clip(r.get("supplier") or "-", 18),
                )
            )
        focus = ", ".join(
            "%s (%s)" % (r["name"], r["severity"]) for r in restock[:5]
        )
        lines.append("")
        lines.append(" Priority: %s" % focus)
    else:
        lines.append(" Nothing to restock today. All items are above their thresholds.")

    lines.append("")
    lines.append(" Auto-generated by StockWise  (python manage.py check_stock)")
    text = "\n".join(lines)

    txt_path = csv_path = None
    if write_files:
        base = report_dir or settings.REPORT_DIR
        base = __import__("pathlib").Path(base)
        base.mkdir(parents=True, exist_ok=True)
        txt_path = base / f"restock_report_{date_tag}.txt"
        csv_path = base / f"restock_report_{date_tag}.csv"
        txt_path.write_text(text, encoding="utf-8")

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=REPORT_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in restock:
            writer.writerow({k: r.get(k, "") for k in REPORT_CSV_COLUMNS})
        csv_path.write_text(buf.getvalue(), encoding="utf-8")

        # stable filenames so automation always finds the latest report
        (base / "latest_restock_report.txt").write_text(text, encoding="utf-8")
        (base / "latest_restock_report.csv").write_text(
            buf.getvalue(), encoding="utf-8"
        )

    return {
        "rows": restock,
        "stats": stats,
        "text": text,
        "txt_path": txt_path,
        "csv_path": csv_path,
        "generated_at": datetime.isoformat(now_local),
    }


def _clip(value, width):
    value = str(value or "")
    return value[: width - 1] + "~" if len(value) > width else value
