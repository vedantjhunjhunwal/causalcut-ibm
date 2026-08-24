"""
FastAPI query interface for the CAUSALCUT Regulatory RAG system.

Design doc Section 4.9:
  "FAISS vector index over chunked regulatory text (OISD standards,
   Factories Act 1948, DGMS circulars); cosine similarity retrieval
   of top-5 relevant chunks"

Endpoints
---------
POST /query
    Main retrieval endpoint.  Accepts a natural-language query and returns
    the top-k most relevant regulatory chunks with cosine similarity scores.

POST /query/batch
    Batch version — accepts up to 10 queries in a single request.

GET  /health
    Liveness check; also returns index stats (vector count, model name, etc.)

GET  /sources
    Lists the distinct source types currently in the index.

GET  /docs
    Auto-generated interactive Swagger UI (from FastAPI / OpenAPI).

GET  /redoc
    Alternative ReDoc documentation UI.

Usage (dev server)
------------------
    # From the project root, with .venv activated:
    uvicorn api:app --reload --port 8000

    # Or directly:
    python api.py

Example curl request:
    curl -X POST http://localhost:8000/query \\
         -H "Content-Type: application/json" \\
         -d '{"query": "suspend hot work permit due to rising gas concentration", "top_k": 5}'
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import config
import vector_store

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="CAUSALCUT Regulatory RAG API",
    description=(
        "Query interface for the CAUSALCUT Safety Twin regulatory knowledge base.\n\n"
        "The index contains chunked regulatory text from:\n"
        "- **OISD Standards** (Oil Industry Safety Directorate)\n"
        "- **Factories Act 1948** (official text from indiacode.nic.in)\n"
        "- **DGMS Circulars** (Directorate General of Mines Safety)\n"
        "- **OSHA Standards** (official text from osha.gov)\n\n"
        "Retrieval uses cosine similarity on `multi-qa-MiniLM-L6-cos-v1` embeddings "
        "stored in a FAISS `IndexFlatIP` index.\n\n"
        "**Design doc reference**: Section 4.9, 7.5, 9.1; Appendix A (timeout fallback)."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow all origins in dev; restrict in prod via env var ALLOWED_ORIGINS
_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Request body for a single regulatory query."""
    query: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Natural-language safety query or intervention description.",
        examples=["suspend hot work permit due to rising gas concentration"],
    )
    top_k: int = Field(
        default=config.RETRIEVAL_TOP_K,
        ge=1,
        le=20,
        description="Number of top chunks to return (default: 5, max: 20).",
    )
    source_type: Optional[str] = Field(
        default=None,
        description=(
            "Filter results to a specific source type. "
            f"Valid values: {sorted(config.VALID_SOURCE_TYPES)}. "
            "Omit to search across all sources."
        ),
    )
    timeout_seconds: float = Field(
        default=config.RETRIEVAL_TIMEOUT_SECONDS,
        ge=0.1,
        le=30.0,
        description="Max seconds to wait for FAISS search before returning an unverified result.",
    )
    mode: str = Field(
        default=config.RETRIEVAL_MODE,
        description=(
            "Retrieval mode: 'hybrid' (BM25 + FAISS fused via RRF — recommended), "
            "'semantic' (FAISS cosine similarity only), "
            "'keyword' (BM25 term matching only). "
            "Hybrid improves recall for exact clause references (e.g. 'OISD-116 §4.3', 'LEL')."
        ),
    )

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in config.VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{v}'. "
                f"Must be one of: {sorted(config.VALID_SOURCE_TYPES)}"
            )
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid = {"hybrid", "semantic", "keyword"}
        if v not in valid:
            raise ValueError(f"Invalid mode '{v}'. Must be one of: {sorted(valid)}")
        return v


