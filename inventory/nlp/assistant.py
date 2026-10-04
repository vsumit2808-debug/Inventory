"""
The assistant pipeline: NLP first, RAG as the safety net.

    question
      |-- NLP intent classifier (nlp.intent)
      |     |-- low_stock / item / category / summary intents
      |     |     -> answered precisely from live MySQL data
      |     `-- unknown / no entities
      |           -> RAG: retrieve top-k inventory records (rag.retriever)
      |                 -> grounded answer (rag.generator)
      `-- every exchange is logged (QueryLog) for analytics

This hybrid is deliberate: structured questions get exact numbers from
SQL; open-ended questions still get a useful, source-backed answer.
"""
from django.conf import settings

from ..models import Item, QueryLog
from ..rag import generator as rag_generator
from ..rag import retriever as rag_retriever
from ..services.stock import evaluate_rows, iter_item_dicts
from .intent import classify, extract_entities

HELP_TEXT = (
    "I can answer inventory questions in plain English. Try:\n"
    "* which items are running low?\n"
    "* how many A4 copy paper do we have?\n"
    "* status of laser toner\n"
    "* what is in the Pantry category?\n"
    "* give me an overview of the inventory\n"
    "* who supplies the toner and where is it stored?\n"
    "Anything else falls through to retrieval over the stock records (RAG)."
)


def answer_question(question):
    """
    Returns a context dict for the assistant page:
      question, answer, intent, confidence, sources, results
    sources  = [{"pk","name","sku","score"}] (RAG evidence / matched items)
    results  = low-stock table rows when the intent was low_stock
    """
    question = (question or "").strip()
    intent, score = classify(question)
    entities = extract_entities(question)
    sources, results = [], []

    if intent == "low_stock":
        rows, stats = evaluate_rows(iter_item_dicts())
        results = rows
        if not rows:
            answer = (
                "Good news: nothing is at or below its reorder threshold "
                "right now. All %d active items are healthy." % stats["total"]
            )
        else:
            listing = "; ".join(
                "%s - %s, %d left (threshold %d, order ~%d)"
                % (
                    r["name"],
                    "out of stock" if r["severity"] == "OUT" else "low",
                    r["quantity"],
                    r["reorder_threshold"],
                    r["suggested_order"],
                )
                for r in rows
            )
            total_order = sum(r["suggested_order"] for r in rows)
            answer = (
                "%d item(s) need restocking: %s. Suggested total order "
                "quantity: %d units." % (len(rows), listing, total_order)
            )
        sources = [
            {"pk": r.get("id"), "name": r["name"], "sku": r["sku"], "score": 1.0}
            for r in rows
        ]
        confidence = 0.95

    elif intent in ("quantity_query", "item_status") and entities.item is not None:
        item = entities.item
        answer = (
            "%s (SKU %s, %s): %d units on hand, reorder threshold %d, "
            "status %s. Shortfall vs threshold: %d. Suggested order: %d."
            % (
                item.name, item.sku, item.category or "general",
                item.quantity, item.reorder_threshold, item.status_label,
                item.shortfall, item.suggested_order,
            )
        )
        if item.supplier:
            answer += " Supplier: %s." % item.supplier
        if item.location:
            answer += " Stored at: %s." % item.location
        sources = [{"pk": item.pk, "name": item.name, "sku": item.sku, "score": entities.item_score}]
        confidence = min(0.95, 0.7 + 0.1 * score)

    elif intent == "quantity_query" and entities.category:
        items = Item.objects.filter(is_active=True, category__iexact=entities.category)
        total = sum(i.quantity for i in items)
        low = sum(1 for i in items if i.needs_reorder)
        answer = (
            "Category '%s': %d item(s), %d units in stock, %d below their "
            "reorder threshold." % (entities.category, items.count(), total, low)
        )
        sources = [
            {"pk": i.pk, "name": i.name, "sku": i.sku, "score": entities.category_score}
            for i in items
        ]
        confidence = 0.85

    elif intent == "category_query" and entities.category:
        items = Item.objects.filter(is_active=True, category__iexact=entities.category)
        if items:
            listing = ", ".join(
                "%s (%d)" % (i.name, i.quantity) for i in items
            )
            answer = "Items in category '%s': %s." % (entities.category, listing)
        else:
            answer = "I could not find a category matching '%s'." % entities.category
        sources = [
            {"pk": i.pk, "name": i.name, "sku": i.sku, "score": entities.category_score}
            for i in items
        ]
        confidence = 0.8

    elif intent == "total_summary":
        rows, stats = evaluate_rows(iter_item_dicts())
        value = sum(float(it.stock_value) for it in Item.objects.filter(is_active=True))
        answer = (
            "Inventory overview: %d active items - %d healthy, %d low, "
            "%d out of stock. %d item(s) need restocking today. "
            "Total stock value: %s%.2f."
            % (
                stats["total"], stats["ok"], stats["low"], stats["out"],
                len(rows), getattr(settings, "CURRENCY_SYMBOL", "$"), value,
            )
        )
        confidence = 0.9

    elif intent == "help" or not question:
        answer = HELP_TEXT
        confidence = 1.0

    else:
        # ---- RAG fallback: retrieve, then generate a grounded answer -----
        hits = rag_retriever.retrieve(question, top_k=5)
        answer = rag_generator.generate_answer(question, hits)
        sources = [
            {"pk": item.pk, "name": item.name, "sku": item.sku, "score": s}
            for item, s in hits
        ]
        confidence = hits[0][1] if hits else 0.0
        intent = "rag_retrieval"

    log = QueryLog.objects.create(
        question=question,
        intent=intent,
        confidence=confidence,
        answer=answer,
        sources=sources,
    )
    return {
        "question": question,
        "answer": answer,
        "intent": intent,
        "confidence": round(confidence, 2),
        "sources": sources,
        "results": results,
        "log_id": log.pk,
    }
