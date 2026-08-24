"""
BM25 retrieval store for the regulatory corpus (Q10 — hybrid search).

This module provides keyword-based BM25 retrieval to complement the FAISS
cosine-similarity search in vector_store.py. Together they are fused via
Reciprocal Rank Fusion (RRF) in vector_store.query_hybrid().

Why BM25 alongside FAISS?
--------------------------
Semantic search (FAISS + sentence-transformers) excels at paraphrase-style
matches: "suspend hot work during gas leak" retrieves "terminate ignition
sources on gas alarm" even with no term overlap. But it fails on exact
regulatory references: a query for "OISD-STD-116 clause 4.3" or "LEL" will
not reliably surface the right chunk unless the embedding happened to encode
those tokens distinctively.

BM25 (Okapi BM25) scores chunks by term frequency with saturation:
    score(d, q) = sum_t IDF(t) * (f(t,d) * (k1+1)) / (f(t,d) + k1*(1-b+b*|d|/avgdl))

    k1 = 1.5  (term frequency saturation; standard default)
    b  = 0.75 (document length normalization; standard default)

Regulatory corpus note: stopword removal is intentionally disabled.
"shall", "must", "not", "without" carry meaning in compliance language.

RRF fusion (in vector_store.query_hybrid):
    score_rrf(doc, rank) = 1 / (k + rank),  k=60 (Cormack et al. 2009)

Persistence:
    The tokenized corpus is saved as a JSON sidecar alongside the FAISS index
    so the BM25 index is rebuilt from disk on process restart without needing
    to re-embed anything.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# BM25 parameters — standard Okapi BM25 defaults, well-validated in IR.
BM25_K1: float = 1.5
BM25_B: float = 0.75

# Tokenizer: split on whitespace and punctuation, lowercase, keep numbers.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase token list. No stopword removal (see module docstring)."""
    return _TOKEN_RE.findall(text.lower())


def _try_import_bm25():
    try:
        from rank_bm25 import BM25Okapi
        return BM25Okapi
    except ImportError:
        logger.warning(
            "rank-bm25 not installed. BM25 retrieval disabled. "
            "Install with: pip install rank-bm25"
        )
        return None


class BM25Store:
    """Thin wrapper around rank_bm25.BM25Okapi with JSON persistence.

    The store maintains a parallel list of metadata dicts (same order as
    the tokenized corpus) so search results carry chunk_id, citation, text,
    and source_type back to the caller.
    """

    def __init__(self, corpus_file: str) -> None:
        self._corpus_file = corpus_file
        self._tokenized: list[list[str]] = []
        self._metadata: list[dict] = []
        self._bm25 = None
        self._BM25Okapi = _try_import_bm25()
        self._loaded = False

    # ---------------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------------- #
    def _rebuild(self) -> None:
        """Rebuild BM25Okapi from the current tokenized corpus."""
        if self._BM25Okapi is None or not self._tokenized:
            self._bm25 = None
            return
        self._bm25 = self._BM25Okapi(
            self._tokenized,
            k1=BM25_K1,
            b=BM25_B,
        )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(self._corpus_file):
            return
        try:
            with open(self._corpus_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._tokenized = data.get("tokenized", [])
            self._metadata = data.get("metadata", [])
            self._rebuild()
            logger.info("BM25 corpus loaded: %d chunks from %s", len(self._tokenized), self._corpus_file)
        except Exception as exc:
            logger.warning("Failed to load BM25 corpus from %s: %s", self._corpus_file, exc)
            self._tokenized = []
            self._metadata = []

    # ---------------------------------------------------------------------- #
    # Public API (matches the interface vector_store uses)
    # ---------------------------------------------------------------------- #
    def add(self, texts: list[str], metadatas: list[dict]) -> None:
        """Add chunks to the BM25 index (appends; call save() to persist)."""
        self._ensure_loaded()
        for text, meta in zip(texts, metadatas):
            self._tokenized.append(_tokenize(text))
            self._metadata.append(meta)
        self._rebuild()

    def delete_by_doc_id(self, doc_id: str) -> None:
        """Remove all chunks for a doc_id and rebuild."""
        self._ensure_loaded()
        keep = [(tok, meta) for tok, meta in zip(self._tokenized, self._metadata)
                if meta.get("doc_id") != doc_id]
        if len(keep) == len(self._tokenized):
            return  # nothing to delete
        if keep:
            self._tokenized, self._metadata = zip(*keep)
            self._tokenized = list(self._tokenized)
            self._metadata = list(self._metadata)
        else:
            self._tokenized, self._metadata = [], []
        self._rebuild()

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        source_type: Optional[str] = None,
    ) -> list[dict]:
        """Return top-k chunks by BM25 score.

        Each result dict has: chunk_id, citation, text, source_type, bm25_score, rank.
        """
        self._ensure_loaded()
        if self._bm25 is None or not self._tokenized:
            return []
        try:
            tokens = _tokenize(query_text)
            scores = self._bm25.get_scores(tokens)
        except Exception as exc:
            logger.warning("BM25 scoring failed: %s", exc)
            return []

        # Rank indices by score descending
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        results: list[dict] = []
        for rank, (idx, score) in enumerate(ranked):
            if score <= 0:
                break
            meta = self._metadata[idx]
            if source_type and meta.get("source_type") != source_type:
                continue
            results.append({
                "chunk_id": meta.get("chunk_id", ""),
                "citation": meta.get("citation", meta.get("doc_id", "")),
                "text": meta.get("text", ""),
                "source_type": meta.get("source_type", ""),
                "bm25_score": float(score),
                "rank": rank + 1,
            })
            if len(results) >= top_k:
                break
        return results

    def save(self) -> None:
        """Persist tokenized corpus + metadata to disk."""
        self._ensure_loaded()
        os.makedirs(os.path.dirname(self._corpus_file), exist_ok=True)
        try:
            with open(self._corpus_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"tokenized": self._tokenized, "metadata": self._metadata},
                    f, ensure_ascii=False,
                )
            logger.info("BM25 corpus saved: %d chunks to %s", len(self._tokenized), self._corpus_file)
        except Exception as exc:
            logger.warning("Failed to save BM25 corpus: %s", exc)

    @property
    def total_chunks(self) -> int:
        self._ensure_loaded()
        return len(self._tokenized)
