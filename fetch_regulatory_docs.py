"""
Fetch regulatory documents from legitimate public sources and supplement
the curated content in regulatory_docs/.

This script attempts to fetch additional regulatory content from official
government websites. Since many Indian regulatory standards (OISD, DGMS)
are available only as PDFs behind download portals, this script:

1. Tries to fetch publicly available regulatory text from official sources
2. Falls back to the curated content in regulatory_docs/ for sources that
   aren't freely scrapable
3. Caches all fetched content to regulatory_docs/fetched/ for offline use

Sources (all official government/regulatory body websites):
- OISD: oisd.gov.in (Oil Industry Safety Directorate)
- Factories Act 1948: indiacode.nic.in (India Code, Ministry of Law)
- DGMS: dgms.gov.in (Directorate General of Mines Safety)
- OSHA: osha.gov (US Occupational Safety & Health Administration)

Note: This is a best-effort fetcher. Many Indian regulatory standards are
distributed as PDFs and may not be freely scrapable as text. The curated
content in regulatory_docs/ provides the guaranteed baseline; this script
supplements it with whatever additional content can be retrieved.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_BASE_DIR, "regulatory_docs", "fetched")

# --------------------------------------------------------------------------
# Helper: HTTP fetch with retry and caching
# --------------------------------------------------------------------------

def _ensure_cache_dir():
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_path(doc_id: str) -> str:
    safe_id = re.sub(r"[^\w\-.]", "_", doc_id)
    return os.path.join(_CACHE_DIR, f"{safe_id}.txt")


def _read_cache(doc_id: str) -> Optional[str]:
    path = _cache_path(doc_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _write_cache(doc_id: str, text: str):
    _ensure_cache_dir()
    path = _cache_path(doc_id)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info("Cached %d chars for %s -> %s", len(text), doc_id, path)


def _fetch_url(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch a URL and return its text content.  Returns None on failure."""
    try:
        import requests
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return None


