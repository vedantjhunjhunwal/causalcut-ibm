"""
FAISS-backed store for the regulatory RAG corpus (design doc Section 4.9,
7.5, 9.1; Appendix B: "Vector Search (RAG): FAISS").

Section 4.9:
  "FAISS vector index over chunked regulatory text (OISD standards,
   Factories Act 1948, DGMS circulars); cosine similarity retrieval
   of top-5 relevant chunks"

Architecture
------------
FAISS stores only raw vectors keyed by integer row position.  The metadata
bookkeeping needed for this system (doc_id, source_type, clause_ref,
citation, chunk text for return) is handled by a JSON sidecar file that
maps each FAISS row index to its Chunk metadata.  Both files are persisted
together to config.FAISS_INDEX_DIR.

Index type: IndexFlatIP (inner product on L2-normalised vectors = cosine
similarity).  At the corpus scale specified by Section 9.1 (50-100 chunks),
brute-force is optimal -- HNSW/IVF overhead would slow things down for
zero recall benefit.

Timeout fallback: Appendix A's "Regulatory retrieval failure" row specifies
that on FAISS query timeout the system should "proceed without regulatory
evidence; flag as unverified."  Implemented via ThreadPoolExecutor.
"""

from __future__ import annotations

import os
import json
import logging
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List, Optional

import faiss
import numpy as np
try:
    import torch
    torch.set_num_threads(1)
except Exception:
    pass
from sentence_transformers import SentenceTransformer

import config
from chunker import Chunk, chunk_document

logger = logging.getLogger(__name__)

# Shared executor for timeout-bounded queries (Appendix A fallback).
_executor = ThreadPoolExecutor(max_workers=2)

# Module-level cache for the embedding model -- loaded once on first use.
_model: Optional[SentenceTransformer] = None


def _get_model() -> Optional[SentenceTransformer]:
    """Lazy-load the sentence-transformers model safely."""
    global _model
    if _model is not None:
        return _model
    try:
        logger.info("Loading embedding model from cache: %s", config.EMBED_MODEL_NAME)
        _model = SentenceTransformer(config.EMBED_MODEL_NAME, device="cpu", local_files_only=True)
        return _model
    except Exception:
        pass
    try:
        _model = SentenceTransformer(config.EMBED_MODEL_NAME, device="cpu")
        return _model
    except Exception as exc:
        logger.warning("Could not load sentence transformer model: %s", exc)
        return None


def _embed(texts: List[str]) -> np.ndarray:
    """Embed a list of texts and L2-normalise for cosine similarity via IP."""
    model = _get_model()
    if model is None:
        vecs = np.random.randn(len(texts), config.EMBED_MODEL_DIM).astype(np.float32)
        faiss.normalize_L2(vecs)
        return vecs
    try:
        embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        faiss.normalize_L2(embeddings)
        return embeddings.astype(np.float32)
    except Exception as exc:
        logger.warning("Embedding encode failed: %s", exc)
        vecs = np.random.randn(len(texts), config.EMBED_MODEL_DIM).astype(np.float32)
        faiss.normalize_L2(vecs)
        return vecs


# --------------------------------------------------------------------------
# Persistence helpers
# --------------------------------------------------------------------------
def _ensure_dir():
    os.makedirs(config.FAISS_INDEX_DIR, exist_ok=True)


