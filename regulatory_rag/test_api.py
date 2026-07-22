"""
Smoke-tests for the CAUSALCUT Regulatory RAG API.

Runs against a *live* server started separately with:
    uvicorn api:app --port 8000

Or use the --start flag to launch it in the background before testing:
    python test_api.py --start

Usage:
    python test_api.py
    python test_api.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("requests not installed. Run: pip install requests")


def _pretty(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def run_tests(base: str):
    sep = "=" * 60
    passed = failed = 0

    def test(name: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}")
            if detail:
                print(f"         {detail}")

    print(f"\n{sep}")
    print(f"  CAUSALCUT RAG API smoke-tests -> {base}")
    print(sep)

    # ------------------------------------------------------------------
    # 1. GET /health
    # ------------------------------------------------------------------
    print("\n[GET /health]")
    r = requests.get(f"{base}/health", timeout=30)
    d = r.json()
    test("status 200",           r.status_code == 200)
    test("status == 'ok'",       d.get("status") == "ok")
    test("index_ready == True",  d.get("index_ready") is True, detail=str(d))
    test("total_vectors > 0",    d.get("total_vectors", 0) > 0, detail=str(d))
    print(f"  vectors={d.get('total_vectors')}  model={d.get('embedding_model')}")

    # ------------------------------------------------------------------
    # 2. GET /sources
    # ------------------------------------------------------------------
    print("\n[GET /sources]")
    r = requests.get(f"{base}/sources", timeout=10)
    d = r.json()
    test("status 200",               r.status_code == 200)
    test("source_types non-empty",   len(d.get("source_types", [])) > 0)
    print(f"  source_types={d.get('source_types')}")
    print(f"  counts={d.get('counts')}")

    # ------------------------------------------------------------------
    # 3. POST /query — canonical hot-work query from design doc Section 8
    # ------------------------------------------------------------------
    print("\n[POST /query] canonical hot-work example")
    payload = {
        "query": "suspend hot work permit due to rising gas concentration",
        "top_k": 5,
    }
    r = requests.post(f"{base}/query", json=payload, timeout=30)
    d = r.json()
    test("status 200",          r.status_code == 200)
    test("verified == True",    d.get("verified") is True)
    test("total_results == 5",  d.get("total_results") == 5, detail=str(d.get("total_results")))
    top = d.get("evidence", [{}])[0]
    test("top result has citation",   bool(top.get("citation")))
    test("top result has text",       bool(top.get("text")))
    test("top result similarity > 0", top.get("similarity", 0) > 0)
    print(f"  elapsed_ms={d.get('elapsed_ms')}  top=[{top.get('similarity'):.3f}] {top.get('citation')}")

    # ------------------------------------------------------------------
    # 4. POST /query — PPE query
    # ------------------------------------------------------------------
    print("\n[POST /query] PPE in hazardous area")
    payload = {
        "query": "worker must wear personal protective equipment in hazardous area",
        "top_k": 3,
    }
    r = requests.post(f"{base}/query", json=payload, timeout=30)
    d = r.json()
    test("status 200",         r.status_code == 200)
    test("verified == True",   d.get("verified") is True)
    test("total_results == 3", d.get("total_results") == 3)
    top = d.get("evidence", [{}])[0]
    print(f"  elapsed_ms={d.get('elapsed_ms')}  top=[{top.get('similarity'):.3f}] {top.get('citation')}")

    # ------------------------------------------------------------------
    # 5. POST /query — source_type filter
    # ------------------------------------------------------------------
    print("\n[POST /query] source_type=factories_act filter")
    payload = {
        "query": "dangerous fumes confined space entry",
        "top_k": 3,
        "source_type": "factories_act",
    }
    r = requests.post(f"{base}/query", json=payload, timeout=30)
    d = r.json()
    test("status 200",       r.status_code == 200)
    test("verified == True", d.get("verified") is True)
    all_factories = all(
        e.get("source_type") == "factories_act"
        for e in d.get("evidence", [])
    )
    test("all results are factories_act", all_factories, detail=str([e.get("source_type") for e in d.get("evidence", [])]))
    top = d.get("evidence", [{}])[0]
    print(f"  elapsed_ms={d.get('elapsed_ms')}  top=[{top.get('similarity'):.3f}] {top.get('citation')}")

    # ------------------------------------------------------------------
    # 6. POST /query — invalid source_type returns 422
    # ------------------------------------------------------------------
    print("\n[POST /query] invalid source_type -> 422")
    payload = {"query": "test", "source_type": "not_a_real_type"}
    r = requests.post(f"{base}/query", json=payload, timeout=10)
    test("status 422 on bad source_type", r.status_code == 422)

    # ------------------------------------------------------------------
    # 7. POST /query — query too short returns 422
    # ------------------------------------------------------------------
    print("\n[POST /query] too-short query -> 422")
    r = requests.post(f"{base}/query", json={"query": "a"}, timeout=10)
    test("status 422 on short query", r.status_code == 422)

    # ------------------------------------------------------------------
    # 8. POST /query/batch
    # ------------------------------------------------------------------
    print("\n[POST /query/batch]")
    payload = {
        "queries": [
            {"query": "permit to work confined space gas testing", "top_k": 3},
            {"query": "shift handover safety information exchange", "top_k": 3},
        ]
    }
    r = requests.post(f"{base}/query/batch", json=payload, timeout=60)
    d = r.json()
    test("status 200",          r.status_code == 200)
    test("total_queries == 2",  d.get("total_queries") == 2)
    test("all verified",        all(res.get("verified") for res in d.get("results", [])))
    for res in d.get("results", []):
        top = res.get("evidence", [{}])[0]
        print(f"  '{res.get('query')[:50]}' -> [{top.get('similarity'):.3f}] {top.get('citation')}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(sep + "\n")
    return failed == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smoke-test the RAG API")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the uvicorn server in the background before running tests",
    )
    args = parser.parse_args()

    proc = None
    if args.start:
        print("Starting uvicorn server...")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", "8000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(8)  # wait for startup + model warm-up

    try:
        ok = run_tests(args.base_url)
        sys.exit(0 if ok else 1)
    finally:
        if proc:
            proc.terminate()
