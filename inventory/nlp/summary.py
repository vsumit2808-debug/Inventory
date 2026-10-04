"""
NLP feature 2 - natural language generation (NLG).

Turns the raw numbers of the stock database into a short human briefing.
The morning check_stock job prints it, and the dashboard shows it - so a
manager reads one sentence instead of scanning a table.

Deterministic template NLG: same data -> same words -> auditable, offline,
zero API cost. (An LLM can be plugged in later; see rag/generator.py.)
"""
from ..services.stock import evaluate_rows, iter_item_dicts

HEALTHY = "are healthy"
NEEDS_ATTENTION = "need attention"


def morning_briefing(queryset=None):
    """One-paragraph summary of current stock health."""
    rows, stats = evaluate_rows(iter_item_dicts(queryset))
    total = stats["total"]
    if total == 0:
        return "No active items in the inventory yet. Import a CSV or add items to get started."

    parts = []
    if stats["out"]:
        parts.append(
            "%d out of stock" % stats["out"]
        )
    if stats["low"]:
        parts.append("%d below reorder threshold" % stats["low"])
    ok = stats["ok"]
    opening = (
        "Stock health: %d of %d items %s (%s)."
        % (ok, total, HEALTHY if ok == total else NEEDS_ATTENTION, ", ".join(parts))
        if parts
        else "Stock health: all %d items %s." % (total, HEALTHY)
    )

    focus = ", ".join(
        "%s (%s, order ~%d)" % (r["name"], r["severity"], r["suggested_order"])
        for r in restock_focus(rows)
    )
    closing = (
        " Suggested reorder focus: %s." % focus
        if focus
        else " No reorders needed today."
    )
    return opening + closing


def restock_focus(restock_rows, limit=3):
    """Most urgent restock rows first: OUT before LOW, then biggest ratio."""
    def urgency(r):
        ratio = r["quantity"] / r["reorder_threshold"] if r["reorder_threshold"] else 0
        return (0 if r["severity"] == "OUT" else 1, ratio)

    return sorted(restock_rows, key=urgency)[:limit]