class EvidenceChunk(BaseModel):
    """A single retrieved regulatory chunk."""
    rank: int = Field(description="1-indexed rank by similarity score.")
    chunk_id: str = Field(description="Unique chunk identifier (doc_id + chunk index).")
    citation: str = Field(description="Human-readable source citation (e.g. 'OISD-STD-116 Clause 4.3').")
    source_type: str = Field(description="Source category (oisd_standard | factories_act | dgms_circular).")
    similarity: float = Field(description="Cosine similarity score (0-1, higher is more relevant).")
    text: str = Field(description="Full text of the retrieved chunk.")
    bm25_score: float = Field(default=0.0, description="BM25 term-match score (hybrid/keyword modes only).")
    rrf_score: float = Field(default=0.0, description="Reciprocal Rank Fusion score (hybrid mode only).")


class QueryResponse(BaseModel):
    """Response from a single regulatory query."""
    query: str = Field(description="The original query string.")
    mode: str = Field(default="hybrid", description="Retrieval mode used.")
    verified: bool = Field(
        description=(
            "True if retrieval completed within the timeout. "
            "False if retrieval timed out or errored — caller should "
            "treat the result as unverified (per design doc Appendix A)."
        )
    )
    reason: Optional[str] = Field(
        default=None,
        description="Populated when verified=False. Values: 'retrieval_timeout' | 'retrieval_error'.",
    )
    elapsed_ms: float = Field(description="Total server-side retrieval time in milliseconds.")
    total_results: int = Field(description="Number of chunks returned.")
    evidence: List[EvidenceChunk] = Field(description="Retrieved regulatory evidence, ranked by similarity.")


class BatchQueryRequest(BaseModel):
    """Request body for batch querying."""
    queries: List[QueryRequest] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List of up to 10 query requests to process in sequence.",
    )


class BatchQueryResponse(BaseModel):
    """Response for a batch of queries."""
    total_queries: int
    results: List[QueryResponse]


class HealthResponse(BaseModel):
    """Health check and index stats."""
    status: str
    index_ready: bool
    total_vectors: int
    embedding_model: str
    embedding_dim: int
    index_file: str
    metadata_file: str


class SourcesResponse(BaseModel):
    """Available source types in the index."""
    source_types: List[str]
    counts: dict


