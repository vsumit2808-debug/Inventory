"""
NLP feature 1 - intent classification + entity extraction.

WHY: warehouse staff should not need to learn query syntax. They type
"what's running low?" or "how many a4 paper do we have?" in plain English.
This module maps free text to a small set of *intents* the app can answer
precisely from the database, and extracts the *entities* (item, category,
number) the intent needs.

HOW: a compact weighted-regex classifier (fast, deterministic, fully
offline) plus fuzzy entity matching from nlp.text. Open-ended questions
that do not match any intent fall through to the RAG pipeline
(see inventory/rag/).
"""
import re
from dataclasses import dataclass, field

from .text import best_match, normalize

# ----------------------------------------------------------------------------
# Intent rules. Each intent has regexes; a hit scores +1 (first pattern of
# each intent scores a bit higher). Priority breaks ties so specific intents
# (low_stock) beat generic ones (total_summary).
# ----------------------------------------------------------------------------
INTENT_RULES = [
    (
        "low_stock",
        [
            r"running low",
            r"\blow\b",
            r"restock",
            r"re[- ]?order",
            r"out of stock",
            r"short(age)?",
            r"deplet",
            r"need(s)? (to be )?(order|reorder)",
            r"what should (we|i) order",
            r"\border(ing)? report\b",
            r"\bbuy\b",
        ],
    ),
    (
        "quantity_query",
        [
            r"how (many|much)",
            r"\bcount\b",
            r"\bleft\b",
            r"\bon hand\b",
            r"\bin stock\b",
            r"\bquantity\b",
            r"\bstock level",
        ],
    ),
    (
        "item_status",
        [
            r"\bstatus\b",
            r"\bcheck\b",
            r"tell me about",
            r"\bdetails?\b",
            r"\binfo( rmation)?\b",
            r"\blook ?up\b",
        ],
    ),
    (
        "category_query",
        [r"\bcategory\b", r"\bcategories\b", r"\bgroup\b", r"\blist\b", r"\bshow\b"],
    ),
    (
        "total_summary",
        [
            r"overview",
            r"summar",
            r"\btotal\b",
            r"how many (items|skus|products)",
            r"inventory value",
            r"\bworth\b",
            r"\bhealth\b",
        ],
    ),
    (
        "help",
        [r"\bhelp\b", r"what can you", r"how do (i|you)", r"\bcapab", r"\bcommands\b"],
    ),
]

# Lower number = higher priority when scores tie.
INTENT_PRIORITY = {
    "low_stock": 0,
    "item_status": 1,
    "quantity_query": 2,
    "category_query": 3,
    "total_summary": 4,
    "help": 5,
}

COMPILED = {
    intent: [re.compile(p) for p in patterns]
    for intent, patterns in INTENT_RULES
}


@dataclass
class Entities:
    """Things the classifier found in the question."""

    item: object = None          # Item instance or None
    item_score: float = 0.0
    category: object = None      # category string or None
    category_score: float = 0.0
    number: object = None        # first integer mentioned, if any
    numbers: list = field(default_factory=list)


def classify(text):
    """
    Return (intent, score).

    score = number of matching patterns; 0 => unknown intent.
    Ties resolved by domain priority (low_stock first, help last).
    """
    q = normalize(text)
    if not q:
        return "unknown", 0
    scores = {}
    for intent, patterns in COMPILED.items():
        hits = sum(1 for p in patterns if p.search(q))
        if hits:
            scores[intent] = hits
    if not scores:
        return "unknown", 0
    best_score = max(scores.values())
    # among intents with the best score, take the highest priority (lowest num)
    intent = min(
        (i for i, s in scores.items() if s == best_score),
        key=lambda i: INTENT_PRIORITY.get(i, 9),
    )
    return intent, best_score


def extract_entities(text, items=None, categories=None):
    """
    Pull the entities a question talks about.

    items       - iterable of Item objects (defaults to active Items)
    categories  - iterable of category names (defaults to distinct values)
    """
    from inventory.models import Item  # local import avoids AppRegistry issues

    if items is None:
        items = list(Item.objects.filter(is_active=True))
    if categories is None:
        categories = list(
            Item.objects.filter(is_active=True)
            .exclude(category="")
            .values_list("category", flat=True)
            .distinct()
        )

    q = normalize(text)
    ent = Entities()

    # -- item: exact SKU mention wins, else fuzzy name match ---------------
    item, score = None, 0.0
    for it in items:
        sku = (it.sku or "").strip().lower()
        if sku and re.search(r"\b" + re.escape(sku) + r"\b", q):
            item, score = it, 1.0
            break
    if item is None:
        names = [it.name for it in items]
        name, score = best_match(q, names, min_score=0.55)
        if name is not None:
            item = next(it for it in items if it.name == name)
    ent.item, ent.item_score = item, score

    # -- category ----------------------------------------------------------
    if item is None:  # only hunt for a category if no specific item matched
        cat, cscore = best_match(q, [c for c in categories if c], min_score=0.6)
        ent.category, ent.category_score = cat, cscore

    # -- numbers -----------------------------------------------------------
    ent.numbers = [int(n) for n in re.findall(r"\b(\d{1,6})\b", q)]
    ent.number = ent.numbers[0] if ent.numbers else None

    return ent
