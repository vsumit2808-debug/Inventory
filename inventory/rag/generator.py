"""
RAG step 3 - grounded answer generation.

Two interchangeable generators behind one interface:

1. Template synthesiser (default).
   Deterministic sentences built ONLY from the retrieved records.
   Offline, zero cost, auditable, cannot hallucinate numbers.

2. Optional LLM generator.
   Set RAG_LLM_ENABLED=1 plus RAG_LLM_BASE_URL / RAG_LLM_API_KEY /
   RAG_LLM_MODEL (any OpenAI-compatible endpoint) and the retrieved
   records are passed as grounded context to the model. Still pure
   Python (urllib), still "only retrieval + generation", and it falls
   back to the template synthesiser on any error.

Either way, the UI shows WHICH records produced the answer (sources),
which is what makes this RAG rather than a chatbot guessing from memory.
"""
import json
import os
import urllib.request

from ..models import Item


def _fact_line(item):
    status = {
        Item.Status.OUT: "OUT OF STOCK",
        Item.Status.LOW: "needs reorder (%d left, threshold %d)"
        % (item.quantity, item.reorder_threshold),
        Item.Status.OK: "healthy (%d in stock, threshold %d)"
        % (item.quantity, item.reorder_threshold),
    }[item.status]
    bits = ["%s (SKU %s)" % (item.name, item.sku), item.category or None, status]
    if item.supplier:
        bits.append("supplier: %s" % item.supplier)
    if item.location:
        bits.append("stored at: %s" % item.location)
    return " - ".join(str(b) for b in bits if b)


def synthesize(question, hits):
    """Template generator: answer strictly from retrieved items."""
    if not hits:
        return (
            "I could not find anything in the inventory related to that. "
            "Try naming an item, a category, or ask 'what is running low?'."
        )

    lines = ["Based on the %d most relevant inventory record(s):" % len(hits), ""]
    for item, _score in hits:
        lines.append("* %s" % _fact_line(item))
    lines.append("")
    lines.append(
        "Answer assembled from retrieved stock records (RAG); see Sources below."
    )
    return "\n".join(lines)


def _llm_available():
    return (
        os.getenv("RAG_LLM_ENABLED") == "1"
        and bool(os.getenv("RAG_LLM_BASE_URL"))
        and bool(os.getenv("RAG_LLM_API_KEY"))
    )


def _llm_answer(question, hits):
    """Grounded LLM generation over the retrieved context (optional)."""
    context = "\n".join("- %s" % _fact_line(item) for item, _ in hits)
    payload = {
        "model": os.getenv("RAG_LLM_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are StockWise, an inventory assistant. Answer ONLY "
                    "using the inventory records provided. If the answer is "
                    "not in them, say so. Be concise and factual."
                ),
            },
            {
                "role": "user",
                "content": "Inventory records:\n%s\n\nQuestion: %s"
                % (context, question),
            },
        ],
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        os.getenv("RAG_LLM_BASE_URL").rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % os.getenv("RAG_LLM_API_KEY"),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def generate_answer(question, hits):
    """Route to the LLM generator when configured, else template synthesis."""
    if _llm_available():
        try:
            return _llm_answer(question, hits)
        except Exception:
            pass  # any LLM failure degrades gracefully to offline synthesis
    return synthesize(question, hits)
