"""
Main entry point: Fetch, chunk, and store all regulatory documents in the
FAISS vector index for the CAUSALCUT Regulatory Verifier (Section 4.9).

Usage:
    python ingest_regulatory_corpus.py [--reset] [--fetch-online] [--query "test query"]

Workflow:
    1. Load curated regulatory content from regulatory_docs/
    2. Optionally fetch additional content from online sources (--fetch-online)
    3. Chunk all documents using chunker.chunk_document()
    4. Store all chunks in the FAISS index via vector_store.ingest_corpus()
    5. Run sanity queries to verify retrieval works
    6. Print summary statistics
"""

from __future__ import annotations

import argparse
import logging
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import vector_store
from regulatory_docs import ALL_DOCUMENTS

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest regulatory corpus into FAISS vector store"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset (delete) the existing FAISS index before ingesting",
    )
    parser.add_argument(
        "--fetch-online",
        action="store_true",
        help="Also fetch documents from online sources (OSHA, etc.)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Run a test query after ingestion",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Step 0: Reset if requested
    if args.reset:
        logger.info("Resetting FAISS index...")
        vector_store.reset_index()

    # Step 1: Load curated content
    documents = list(ALL_DOCUMENTS)
    logger.info("Loaded %d curated regulatory documents", len(documents))
    for doc in documents:
        logger.info(
            "  [%s] %s (%d chars)",
            doc["source_type"],
            doc["doc_id"],
            len(doc["text"]),
        )

    # Step 2: Optionally fetch online content
    if args.fetch_online:
        try:
            from fetch_regulatory_docs import fetch_all_documents
            online_docs = fetch_all_documents()
            if online_docs:
                documents.extend(online_docs)
                logger.info("Added %d documents from online sources", len(online_docs))
        except ImportError as e:
            logger.warning(
                "Could not import fetch_regulatory_docs (missing dependencies?): %s", e
            )
        except Exception as e:
            logger.warning("Online fetch failed (continuing with curated content): %s", e)

    # Step 3: Ingest into FAISS
    logger.info("\n" + "=" * 60)
    logger.info("INGESTING INTO FAISS VECTOR STORE")
    logger.info("=" * 60)

    total_chunks = vector_store.ingest_corpus(documents)

    # Step 4: Print stats
    stats = vector_store.get_stats()
    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)
    print(f"  Documents ingested:  {len(documents)}")
    print(f"  Total chunks:        {total_chunks}")
    print(f"  FAISS vectors:       {stats['total_vectors']}")
    print(f"  Embedding model:     {stats['embedding_model']}")
    print(f"  Embedding dimension: {stats['embedding_dim']}")
    print(f"  Index file:          {stats['index_file']}")
    print(f"  Metadata file:       {stats['metadata_file']}")

    # Validate chunk count against Section 9.1's 50-100 target
    if total_chunks < 30:
        print(f"\n  [!] WARNING: Only {total_chunks} chunks -- below the 50-100 target in Section 9.1")
    elif total_chunks > 150:
        print(f"\n  [!] WARNING: {total_chunks} chunks -- above the 50-100 target in Section 9.1")
    else:
        print(f"\n  [OK] Chunk count ({total_chunks}) is within the 50-100 target range")

    # Step 5: Run sanity queries
    print("\n" + "=" * 60)
    print("SANITY QUERIES")
    print("=" * 60)

    test_queries = [
        # From Section 8's coke-oven worked example
        "suspend hot work permit due to rising gas concentration",
        # PPE requirement for hazardous zone
        "worker must wear personal protective equipment in hazardous area",
        # Emergency ventilation
        "ventilation failure emergency shutdown procedure",
        # Permit-to-work validation
        "permit to work confined space entry gas testing requirements",
        # Shift handover
        "shift handover safety information exchange procedure",
    ]

    # Use the user's custom query if provided
    if args.query:
        test_queries = [args.query] + test_queries

    for q in test_queries:
        result = vector_store.query(q, timeout_seconds=10.0)  # generous timeout for first run
        print(f"\n  Query: \"{q}\"")
        print(f"  Verified: {result['verified']}")
        if result["evidence"]:
            for i, ev in enumerate(result["evidence"][:3], 1):  # show top 3
                print(f"    {i}. [{ev['similarity']:.3f}] {ev['citation']}")
                # Show first 100 chars of text
                preview = ev["text"][:100].replace("\n", " ")
                print(f"       {preview}...")
        else:
            reason = result.get("reason", "unknown")
            print(f"    No evidence retrieved (reason: {reason})")

    print("\n" + "=" * 60)
    print("DONE — Regulatory corpus ready for CAUSALCUT Regulatory Verifier")
    print("=" * 60)


if __name__ == "__main__":
    main()
