"""Small RAG evaluation harness — recall@k / MRR against the repo's own docs.

Not part of the installed package; run manually:
    python scripts/eval_rag.py

Ingests README.md, CLAUDE.md, and requirements/*.md into an ephemeral ChromaDB
collection (never touches ~/.consilium/chroma/) and checks whether each
hand-authored query retrieves its expected source file in the top-k.

This is a small starter/demo eval set (n≈18 real query -> known-source pairs,
hand-verified against the actual doc content), not a statistically powered
benchmark. Results are reported as a fraction and a per-query table, not a
bare aggregate percentage, so `n` stays visible wherever the number is quoted.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

TOP_K = 3

# query -> expected source file (relative to repo root). Each pair was
# hand-verified against the real file content — not fabricated ground truth.
EVAL_SET: list[tuple[str, str]] = [
    ("What does the Generator voice do in the deliberation pipeline?", "README.md"),
    ("What verdicts can the aggregator produce?", "README.md"),
    ("How do I install the RAG extra?", "README.md"),
    ("What CLI command reviews the current git diff?", "README.md"),
    ("How do I run consilium without an API key?", "README.md"),
    ("What does the trias deliberation mode do?", "README.md"),
    ("How do I run a single test file?", "CLAUDE.md"),
    ("What comment marks a source file as implementing a requirement?", "CLAUDE.md"),
    ("Which voice runs first in the sequential pipeline and why?", "CLAUDE.md"),
    ("What triggers a BLOCK verdict with reason voice_unparseable?", "CLAUDE.md"),
    ("What flag lets the Skeptic downgrade the verdict in dialectic mode?", "CLAUDE.md"),
    ("Does a categorical BLOCK from one trias personality get out-voted?", "CLAUDE.md"),
    ("What ChromaDB distance space does the RAG index use and why is it explicit?",
     "requirements/CPYEXT-RAG-001.md"),
    ("What confidence and verdict filter does retrieve() apply to past runs?",
     "requirements/CPYEXT-RAG-001.md"),
    ("What happens when consilium ingest finds a file over 1MB?",
     "requirements/CPYEXT-DOCRAG-001.md"),
    ("What metadata field distinguishes an ingested doc chunk from a past run?",
     "requirements/CPYEXT-DOCRAG-001.md"),
    ("When is a Skeptic objection discarded even though can_object is true?",
     "requirements/CPYBUS-SKEPTIC-001.md"),
    ("What does the POST /deliberate endpoint accept in its JSON body?",
     "requirements/CPYSRV-HTTP-001.md"),
    ("What happens when explain_module finds no Python files?",
     "requirements/CPYBUS-EXPLAIN-001.md"),
]


def main() -> int:
    try:
        import chromadb
    except ImportError:
        print(
            "eval_rag requires chromadb. Install with: pip install 'consilium-py[rag]'",
            file=sys.stderr,
        )
        return 1

    from consilium.rag import _chunk_text  # noqa: PLC0415

    tmp = tempfile.mkdtemp()
    try:
        client = chromadb.PersistentClient(path=tmp)
        col = client.get_or_create_collection(name="eval", metadata={"hnsw:space": "cosine"})

        corpus_files = [
            _ROOT / "README.md",
            _ROOT / "CLAUDE.md",
            *sorted((_ROOT / "requirements").glob("*.md")),
        ]
        for f in corpus_files:
            if not f.exists():
                continue
            text = f.read_text(encoding="utf-8")
            source = str(f.relative_to(_ROOT)).replace("\\", "/")
            chunks = _chunk_text(text)
            if not chunks:
                continue
            ids = [f"{source}:{i}" for i in range(len(chunks))]
            metadatas = [{"source": source} for _ in chunks]
            col.upsert(ids=ids, documents=chunks, metadatas=metadatas)

        results = []
        for query, expected_source in EVAL_SET:
            res = col.query(query_texts=[query], n_results=TOP_K)
            sources = [m["source"] for m in res["metadatas"][0]]
            hit = expected_source in sources
            rank = sources.index(expected_source) + 1 if hit else None
            results.append((query, expected_source, hit, rank))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n = len(results)
    passed = sum(1 for _q, _s, hit, _r in results if hit)
    mrr = sum(1 / rank for _q, _s, hit, rank in results if hit) / n

    print(f"recall@{TOP_K}: {passed}/{n} passed\n")
    for query, expected_source, hit, rank in results:
        mark = "PASS" if hit else "FAIL"
        rank_str = f"rank {rank}" if hit else "not retrieved"
        print(f"  [{mark}] {query!r} -> expected {expected_source} ({rank_str})")
    print(f"\nMRR: {mrr:.3f}  (n={n})")

    # This is a measurement, not a gate — imperfect recall is data to act on
    # (retune chunk size, k, or the query set), not a script failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
