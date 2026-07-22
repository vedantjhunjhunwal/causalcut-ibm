"""
Regression test for the token-budget overflow bug fixed in chunker.py's
packing loop (see the "Fix note" in chunker.py's module docstring).

Run from the project root (one level above regulatory_rag/):
    python -m regulatory_rag.tests.test_chunker_budget

The original version of chunk_document() could emit a chunk whose
token_count exceeds target_tokens whenever a large trailing overlap-seed
unit combined with a large next unit -- the combined buffer was only
size-checked at the *following* iteration, or never, if the offending unit
was the last one in the document. This test constructs both cases
directly (mid-document and trailing-chunk) and asserts the invariant
chunk_document() is supposed to guarantee: no returned chunk exceeds
target_tokens.
"""

import chunker
import config


def _para(n_words: int, prefix: str) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n_words))


def _assert_within_budget(chunks, target_tokens, label):
    for ch in chunks:
        assert ch.token_count <= target_tokens, (
            f"{label}: chunk {ch.chunk_index} has token_count={ch.token_count} "
            f"> target_tokens={target_tokens}"
        )


def test_mid_document_overflow_case():
    target, overlap = 50, 15
    text = "\n\n".join([_para(40, "a"), _para(45, "b"), _para(10, "c")])
    chunks = chunker.chunk_document(
        doc_id="TEST-1",
        source_type=next(iter(config.VALID_SOURCE_TYPES)),
        title="t",
        text=text,
        target_tokens=target,
        overlap_tokens=overlap,
    )
    _assert_within_budget(chunks, target, "mid-document overflow case")


def test_trailing_chunk_overflow_case():
    target, overlap = 50, 15
    text = "\n\n".join([_para(40, "d"), _para(45, "e")])
    chunks = chunker.chunk_document(
        doc_id="TEST-2",
        source_type=next(iter(config.VALID_SOURCE_TYPES)),
        title="t",
        text=text,
        target_tokens=target,
        overlap_tokens=overlap,
    )
    _assert_within_budget(chunks, target, "trailing-chunk overflow case")


def test_normal_packing_still_overlaps():
    target, overlap = 50, 15
    paras = [_para(15, f"p{i}_") for i in range(6)]
    text = "\n\n".join(paras)
    chunks = chunker.chunk_document(
        doc_id="TEST-3",
        source_type=next(iter(config.VALID_SOURCE_TYPES)),
        title="t",
        text=text,
        target_tokens=target,
        overlap_tokens=overlap,
    )
    _assert_within_budget(chunks, target, "normal packing case")
    assert len(chunks) > 1
    # sanity: consecutive chunks should share overlap content, not be disjoint
    assert chunks[0].text.split("\n\n")[-1] in chunks[1].text


def test_tail_merge_guard_skips_merge_when_it_would_overflow():
    target, overlap, min_chunk = 50, 15, 5
    text = "\n\n".join([_para(48, "f"), _para(3, "s")])
    chunks = chunker.chunk_document(
        doc_id="TEST-4",
        source_type=next(iter(config.VALID_SOURCE_TYPES)),
        title="t",
        text=text,
        target_tokens=target,
        overlap_tokens=overlap,
    )
    _assert_within_budget(chunks, target, "tail-merge guard case")
    # 48 + 3 = 51 > target(50) -> merge must be skipped, sliver stays its own chunk
    assert len(chunks) == 2
    assert chunks[-1].token_count == 3


if __name__ == "__main__":
    test_mid_document_overflow_case()
    test_trailing_chunk_overflow_case()
    test_normal_packing_still_overlaps()
    test_tail_merge_guard_skips_merge_when_it_would_overflow()
    print("All chunker budget tests passed.")