def _html_to_text(html: str) -> str:
    """Extract plain text from HTML.  Uses BeautifulSoup if available, else regex."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    except ImportError:
        # Fallback: strip HTML tags with regex
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

    # Clean up excessive whitespace while preserving paragraph breaks
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n\n".join(lines)


# --------------------------------------------------------------------------
# OSHA Standards (freely available from osha.gov)
# --------------------------------------------------------------------------

OSHA_SOURCES = [
    {
        "doc_id": "OSHA-1910.119",
        "source_type": "oisd_standard",  # mapped to closest valid type
        "title": "OSHA 29 CFR 1910.119 - Process Safety Management of Highly Hazardous Chemicals",
        "url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.119",
    },
    {
        "doc_id": "OSHA-1910.146",
        "source_type": "oisd_standard",
        "title": "OSHA 29 CFR 1910.146 - Permit-required Confined Spaces",
        "url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.146",
    },
    {
        "doc_id": "OSHA-1910.132",
        "source_type": "oisd_standard",
        "title": "OSHA 29 CFR 1910.132 - Personal Protective Equipment - General Requirements",
        "url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.132",
    },
    {
        "doc_id": "OSHA-1910.252",
        "source_type": "oisd_standard",
        "title": "OSHA 29 CFR 1910.252 - General Requirements for Welding and Cutting (Hot Work)",
        "url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.252",
    },
]


def fetch_osha_standards() -> List[dict]:
    """Fetch OSHA regulatory standards from osha.gov (public domain)."""
    documents = []
    for source in OSHA_SOURCES:
        doc_id = source["doc_id"]

        # Check cache first
        cached = _read_cache(doc_id)
        if cached:
            logger.info("Using cached content for %s", doc_id)
            documents.append({
                "doc_id": doc_id,
                "source_type": source["source_type"],
                "title": source["title"],
                "text": cached,
            })
            continue

        # Fetch from osha.gov
        logger.info("Fetching %s from %s", doc_id, source["url"])
        html = _fetch_url(source["url"])
        if html:
            text = _html_to_text(html)
            # OSHA pages have a lot of navigation/boilerplate — extract the
            # main regulatory text section
            text = _extract_osha_body(text, doc_id)
            if len(text) > 200:  # sanity check: got meaningful content
                _write_cache(doc_id, text)
                documents.append({
                    "doc_id": doc_id,
                    "source_type": source["source_type"],
                    "title": source["title"],
                    "text": text,
                })
                logger.info("Fetched %d chars for %s", len(text), doc_id)
            else:
                logger.warning("Fetched content too short for %s (%d chars), skipping", doc_id, len(text))
        else:
            logger.warning("Could not fetch %s, will rely on curated content", doc_id)

        # Be respectful with rate limiting
        time.sleep(1)

    return documents


def _extract_osha_body(text: str, doc_id: str) -> str:
    """Extract the regulatory body text from an OSHA page, stripping nav/boilerplate."""
    # Try to find the start of the actual regulation content
    markers = [
        "General requirements",
        "Purpose.",
        "Scope.",
        "Application.",
        "Definitions.",
        "(a)",
    ]
    best_start = 0
    for marker in markers:
        idx = text.find(marker)
        if idx > 0 and (best_start == 0 or idx < best_start):
            best_start = idx

    if best_start > 0:
        text = text[best_start:]

    # Truncate at footer markers
    footer_markers = [
        "Standards - Table of Contents",
        "UNITED STATES DEPARTMENT OF LABOR",
        "FEDERAL REGISTER",
    ]
    for marker in footer_markers:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]

    return text.strip()


# --------------------------------------------------------------------------
# India Code (Factories Act — freely available legislation)
# --------------------------------------------------------------------------

def fetch_factories_act() -> List[dict]:
    """
    Attempt to fetch the Factories Act 1948 from India Code.

    The India Code portal (indiacode.nic.in) serves legislative text but
    often behind JavaScript-rendered pages.  This is a best-effort attempt;
    the curated content in regulatory_docs/factories_act.py provides the
    guaranteed baseline.
    """
    doc_id = "Factories-Act-1948-Online"
    cached = _read_cache(doc_id)
    if cached:
        logger.info("Using cached content for Factories Act")
        return [{
            "doc_id": doc_id,
            "source_type": "factories_act",
            "title": "The Factories Act, 1948 (Act No. 63 of 1948) — Online Fetch",
            "text": cached,
        }]

    # India Code URLs for the Factories Act
    urls = [
        "https://www.indiacode.nic.in/bitstream/123456789/1560/1/A1948-63.pdf",
        "https://labour.gov.in/sites/default/files/TheFactoriesAct1948.pdf",
    ]

    for url in urls:
        logger.info("Attempting to fetch Factories Act from %s", url)
        # These are PDFs — we'd need PyPDF2/pdfplumber to extract text
        # For now, log and fall back to curated content
        logger.info("Factories Act is a PDF at %s — using curated content instead", url)

    logger.info("Factories Act: using curated content from regulatory_docs/factories_act.py")
    return []


# --------------------------------------------------------------------------
# OISD Standards (official portal — limited free access)
# --------------------------------------------------------------------------

def fetch_oisd_standards() -> List[dict]:
    """
    Attempt to fetch OISD standards.

    OISD standards are published by the Oil Industry Safety Directorate
    (oisd.gov.in). Most full-text standards are available as PDFs that
    require registration. The publicly available portions (standard titles,
    scopes, and some clause summaries) are limited.

    This function logs what's available and falls back to curated content.
    """
    doc_id = "OISD-Index"
    cached = _read_cache(doc_id)
    if cached:
        logger.info("Using cached OISD index")
        return [{
            "doc_id": doc_id,
            "source_type": "oisd_standard",
            "title": "OISD Standards Index — Online Fetch",
            "text": cached,
        }]

    logger.info("OISD standards portal: https://oisd.gov.in — standards require PDF download")
    logger.info("Using curated OISD content from regulatory_docs/oisd_standards.py")
    return []


# --------------------------------------------------------------------------
# DGMS Circulars (dgms.gov.in — some circulars are freely available)
# --------------------------------------------------------------------------

def fetch_dgms_circulars() -> List[dict]:
    """
    Attempt to fetch DGMS circulars from dgms.gov.in.

    DGMS circulars are published on the official DGMS website.  Some are
    available as HTML pages, others as PDFs.
    """
    doc_id = "DGMS-Circulars-Online"
    cached = _read_cache(doc_id)
    if cached:
        logger.info("Using cached DGMS content")
        return [{
            "doc_id": doc_id,
            "source_type": "dgms_circular",
            "title": "DGMS Circulars — Online Fetch",
            "text": cached,
        }]

    logger.info("DGMS circulars portal: https://dgms.gov.in — circulars available as PDFs")
    logger.info("Using curated DGMS content from regulatory_docs/dgms_circulars.py")
    return []


# --------------------------------------------------------------------------
# Master fetch function
# --------------------------------------------------------------------------

def fetch_all_documents() -> List[dict]:
    """
    Fetch all regulatory documents from legitimate sources.

    Returns a list of document dicts ready for ingestion via
    vector_store.ingest_corpus().

    Documents that cannot be fetched online are skipped — the curated
    content in regulatory_docs/ provides the guaranteed baseline.
    """
    all_docs = []

    logger.info("=" * 60)
    logger.info("FETCHING REGULATORY DOCUMENTS")
    logger.info("=" * 60)

    # 1. OSHA standards (most likely to succeed — public HTML pages)
    logger.info("\n--- OSHA Standards (osha.gov) ---")
    osha_docs = fetch_osha_standards()
    all_docs.extend(osha_docs)
    logger.info("Fetched %d OSHA documents", len(osha_docs))

    # 2. Factories Act
    logger.info("\n--- Factories Act 1948 (indiacode.nic.in) ---")
    fa_docs = fetch_factories_act()
    all_docs.extend(fa_docs)

    # 3. OISD Standards
    logger.info("\n--- OISD Standards (oisd.gov.in) ---")
    oisd_docs = fetch_oisd_standards()
    all_docs.extend(oisd_docs)

    # 4. DGMS Circulars
    logger.info("\n--- DGMS Circulars (dgms.gov.in) ---")
    dgms_docs = fetch_dgms_circulars()
    all_docs.extend(dgms_docs)

    logger.info("\n" + "=" * 60)
    logger.info("FETCH COMPLETE: %d documents from online sources", len(all_docs))
    logger.info("=" * 60)

    return all_docs


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    docs = fetch_all_documents()
    print(f"\nFetched {len(docs)} documents from online sources")
    for d in docs:
        print(f"  - {d['doc_id']}: {d['title']} ({len(d['text'])} chars)")