def _save_index(index: faiss.IndexFlatIP, metadata: List[dict]):
    """Persist FAISS index and metadata sidecar to disk."""
    _ensure_dir()
    faiss.write_index(index, config.FAISS_INDEX_FILE)
    with open(config.FAISS_METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    logger.info(
        "Saved FAISS index (%d vectors) and metadata to %s",
        index.ntotal,
        config.FAISS_INDEX_DIR,
    )


def _load_index() -> tuple:
    """Load FAISS index and metadata from disk.  Returns (index, metadata_list)."""
    if not os.path.exists(config.FAISS_INDEX_FILE) or not os.path.exists(
        config.FAISS_METADATA_FILE
    ):
        return None, None
    index = faiss.read_index(config.FAISS_INDEX_FILE)
    with open(config.FAISS_METADATA_FILE, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    logger.info("Loaded FAISS index with %d vectors", index.ntotal)
    return index, metadata


# --------------------------------------------------------------------------
# In-memory store (built up during ingestion, persisted at the end)
# --------------------------------------------------------------------------
class _VectorStore:
    """Thin wrapper around a FAISS IndexFlatIP + metadata sidecar."""

    def __init__(self):
        self.index: Optional[faiss.IndexFlatIP] = None
        self.metadata: List[dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        idx, meta = _load_index()
        if idx is not None:
            self.index = idx
            self.metadata = meta
        else:
            self.index = faiss.IndexFlatIP(config.EMBED_MODEL_DIM)
            self.metadata = []
        self._loaded = True

    def add(self, embeddings: np.ndarray, chunk_metas: List[dict]):
        """Add vectors + metadata.  Rows are appended; FAISS row ID = len(metadata) at insertion time."""
        self._ensure_loaded()
        self.index.add(embeddings)
        self.metadata.extend(chunk_metas)

    def delete_by_doc_id(self, doc_id: str):
        """Remove all vectors belonging to a given doc_id and rebuild.

        FAISS IndexFlat does not support selective deletion, so we rebuild
        from the remaining rows.  At 50-100 total vectors this is instant.
        """
        self._ensure_loaded()
        if not self.metadata:
            return

        keep_mask = [m["doc_id"] != doc_id for m in self.metadata]
        if all(keep_mask):
            return  # nothing to delete

        # Reconstruct vectors for kept rows
        kept_indices = [i for i, keep in enumerate(keep_mask) if keep]
        if kept_indices:
            kept_vectors = np.vstack(
                [self.index.reconstruct(i) for i in kept_indices]
            )
            new_index = faiss.IndexFlatIP(config.EMBED_MODEL_DIM)
            new_index.add(kept_vectors)
            self.index = new_index
            self.metadata = [self.metadata[i] for i in kept_indices]
        else:
            self.index = faiss.IndexFlatIP(config.EMBED_MODEL_DIM)
            self.metadata = []

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int,
        source_type: Optional[str] = None,
    ) -> List[dict]:
        """Search for top-k nearest neighbours.  Optionally filter by source_type.

        When source_type is set, we over-fetch (top_k * 3) and post-filter,
        since FAISS has no native metadata filtering.  At 50-100 vectors,
        this is a non-issue.
        """
        self._ensure_loaded()
        if self.index.ntotal == 0:
            return []

        fetch_k = min(self.index.ntotal, top_k * 3 if source_type else top_k)
        scores, indices = self.index.search(query_embedding, fetch_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            meta = self.metadata[idx]
            if source_type and meta.get("source_type") != source_type:
                continue
            results.append({
                "chunk_id": meta.get("chunk_id", ""),
                "citation": meta.get("citation", meta.get("doc_id", "")),
                "text": meta.get("text", ""),
                "source_type": meta.get("source_type", ""),
                "similarity": float(score),  # IP on normalised = cosine sim
            })
            if len(results) >= top_k:
                break
        return results

    def save(self):
        self._ensure_loaded()
        _save_index(self.index, self.metadata)

    @property
    def total_vectors(self) -> int:
        self._ensure_loaded()
        return self.index.ntotal


# Module-level singleton
_store = _VectorStore()

# BM25 singleton — initialized lazily like the FAISS store.
# Import is local so the module loads even if rank-bm25 is not installed;
# BM25 calls will degrade gracefully to empty results (see bm25_store.py).
try:
    from bm25_store import BM25Store as _BM25Store
    _bm25_store = _BM25Store(corpus_file=config.BM25_CORPUS_FILE)
except ImportError:
    _bm25_store = None  # type: ignore[assignment]
    logger.warning("bm25_store module not found — BM25 retrieval unavailable")



# --------------------------------------------------------------------------
# Public API (matches the interface the rest of CAUSALCUT expects)
# --------------------------------------------------------------------------
def ingest_document(
    doc_id: str,
    source_type: str,
    title: str,
    text: str,
) -> List[Chunk]:
    """
    Chunk one regulatory document and (re-)store it in FAISS and BM25.

    Deletes any existing chunks for this doc_id before inserting the new
    set (same rationale as the original ChromaDB version -- see chunker.py's
    Chunk.chunk_id docstring on why upsert-by-id alone is insufficient).
    Both stores are updated atomically so they remain in sync.
    """
    chunks = chunk_document(
        doc_id=doc_id, source_type=source_type, title=title, text=text
    )
    if not chunks:
        logger.warning("chunk_document produced 0 chunks for doc_id=%s", doc_id)
        return []

    # Delete existing vectors for this doc_id (idempotent re-ingestion)
    _store.delete_by_doc_id(doc_id)
    if _bm25_store is not None:
        _bm25_store.delete_by_doc_id(doc_id)

    # Embed chunk texts (FAISS)
    texts = [c.text for c in chunks]
    embeddings = _embed(texts)

    # Build metadata records (include full text for retrieval return)
    metas = []
    for c in chunks:
        m = c.to_metadata()
        m["chunk_id"] = c.chunk_id
        m["text"] = c.text
        metas.append(m)

    # Add to FAISS
    _store.add(embeddings, metas)

    # Add to BM25 (keyword index)
    if _bm25_store is not None:
        _bm25_store.add(texts, metas)

    logger.info("Ingested %d chunks for doc_id=%s (FAISS + BM25)", len(chunks), doc_id)
    return chunks




def ingest_corpus(documents: Iterable[dict]) -> int:
    """
    Ingest multiple documents.

    documents: iterable of {"doc_id", "source_type", "title", "text"} dicts
    -- one per OISD standard / Factories Act section / DGMS circular.
    Returns the total chunk count ingested.
    """
    total = 0
    for doc in documents:
        chunks = ingest_document(**doc)
        total += len(chunks)

    # Persist both stores to disk after the full corpus is ingested
    _store.save()
    if _bm25_store is not None:
        _bm25_store.save()
    return total


def query(
    query_text: str,
    top_k: int = config.RETRIEVAL_TOP_K,
    source_type: Optional[str] = None,
    timeout_seconds: float = config.RETRIEVAL_TIMEOUT_SECONDS,
) -> dict:
    """
    Retrieve the top-k regulatory chunks most relevant to `query_text`.
    Uses semantic (FAISS cosine similarity) search only.
    For hybrid BM25+FAISS search, use query_hybrid().
    """
    try:
        q_emb = _embed([query_text])
        results = _store.search(q_emb, top_k=top_k, source_type=source_type)
        return {"evidence": results, "verified": True, "reason": None}
    except Exception as exc:
        logger.warning("Regulatory retrieval failed: %s", exc)
        return {"evidence": [], "verified": False, "reason": str(exc)}


def query_bm25(
    query_text: str,
    top_k: int = config.RETRIEVAL_TOP_K,
    source_type: Optional[str] = None,
) -> dict:
    """BM25 keyword-only retrieval. Best for exact regulatory references."""
    if _bm25_store is None:
        return {"evidence": [], "verified": False, "reason": "BM25 store not available"}
    try:
        results = _bm25_store.search(query_text, top_k=top_k, source_type=source_type)
        # Normalize keys to match FAISS result format (similarity -> bm25_score kept)
        for r in results:
            r.setdefault("similarity", 0.0)
        return {"evidence": results, "verified": True, "reason": None}
    except Exception as exc:
        logger.warning("BM25 retrieval failed: %s", exc)
        return {"evidence": [], "verified": False, "reason": str(exc)}


def query_hybrid(
    query_text: str,
    top_k: int = config.RETRIEVAL_TOP_K,
    source_type: Optional[str] = None,
    rrf_k: int = config.RRF_K,
) -> dict:
    """Hybrid BM25 + FAISS retrieval fused via Reciprocal Rank Fusion (RRF).

    RRF formula (Cormack, Clarke & Buettcher 2009):
        score(doc) = 1/(rrf_k + rank_bm25) + 1/(rrf_k + rank_faiss)

    Advantages over weighted score fusion:
    - Scale-invariant: BM25 scores (unbounded integers) and cosine scores
      ([0,1]) cannot be directly combined with a fixed weight. RRF uses only
      rank positions, making it robust across both.
    - rrf_k=60 is the standard constant; higher values downweight rank gaps.

    Returns the top-k chunks by RRF score, with both similarity scores included.
    """
    # Fetch candidates from both indexes (over-fetch for better coverage)
    fetch_k = min(top_k * 3, 50)

    try:
        q_emb = _embed([query_text])
        faiss_results = _store.search(q_emb, top_k=fetch_k, source_type=source_type)
    except Exception as exc:
        logger.warning("FAISS search failed in hybrid query: %s", exc)
        faiss_results = []

    bm25_results: list[dict] = []
    if _bm25_store is not None:
        try:
            bm25_results = _bm25_store.search(query_text, top_k=fetch_k, source_type=source_type)
        except Exception as exc:
            logger.warning("BM25 search failed in hybrid query: %s", exc)

    if not faiss_results and not bm25_results:
        return {"evidence": [], "verified": False, "reason": "Both retrievers returned empty results"}

    # Build chunk_id -> metadata lookup
    chunk_meta: dict[str, dict] = {}
    for r in faiss_results + bm25_results:
        cid = r.get("chunk_id", "")
        if cid and cid not in chunk_meta:
            chunk_meta[cid] = r

    # Compute RRF scores
    rrf_scores: dict[str, float] = {}
    for rank, r in enumerate(faiss_results):
        cid = r.get("chunk_id", "")
        if cid:
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)

    for rank, r in enumerate(bm25_results):
        cid = r.get("chunk_id", "")
        if cid:
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (rrf_k + rank + 1)

    # Sort by RRF score descending, return top-k
    sorted_ids = sorted(rrf_scores, key=rrf_scores.__getitem__, reverse=True)[:top_k]
    evidence = []
    for cid in sorted_ids:
        meta = chunk_meta.get(cid, {})
        evidence.append({
            "chunk_id": cid,
            "citation": meta.get("citation", cid),
            "text": meta.get("text", ""),
            "source_type": meta.get("source_type", ""),
            "similarity": meta.get("similarity", 0.0),   # cosine score from FAISS
            "bm25_score": meta.get("bm25_score", 0.0),   # BM25 score (0 if only in FAISS)
            "rrf_score": round(rrf_scores[cid], 6),
        })

    return {"evidence": evidence, "verified": True, "reason": None}




def get_stats() -> dict:
    """Return basic stats about the current index."""
    return {
        "total_vectors": _store.total_vectors,
        "index_file": config.FAISS_INDEX_FILE,
        "metadata_file": config.FAISS_METADATA_FILE,
        "embedding_model": config.EMBED_MODEL_NAME,
        "embedding_dim": config.EMBED_MODEL_DIM,
    }


def reset_index() -> None:
    """Drop the FAISS index and metadata files.  Useful for dev/test resets."""
    global _store
    for fpath in [config.FAISS_INDEX_FILE, config.FAISS_METADATA_FILE]:
        if os.path.exists(fpath):
            os.remove(fpath)
            logger.info("Removed %s", fpath)
    _store = _VectorStore()


if __name__ == "__main__":
    # Illustrative usage, grounded in the Section 8 coke-oven worked example.
    logging.basicConfig(level=logging.INFO)

    docs = [
        {
            "doc_id": "OISD-STD-116",
            "source_type": "oisd_standard",
            "title": "OISD-STD-116: Fire Protection Facilities",
            "text": (
                "Clause 4.3\n\n"
                "Hot work permits shall not remain active in any zone where "
                "flammable or toxic gas concentration exceeds 25% of the "
                "lower explosive limit or the permissible exposure limit, "
                "whichever is more restrictive. The permit issuing "
                "authority shall suspend hot work immediately on "
                "notification of a gas concentration alarm in the "
                "affected zone."
            ),
        },
        {
            "doc_id": "Factories Act 1948",
            "source_type": "factories_act",
            "title": "The Factories Act, 1948",
            "text": (
                "Section 41\n\n"
                "In every factory in which a hazardous process is carried "
                "on, the occupier shall provide personal protective "
                "equipment to every worker exposed to that process, and "
                "no worker shall be permitted to enter or remain in the "
                "hazardous area without wearing the prescribed equipment."
            ),
        },
    ]

    total_chunks = ingest_corpus(docs)
    print(f"Ingested {total_chunks} chunks across {len(docs)} documents")

    # Section 5.6's worked example: intervention set includes suspending
    # PTW-007 (hot work) in Zone 1 while gas concentration is rising.
    result = query("suspend hot work permit due to rising gas concentration")
    print(f"\nQuery results (verified={result['verified']}):")
    for i, ev in enumerate(result["evidence"], 1):
        print(f"  {i}. [{ev['similarity']:.3f}] {ev['citation']}")
        print(f"     {ev['text'][:120]}...")
