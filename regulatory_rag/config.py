"""
Configuration for the regulatory RAG pipeline (design doc Sections 4.9,
7.5, 9.1; Appendix A's "Regulatory retrieval failure" row).

Embedding model choice
-----------------------
Section 4.9 specifies "sentence-transformers" without naming a model, and
Section 7.5 asks for "~500-token passages." Section 9.1 caps the whole
corpus at 50-100 chunks, so model size/speed is not a real constraint here
-- retrieval quality and honest chunk-size-vs-model-limit alignment are.

Picked: multi-qa-MiniLM-L6-cos-v1 (verified against its HF model card)
  - Purpose-built for *asymmetric* query -> passage retrieval (short query,
    longer passage), which is the actual shape of this task: a proposed
    intervention description as the query, a regulatory clause as the
    passage. The more commonly reached-for all-MiniLM-L6-v2 is a symmetric
    sentence-similarity model and is a weaker fit for that shape.
  - Hard truncation ceiling: 512 word pieces (model card: "there is a limit
    of 512 word pieces; text longer than that will be truncated").
  - Effective quality ceiling: the same model card states it "was just
    trained on input text up to 250 word pieces. It might not work well
    for longer text." Chunks pushed close to 512 will not truncate but
    will silently degrade retrieval quality -- arguably worse than
    truncation, since nothing flags it.
  - 384-dim output, ~22M params -- trivial CPU inference at this corpus
    size, in keeping with Appendix B's "minimal dependencies" mandate.

This resolves a latent inconsistency in the design doc: Section 7.5 asks
for ~500-token passages, but no commonly-used lightweight sentence-
transformers model embeds 500 tokens at full quality (this one's usable
range is closer to 250). CHUNK_TARGET_TOKENS below is set against the
*effective* ceiling, not the hard truncation ceiling -- log this reasoning
in the design doc itself if this needs to survive review, since "500
tokens" appears there as a concrete spec.
"""

import os

EMBED_MODEL_NAME = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
EMBED_MODEL_DIM = 384
EMBED_MODEL_HARD_TOKEN_LIMIT = 512        # silent truncation past this (model card)
EMBED_MODEL_EFFECTIVE_TOKEN_LIMIT = 250   # quality degrades past this (model card)

# Kept well under the *effective* ceiling (250) to absorb:
#  (a) the ~10-15% error margin of chunker.py's regex token estimator vs.
#      the model's real WordPiece tokenizer -- legal/technical vocabulary
#      (hyphenated terms, "41(2)"-style citations) tends toward *more*
#      WordPieces than the regex estimate, not fewer, so the margin should
#      not be spent optimistically;
#  (b) normal chunk-boundary variance from paragraph-greedy packing.
CHUNK_TARGET_TOKENS = 200
CHUNK_OVERLAP_TOKENS = 40   # ~20% of target; standard RAG range is 10-20%
MIN_CHUNK_TOKENS = 40       # trailing slivers below this get merged into the previous chunk

VALID_SOURCE_TYPES = {
    "oisd_standard",   # OISD Standards
    "factories_act",   # Factories Act 1948
    "dgms_circular",   # DGMS Circulars
}

# --------------------------------------------------------------------------
# FAISS (Section 4.9: "FAISS vector index"; Appendix B: "Vector Search
# (RAG): FAISS -- efficient similarity search, minimal dependencies")
# --------------------------------------------------------------------------
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_INDEX_DIR = os.path.join(_BASE_DIR, "faiss_store")
FAISS_INDEX_FILE = os.path.join(FAISS_INDEX_DIR, "regulatory.index")
FAISS_METADATA_FILE = os.path.join(FAISS_INDEX_DIR, "regulatory_metadata.json")

# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
RETRIEVAL_TOP_K = 5                 # Section 4.9: "top-5 relevant chunks"
RETRIEVAL_TIMEOUT_SECONDS = 1.0     # Section 4.9 latency target is <1s end-to-end;
                                     # Appendix A: "[FAISS] query timeout -> proceed
                                     # without regulatory evidence, flag unverified"

# -------------------------------------------------------------------------- #
# BM25 hybrid search (Q10)
# -------------------------------------------------------------------------- #
# Tokenized corpus sidecar for BM25Okapi. Stored alongside the FAISS index
# so both indexes are always in sync (ingest_document updates both atomically).
BM25_CORPUS_FILE = os.path.join(FAISS_INDEX_DIR, "bm25_corpus.json")

# BM25 Okapi parameters (standard defaults from Robertson & Sparck Jones 1994)
BM25_K1: float = 1.5    # term frequency saturation
BM25_B: float = 0.75    # document length normalization

# Reciprocal Rank Fusion constant (Cormack, Clarke & Buettcher 2009)
RRF_K: int = 60

# Retrieval mode: "hybrid" (BM25 + FAISS fused via RRF), "semantic" (FAISS only),
# "keyword" (BM25 only). Override via RETRIEVAL_MODE env var.
RETRIEVAL_MODE: str = os.getenv("RETRIEVAL_MODE", "hybrid")

