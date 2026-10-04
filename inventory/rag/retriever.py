"""
RAG step 1+2 - index construction and retrieval.

Each active Item becomes one "document" that bundles every fact a client
might ask about: name, SKU, category, supplier, storage location, quantity,
threshold, status, notes. The retriever fetches the top-k most relevant
documents for a free-text question.

An index cache invalidates itself whenever the inventory changes (count or
latest updated_at moves), so answers always reflect live MySQL data.
"""
from ..models import Item
from .index import TfidfIndex

_cache = {"signature": None, "index": TfidfIndex(), "items": []}


def item_document(item):
    """Flatten an Item into the text that gets indexed."""
    parts = [
        item.name,
        item.sku,
        "category %s" % item.category if item.category else "",
        "supplier %s" % item.supplier if item.supplier else "",
        "stored at %s" % item.location if item.location else "",
        "quantity %d units in stock" % item.quantity,
        "reorder threshold %d" % item.reorder_threshold,
        "status %s" % item.status_label,
        item.notes or "",
    ]
    return ". ".join(p for p in parts if p)


def _signature():
    items = Item.objects.filter(is_active=True).order_by("pk")
    latest = items.latest("updated_at").updated_at if items.exists() else None
    return (items.count(), latest.isoformat() if latest else "")


def get_index():
    """Return (index, items). Rebuilds lazily when the data changed."""
    sig = _signature()
    if _cache["signature"] != sig:
        items = list(Item.objects.filter(is_active=True))
        index = TfidfIndex()
        index.build((item.pk, item_document(item)) for item in items)
        _cache["signature"] = sig
        _cache["index"] = index
        _cache["items"] = items
    return _cache["index"], _cache["items"]


def retrieve(query, top_k=5, min_score=0.05):
    """
    Return [(Item, score), ...] - the evidence for the generator step.
    """
    index, items = get_index()
    by_pk = {item.pk: item for item in items}
    hits = []
    for pk, score in index.search(query, top_k=top_k, min_score=min_score):
        item = by_pk.get(pk)
        if item is not None:
            hits.append((item, score))
    return hits
