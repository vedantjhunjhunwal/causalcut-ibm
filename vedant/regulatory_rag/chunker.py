"""
Chunking for the regulatory corpus (OISD standards, Factories Act 1948,
DGMS circulars -- Section 7.5 of the design doc).

Two things regulatory/legal text needs that generic RAG chunkers usually
don't bother with:

1. Clause/section provenance. The optimiser's output schema cites evidence
   like "OISD-STD-116 Clause 4.3" and "Factories Act 1948 Section 41"
   (Section 5.6 / 8's worked example). If chunking throws away where in the
   document a passage came from, you can't reconstruct that citation later.
   So every paragraph is scanned for a leading clause/section marker, and
   that marker is carried forward onto any continuation paragraphs that
   belong to the same clause.

2. A hard ceiling under the embedding model's token limit. See config.py --
   packing chunks past the model's real ceiling means silent truncation
   (worse: silent quality loss even before hard truncation -- see
   config.py's EMBED_MODEL_EFFECTIVE_TOKEN_LIMIT). Token estimation here is
   a fast, dependency-free regex approximation (no tokenizer download
   needed at chunk time); the target is kept comfortably below the real
   model ceiling to absorb the estimate's error margin.

Fix note (this revision): the packing loop below now re-validates the
budget immediately after reseeding a chunk with overlap from its
predecessor, before blindly appending the unit that triggered the flush.
The previous version checked the budget only *before* reseeding, so a large
trailing overlap unit combined with a large next unit could silently
produce a chunk over target_tokens -- exactly the failure mode this module
exists to prevent. See the inline comment at the fix site for the mechanism
and test_fix.py-style repro for a worked example of the failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import config

# --------------------------------------------------------------------------
# Token estimation
# --------------------------------------------------------------------------
# Words and punctuation counted separately, which tracks WordPiece/BPE
# token counts on typical English prose to within ~10-15% -- close enough
# given the headroom built into CHUNK_TARGET_TOKENS.
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]")


def estimate_tokens(text: str) -> int:
    return len(_TOKEN_PATTERN.findall(text))


# --------------------------------------------------------------------------
# Clause / section detection
# --------------------------------------------------------------------------
# Covers the numbering styles that show up across OISD standards ("Clause
# 4.3"), the Factories Act ("Section 41", "Section 41(2)"), and DGMS
# circulars (plain decimal numbering, "Para 3.2"). Order matters -- first
# match wins, so more specific patterns are listed first.
#
# Known limitation (unchanged from the original): matching is anchored to
# the *start* of a paragraph, so an inline reference like "...in accordance
# with Clause 4.3 above..." mid-sentence will not update current_ref. This
# is fine for source text where clause numbers head their own paragraph
# (the normal OISD/DGMS layout) but will under-tag prose-style documents
# that only reference clauses inline.
_CLAUSE_PATTERNS = [
    re.compile(r"^(Clause\s+\d+(?:\.\d+)*)", re.IGNORECASE),
    re.compile(r"^(Section\s+\d+[A-Za-z]?(?:\(\d+\))?)", re.IGNORECASE),
    re.compile(r"^(Regulation\s+\d+(?:\.\d+)*)", re.IGNORECASE),
    re.compile(r"^(Para(?:graph)?\s+\d+(?:\.\d+)*)", re.IGNORECASE),
    re.compile(r"^(Circular\s+No\.?\s*[\w./-]+)", re.IGNORECASE),
    re.compile(r"^(\d+(?:\.\d+){1,3})\b"),  # bare decimal numbering, e.g. "4.3.1"
]


def extract_clause_ref(paragraph: str) -> Optional[str]:
    stripped = paragraph.strip()
    for pattern in _CLAUSE_PATTERNS:
        m = pattern.match(stripped)
        if m:
            return m.group(1).strip()
    return None


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class Chunk:
    doc_id: str
    source_type: str
    title: str
    text: str
    chunk_index: int
    clause_ref: str = ""
    token_count: int = field(default=0)

    def __post_init__(self):
        if not self.token_count:
            self.token_count = estimate_tokens(self.text)

    @property
    def chunk_id(self) -> str:
        # Deterministic -- re-running ingestion on an unchanged corpus
        # produces the same IDs, so vector_store.py can upsert idempotently
        # instead of accumulating duplicates. NOTE: this is only stable
        # under an *unchanged* corpus -- if the source text changes such
        # that paragraph/unit counts shift, chunk_index shifts with them
        # and old IDs become orphaned. vector_store.ingest_document handles
        # this by deleting all chunks for a doc_id before inserting the new
        # set, rather than relying on upsert-by-id alone.
        safe_doc_id = re.sub(r"\s+", "-", self.doc_id.strip())
        return f"{safe_doc_id}::chunk-{self.chunk_index:04d}"

    @property
    def citation(self) -> str:
        return f"{self.doc_id} {self.clause_ref}".strip() if self.clause_ref else self.doc_id

    def to_metadata(self) -> dict:
        # Chroma metadata values must be flat str/int/float/bool -- no None,
        # no nested structures.
        return {
            "doc_id": self.doc_id,
            "source_type": self.source_type,
            "title": self.title,
            "clause_ref": self.clause_ref,
            "citation": self.citation,
            "chunk_index": self.chunk_index,
            "token_count": self.token_count,
            "char_count": len(self.text),
        }


# --------------------------------------------------------------------------
# Paragraph splitting
# --------------------------------------------------------------------------
def _split_paragraphs(text: str) -> List[str]:
    normalized = text.replace("\r\n", "\n")
    raw_paragraphs = re.split(r"\n\s*\n", normalized)
    return [p.strip() for p in raw_paragraphs if p.strip()]


def _split_sentences(paragraph: str) -> List[str]:
    # Lightweight sentence split -- good enough for the fallback case
    # (a single paragraph that alone exceeds the token budget).
    sentences = re.split(r"(?<=[.;:])\s+(?=[A-Z(])", paragraph)
    return [s.strip() for s in sentences if s.strip()]


_HARD_SPLIT_PIECE_TOKENS = 40  # deliberately small -- see docstring below


def _hard_split_by_tokens(text: str, max_tokens: int) -> List[str]:
    # Last-resort fallback for a single sentence that alone exceeds the
    # token budget (e.g. a long run-on clause with no internal punctuation).
    # Pieces are kept small (~_HARD_SPLIT_PIECE_TOKENS), deliberately well
    # under max_tokens, rather than sized up to max_tokens itself: the
    # packer below combines several small units per chunk and re-derives
    # overlap between them, but a handful of already-near-budget atomic
    # blocks can't be safely recombined -- one such block alone, force-
    # included as the next chunk's overlap seed, can push that chunk over
    # budget before the packer's own overflow check fires again.
    words = text.split()
    if not words:
        return [text]
    piece_target = max(1, min(_HARD_SPLIT_PIECE_TOKENS, max_tokens))
    pieces, current = [], []
    for word in words:
        current.append(word)
        if estimate_tokens(" ".join(current)) >= piece_target:
            pieces.append(" ".join(current))
            current = []
    if current:
        pieces.append(" ".join(current))
    return pieces or [text]


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def chunk_document(
    doc_id: str,
    source_type: str,
    title: str,
    text: str,
    target_tokens: int = config.CHUNK_TARGET_TOKENS,
    overlap_tokens: int = config.CHUNK_OVERLAP_TOKENS,
) -> List[Chunk]:
    """
    Chunk one regulatory document into overlapping, clause-tagged passages.

    Packing is paragraph-greedy: paragraphs are added to the running chunk
    until the next one would break the token budget, at which point the
    chunk is emitted and a new one starts, seeded with the trailing
    paragraph(s) of the previous chunk (by token budget) so a clause split
    across a chunk boundary still has surrounding context on both sides.

    Invariant this function guarantees: no returned chunk's token_count
    exceeds target_tokens. (The pre-processing pass below already caps
    every individual unit at target_tokens; the packing loop's job is to
    combine units into chunks without breaking that ceiling itself.)
    """
    if source_type not in config.VALID_SOURCE_TYPES:
        raise ValueError(
            f"Unknown source_type {source_type!r}; expected one of {sorted(config.VALID_SOURCE_TYPES)}"
        )

    paragraphs = _split_paragraphs(text)

    # Expand any paragraph that alone busts the budget into smaller pieces
    # (sentence-level, then hard token-level as a last resort) *before*
    # packing, so the packer only ever deals with sub-budget units.
    units: List[str] = []
    for para in paragraphs:
        if estimate_tokens(para) <= target_tokens:
            units.append(para)
            continue
        for sentence in _split_sentences(para):
            if estimate_tokens(sentence) <= target_tokens:
                units.append(sentence)
            else:
                units.extend(_hard_split_by_tokens(sentence, target_tokens))

    if not units:
        return []

    # Carry the most recently seen clause marker forward onto continuation
    # units that don't start a new clause themselves.
    unit_refs: List[Optional[str]] = []
    current_ref: Optional[str] = None
    for u in units:
        detected = extract_clause_ref(u)
        if detected:
            current_ref = detected
        unit_refs.append(current_ref)

    # Pair each unit with its clause ref so the two travel together through
    # buffering/reseeding -- indexing two parallel lists by position breaks
    # as soon as the buffer gets reseeded with a subset of the previous one.
    paired_units = list(zip(units, unit_refs))

    chunks: List[Chunk] = []
    buffer: List[tuple] = []  # list of (unit_text, ref_or_None)
    buffer_tokens = 0
    chunk_index = 0

    def flush():
        nonlocal buffer, buffer_tokens, chunk_index
        if not buffer:
            return
        chunk_text = "\n\n".join(u for u, _ in buffer)
        # Cite the clause active at the *start* of the chunk -- that's the
        # clause a reader lands on first, and the common case (one clause
        # comfortably fits in one chunk) makes this exact.
        ref_for_chunk = next((r for _, r in buffer if r), "") or ""
        chunks.append(
            Chunk(
                doc_id=doc_id,
                source_type=source_type,
                title=title,
                text=chunk_text,
                chunk_index=chunk_index,
                clause_ref=ref_for_chunk,
            )
        )
        chunk_index += 1

    for unit, ref in paired_units:
        unit_tokens = estimate_tokens(unit)

        if buffer and buffer_tokens + unit_tokens > target_tokens:
            flush()
            # Seed the next chunk with trailing units from the one just
            # closed, up to overlap_tokens, so context carries across the
            # seam.
            overlap, overlap_count = [], 0
            for prev_unit, prev_ref in reversed(buffer):
                t = estimate_tokens(prev_unit)
                if overlap_count + t > overlap_tokens and overlap:
                    break
                overlap.insert(0, (prev_unit, prev_ref))
                overlap_count += t
            buffer = overlap
            buffer_tokens = overlap_count

            # FIX: the "at least one unit" rule above can let a single
            # trailing unit into the overlap seed even though it alone
            # exceeds overlap_tokens (every unit is only guaranteed to be
            # <= target_tokens, not <= overlap_tokens). Without this check,
            # the code below would append `unit` on top of that seed
            # unconditionally, and the combined buffer would only be
            # size-checked at the *next* iteration -- or never, if `unit`
            # is the last one in the document, since the final flush()
            # after the loop is unconditional.
            #
            # Re-check right here: if the reseeded buffer already can't fit
            # `unit`, DROP the overlap seed rather than flushing it as its
            # own chunk -- that seed's text is, by construction, the tail
            # of the chunk just flushed above, so emitting it again would
            # ship a near-duplicate chunk into the corpus (confirmed by an
            # earlier version of this fix that did exactly that). Losing
            # overlap continuity at this one seam is a minor quality
            # trade-off; a duplicate chunk is a correctness regression.
            if buffer and buffer_tokens + unit_tokens > target_tokens:
                buffer, buffer_tokens = [], 0

        buffer.append((unit, ref))
        buffer_tokens += unit_tokens

    flush()

    # Merge a trailing sliver into its predecessor rather than shipping a
    # near-empty final chunk -- but only if the merge itself stays within
    # budget. A merge that overshoots target_tokens defeats the whole
    # point of this module; a small trailing chunk is a minor quality nit
    # by comparison, so when the two conflict, staying under budget wins.
    if len(chunks) >= 2 and chunks[-1].token_count < config.MIN_CHUNK_TOKENS:
        tail = chunks[-1]
        prev = chunks[-2]
        if prev.token_count + tail.token_count <= target_tokens:
            chunks.pop()
            merged_text = prev.text + "\n\n" + tail.text
            chunks[-1] = Chunk(
                doc_id=prev.doc_id,
                source_type=prev.source_type,
                title=prev.title,
                text=merged_text,
                chunk_index=prev.chunk_index,
                clause_ref=prev.clause_ref,
            )

    return chunks
