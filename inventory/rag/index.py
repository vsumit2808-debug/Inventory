"""
A tiny, dependency-free TF-IDF vector space index.

Why hand-rolled? The brief is "Python + Django + MySQL only". numpy /
scikit-learn would work, but a ~70-line pure-Python index keeps the
dependency list tiny and installs identically on macOS, Windows and Linux
(no compiled wheels). For an inventory of hundreds to low-thousands of
SKUs this is instant; for 100k+ items swap in pgvector/MySQL vector
extensions or a real ANN service - the Retriever interface stays the same.

Mechanics (classic IR):
  tf  = raw token count in document
  idf = ln((N + 1) / (df + 1)) + 1   (smoothed, avoids div-by-zero)
  w   = tf * idf, L2-normalised per document
  score(query, doc) = cosine similarity = dot product (both normalised)
"""
import math
import re
from collections import Counter

from inventory.nlp.text import tokenize

TOKEN_RE = re.compile(r"[a-z0-9]+")


class TfidfIndex:
    def __init__(self):
        self.ids = []
        self.vectors = []
        self.idf = {}

    # ------------------------------------------------------------------
    def build(self, documents):
        """
        documents: iterable of (doc_id, text).
        """
        docs = list(documents)
        df = Counter()
        tokenised = [(doc_id, Counter(tokenize(text))) for doc_id, text in docs]
        for _, tf in tokenised:
            for token in tf:
                df[token] += 1

        n_docs = len(docs)
        self.idf = {
            token: math.log((n_docs + 1) / (count + 1)) + 1.0
            for token, count in df.items()
        }
        self.ids = [doc_id for doc_id, _ in tokenised]
        self.vectors = [self._vector(tf) for _, tf in tokenised]

    def _vector(self, tf):
        weights = {
            token: count * self.idf.get(token, 1.0) for token, count in tf.items()
        }
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        return {token: w / norm for token, w in weights.items()}

    # ------------------------------------------------------------------
    def search(self, query, top_k=5, min_score=0.05):
        """
        Return [(doc_id, score), ...] best first. Cosine similarity.
        """
        if not self.ids:
            return []
        q = self._vector(Counter(tokenize(query)))
        if not q:
            return []
        scored = []
        for doc_id, vec in zip(self.ids, self.vectors):
            # both vectors are L2-normalised -> dot product == cosine
            score = sum(w * q[token] for token, w in vec.items() if token in q)
            if score >= min_score:
                scored.append((doc_id, round(score, 4)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]