# ---------------------------------------------------------------------------
# Startup: warm up the embedding model so the first query isn't slow
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def _warm_up():
    """Pre-load the embedding model and FAISS index at startup."""
    logger.info("Warming up embedding model and FAISS index...")
    try:
        # This loads the model and the index into memory
        result = vector_store.query(
            "safety regulations",
            top_k=1,
            timeout_seconds=60.0,
        )
        stats = vector_store.get_stats()
        logger.info(
            "Startup complete: %d vectors loaded, model=%s",
            stats["total_vectors"],
            stats["embedding_model"],
        )
        if stats["total_vectors"] == 0:
            logger.warning(
                "FAISS index is empty! Run: python ingest_regulatory_corpus.py --reset"
            )
    except Exception:
        logger.exception("Startup warm-up failed (index may be empty or missing)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_evidence(raw_results: List[dict]) -> List[EvidenceChunk]:
    return [
        EvidenceChunk(
            rank=i + 1,
            chunk_id=r.get("chunk_id", ""),
            citation=r.get("citation", r.get("chunk_id", "")),
            source_type=r.get("source_type", ""),
            similarity=round(r.get("similarity", 0.0), 4),
            text=r.get("text", ""),
        )
        for i, r in enumerate(raw_results)
    ]


def _run_query(req: QueryRequest) -> QueryResponse:
    t0 = time.perf_counter()
    raw = vector_store.query(
        query_text=req.query,
        top_k=req.top_k,
        source_type=req.source_type,
        timeout_seconds=req.timeout_seconds,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    evidence = _build_evidence(raw.get("evidence", []))
    return QueryResponse(
        query=req.query,
        verified=raw["verified"],
        reason=raw.get("reason"),
        elapsed_ms=round(elapsed_ms, 2),
        total_results=len(evidence),
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, summary="Health check & index stats")
def health():
    """
    Returns liveness status and current FAISS index statistics.

    If `total_vectors` is 0, the index has not been populated yet.
    Run `python ingest_regulatory_corpus.py --reset` to populate it.
    """
    try:
        stats = vector_store.get_stats()
        return HealthResponse(
            status="ok",
            index_ready=stats["total_vectors"] > 0,
            total_vectors=stats["total_vectors"],
            embedding_model=stats["embedding_model"],
            embedding_dim=stats["embedding_dim"],
            index_file=stats["index_file"],
            metadata_file=stats["metadata_file"],
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Index unavailable: {exc}") from exc


@app.get("/sources", response_model=SourcesResponse, summary="Available source types")
def sources():
    """
    Returns the source types present in the index and the count of chunks per type.

    Useful for constructing filtered queries.
    """
    try:
        stats = vector_store.get_stats()
        if stats["total_vectors"] == 0:
            return SourcesResponse(source_types=[], counts={})

        # Count chunks per source_type by inspecting the metadata sidecar
        import json as _json
        meta_path = stats["metadata_file"]
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = _json.load(f)

        counts: dict[str, int] = {}
        for m in metadata:
            st = m.get("source_type", "unknown")
            counts[st] = counts.get(st, 0) + 1

        return SourcesResponse(
            source_types=sorted(counts.keys()),
            counts=counts,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/query",
    response_model=QueryResponse,
    summary="Query the regulatory knowledge base",
)
def query(req: QueryRequest):
    """
    Retrieve the most relevant regulatory chunks for a given query.

    **How it works**:
    1. The query is embedded with `multi-qa-MiniLM-L6-cos-v1`.
    2. FAISS performs cosine similarity search over the indexed regulatory corpus.
    3. The top-k chunks are returned with citation, source type, and similarity score.

    **Timeout behaviour** (per design doc Appendix A):
    If retrieval exceeds `timeout_seconds`, the response is returned with
    `verified: false` and `reason: "retrieval_timeout"` so the caller can
    proceed without regulatory evidence and flag the recommendation as unverified.

    **Filter by source**:
    Pass `source_type` to restrict results to a specific regulatory body
    (e.g. `"factories_act"`, `"oisd_standard"`, `"dgms_circular"`).
    """
    try:
        return _run_query(req)
    except Exception as exc:
        logger.exception("Query failed for: %r", req.query)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/query/batch",
    response_model=BatchQueryResponse,
    summary="Batch query the regulatory knowledge base",
)
def query_batch(req: BatchQueryRequest):
    """
    Run multiple queries in a single request (up to 10).

    Each query in the batch is processed independently with its own
    `top_k`, `source_type`, and `timeout_seconds` settings.
    """
    results = []
    for q in req.queries:
        try:
            results.append(_run_query(q))
        except Exception as exc:
            logger.exception("Batch sub-query failed: %r", q.query)
            results.append(
                QueryResponse(
                    query=q.query,
                    verified=False,
                    reason=f"error: {exc}",
                    elapsed_ms=0.0,
                    total_results=0,
                    evidence=[],
                )
            )
    return BatchQueryResponse(total_queries=len(results), results=results)


# ---------------------------------------------------------------------------
# G4 — Incident Pattern Intelligence: /patterns/query
# ---------------------------------------------------------------------------
import json as _json
import math as _math

_INCIDENTS_PATH = os.path.join(_HERE, "incident_corpus", "incidents.json")
_incidents_cache: list | None = None


def _load_incidents() -> list:
    global _incidents_cache
    if _incidents_cache is None:
        try:
            with open(_INCIDENTS_PATH, "r", encoding="utf-8") as f:
                _incidents_cache = _json.load(f)
        except Exception as exc:
            logger.warning("Could not load incident corpus: %s", exc)
            _incidents_cache = []
    return _incidents_cache


def _incident_similarity(incident: dict, pathway: str, factors: list[str]) -> float:
    """Simple Jaccard-style factor overlap score (0–1).

    Upgraded to full FAISS vector search when ingest_incidents.py is run.
    This lightweight version is sufficient for demo/hackathon purposes.
    """
    score = 0.0
    # Pathway match: +0.4 if same, +0.1 if substring
    inc_pathway = incident.get("pathway", "")
    if inc_pathway == pathway:
        score += 0.40
    elif pathway in inc_pathway or inc_pathway in pathway:
        score += 0.10

    # Factor overlap: Jaccard over factor sets
    inc_factors = set(incident.get("precursor_factors", []))
    query_factors = set(factors)
    if inc_factors or query_factors:
        intersection = len(inc_factors & query_factors)
        union = len(inc_factors | query_factors)
        score += 0.60 * (intersection / union) if union > 0 else 0.0

    return round(min(score, 1.0), 3)


class PatternQueryRequest(BaseModel):
    """Request body for incident pattern query."""
    pathway: str = Field(..., description="AccidentPath.pathway value")
    contributing_factors: List[str] = Field(
        default_factory=list,
        description="List of factor tags from AccidentPath.contributing_factors"
    )
    top_k: int = Field(default=5, ge=1, le=20)
    min_similarity: float = Field(default=0.15, ge=0.0, le=1.0)


class IncidentMatch(BaseModel):
    incident_id: str
    title: str
    similarity_score: float
    pathway: str
    summary: str
    precursor_factors: List[str]
    outcome: str
    source: str
    information_class: str
    synthetic_flag: bool
    oisd_clause: Optional[str] = None


class PatternQueryResponse(BaseModel):
    pathway_queried: str
    factors_queried: List[str]
    incidents: List[IncidentMatch]
    total_matches: int
    information_class: str = "R/S"
    note: str = (
        "Results include both real public-source incidents [R] and synthetic near-miss "
        "reports schema-matched to AccidentPath [S]. Synthetic records are clearly "
        "labelled and must not be presented as real historical data."
    )


@app.post(
    "/patterns/query",
    response_model=PatternQueryResponse,
    summary="Query incident corpus for similar historical patterns (G4)",
    description=(
        "Given an AccidentPath pathway and contributing factors, retrieves structurally "
        "similar historical incidents and near-miss reports from the incident corpus. "
        "Used by Agent 2 (Incident Pattern Mining) in the agent orchestrator. "
        "Corpus includes real public-source incidents [R] and synthetic near-miss "
        "reports [S] schema-matched to AccidentPath."
    ),
)
def patterns_query(req: PatternQueryRequest):
    """Retrieve similar incidents for an AccidentPath."""
    t0 = time.perf_counter()
    incidents = _load_incidents()

    scored = []
    for inc in incidents:
        sim = _incident_similarity(inc, req.pathway, req.contributing_factors)
        if sim >= req.min_similarity:
            scored.append((sim, inc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:req.top_k]

    matches = [
        IncidentMatch(
            incident_id=inc.get("incident_id", ""),
            title=inc.get("title", ""),
            similarity_score=sim,
            pathway=inc.get("pathway", ""),
            summary=inc.get("summary", ""),
            precursor_factors=inc.get("precursor_factors", []),
            outcome=inc.get("outcome", ""),
            source=inc.get("source", ""),
            information_class=inc.get("information_class", "S"),
            synthetic_flag=inc.get("synthetic_flag", True),
            oisd_clause=inc.get("oisd_clause"),
        )
        for sim, inc in top
    ]

    elapsed = (time.perf_counter() - t0) * 1000
    logger.info(
        "patterns/query: pathway=%s factors=%s -> %d matches in %.1fms",
        req.pathway, req.contributing_factors, len(matches), elapsed,
    )

    return PatternQueryResponse(
        pathway_queried=req.pathway,
        factors_queried=req.contributing_factors,
        incidents=matches,
        total_matches=len(matches),
    )


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
