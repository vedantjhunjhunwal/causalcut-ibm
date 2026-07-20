# CAUSALCUT Regulatory RAG Module

This module provides a standalone FAISS-backed Vector Search (RAG) engine for regulatory texts, as outlined in the CAUSALCUT Safety Twin Design Document.

## Features
- **FastAPI Interface**: Exposes endpoints for single (`/query`) and batch (`/query/batch`) semantic retrieval.
- **FAISS Vector Store**: Uses `IndexFlatIP` with `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` for low-latency cosine similarity search.
- **Authentic Regulatory Data**: Ships with official, pre-ingested texts from OSHA (1910.119, 1910.146, etc.) and the Factories Act 1948.
- **Zero-Dependency Core**: Can be imported directly into Python applications without needing the API server.

---

## 1. Directory Structure

The module is organized into the `regulatory_rag/` directory:

```text
regulatory_rag/
├── api.py                      # FastAPI server and endpoints
├── vector_store.py             # FAISS interface and search logic
├── chunker.py                  # Text chunking and budgeting logic
├── config.py                   # System configuration and hyperparameters
├── ingest_regulatory_corpus.py # Script to rebuild the vector database
├── fetch_regulatory_docs.py    # Script to download authentic safety rules
├── fetch_and_extract.py        # HTML parsing logic for OSHA/Factories Act
├── test_api.py                 # Smoke-tests for the API endpoints
├── test_chunker_budget.py      # Unit tests for the chunker
├── regulatory_docs/            # Raw Python modules containing text data
└── faiss_store/                # Compiled FAISS index and JSON metadata
```

---

## 2. Running the API Server

The simplest way to use this module is via the standalone HTTP API. 

### Prerequisites
Make sure you have installed the required dependencies in your environment:
```cmd
pip install fastapi uvicorn[standard] sentence-transformers faiss-cpu pydantic requests
```

### Start the Server
Navigate to the `regulatory_rag` directory and start the `uvicorn` server:
```cmd
cd regulatory_rag
python api.py
```
*(Alternatively: `uvicorn api:app --port 8000 --reload`)*

The server will automatically load the embedding model and the `faiss_store` index into memory on startup.

### Interactive Documentation
Once running, navigate to:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 3. API Usage (cURL Examples)

### Check Health & Index Status
```cmd
curl -X GET http://localhost:8000/health
```

### Query for Relevant Regulatory Clauses
Pass a natural-language description of an incident or safety procedure:
```cmd
curl -X POST http://localhost:8000/query ^
     -H "Content-Type: application/json" ^
     -d "{\"query\": \"suspend hot work permit due to rising gas concentration\", \"top_k\": 5}"
```

**Filtering by Source Type**:
You can restrict the search to a specific regulatory body (e.g., OSHA, Factories Act, DGMS):
```cmd
curl -X POST http://localhost:8000/query ^
     -H "Content-Type: application/json" ^
     -d "{\"query\": \"dangerous fumes confined space\", \"top_k\": 3, \"source_type\": \"factories_act\"}"
```

### Batch Queries
Send up to 10 queries at once for bulk processing:
```cmd
curl -X POST http://localhost:8000/query/batch ^
     -H "Content-Type: application/json" ^
     -d "{\"queries\": [{\"query\": \"ventilation requirements\", \"top_k\": 2}, {\"query\": \"PPE in hazardous areas\", \"top_k\": 2}]}"
```

---

## 4. Native Python Integration

If you prefer to integrate the vector store directly into the main Python backend (bypassing the HTTP API), you can import `vector_store` natively.

```python
import sys
sys.path.append("path/to/regulatory_rag")

from regulatory_rag import vector_store

# Query the store natively (loads model and index automatically on first call)
result = vector_store.query(
    query_text="worker must wear personal protective equipment in hazardous area",
    top_k=5,
    source_type="oisd_standard", # Optional filter
    timeout_seconds=2.0          # Hard timeout to prevent blocking
)

if result["verified"]:
    for chunk in result["evidence"]:
        print(f"[{chunk['similarity']:.3f}] {chunk['citation']}: {chunk['text'][:100]}...")
else:
    print(f"Retrieval failed or timed out: {result['reason']}")
```

---

## 5. Rebuilding the Knowledge Base

If you add new documents to `regulatory_docs/` or modify existing ones, you must rebuild the FAISS index:

```cmd
cd regulatory_rag
python ingest_regulatory_corpus.py --reset
```
This will chunk all texts, compute embeddings, and overwrite the `faiss_store/` directory with the new index.
