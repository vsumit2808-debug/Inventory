"""
Low-level text utilities shared by the NLP features.

Everything here is pure Python (difflib + re + math from the standard
library) so the stack stays Django + MySQL only, on every OS.
"""
import re
from difflib import SequenceMatcher

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Very small stopword list tuned for inventory questions. We keep domain
# words like "low", "stock", "order" because they carry intent.
STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "to", "is", "are", "do",
    "does", "did", "we", "i", "my", "our", "and", "or", "with", "at",
    "it", "its", "this", "that", "there", "please", "can", "you", "me",
    "us", "get", "give", "was", "were", "be", "been", "have", "has",
    "had", "any", "about", "from", "by", "as", "so", "if", "s",
}


def normalize(text):
    """Lowercase and collapse whitespace."""
    return " ".join(str(text or "").lower().split())


def tokenize(text):
    """Lowercase alphanumeric tokens, stopwords removed."""
    return [
        t
        for t in TOKEN_RE.findall(str(text or "").lower())
        if t not in STOPWORDS
    ]


def similarity(a, b):
    """
    Fuzzy similarity in [0, 1] between two short product-name strings.

    Combines:
      * plain character-sequence ratio  (catches typos: "sterly nife")
      * sorted token-set ratio          (catches word order: "paper a4")

    Used by CSV de-duplication and by entity extraction when the user
    types an item name freehand.
    """
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    direct = SequenceMatcher(None, a, b).ratio()
    ta = " ".join(sorted(set(tokenize(a))))
    tb = " ".join(sorted(set(tokenize(b))))
    token = SequenceMatcher(None, ta, tb).ratio() if ta and tb else 0.0
    return max(direct, token)


def best_match(query, candidates, min_score=0.6):
    """
    Return (candidate, score) with the highest fuzzy similarity to
    `query`, or (None, score) when nothing clears `min_score`.
    `candidates` is any iterable of strings.
    """
    best, best_score = None, 0.0
    q = normalize(query)
    if not q:
        return None, 0.0
    for cand in candidates:
        score = similarity(q, cand)
        if score > best_score:
            best, best_score = cand, score
    if best_score < min_score:
        return None, best_score
    return best, best_score
