---
id: CPYEXT-DOCRAG-001
status: confirmed
layer: feature
owner: human
priority: could-have
depends_on: [CPYEXT-RAG-001]
superseded_by:
---

# Doc-RAG — ingest reference documents for retrieval

Extends the existing past-run RAG index (CPYEXT-RAG-001) so it can also retrieve from ingested reference documents (README, requirements, code), not just past deliberation runs — chunked, embedded, and injected as a "RELEVANT DOCS" block distinct from "SIMILAR PAST DECISIONS". Reuses the same ChromaDB collection and retrieve machinery via a `kind` metadata field rather than standing up a second parallel index/retrieve/inject subsystem — two collections doing the same underlying job (semantic search + context injection) would diverge over time for no functional benefit.

## WHAT — Contract

- `consilium ingest <path>` (file or directory) shall chunk and index every file under `path` whose suffix is one of `.md`, `.txt`, `.py`, `.rst`, using `_chunk_text()` (default 1200-char windows, 200-char overlap) and upsert each chunk into the same `consilium_runs_v2` collection used by CPYEXT-RAG-001, tagged `metadata={"kind": "doc", "source": <relative path>, "chunk_index": <int>}`.
- Files exceeding 1 MB shall be skipped with a stderr message (not silently truncated or embedded in full).
- Files that fail UTF-8 decoding (binary content misdetected by extension) shall be skipped with a stderr message, not embedded as garbage.
- A resolved file path that falls outside the resolved ingestion root shall be skipped (guards against a symlink escaping the intended corpus directory). `consilium ingest` is a trusted-operator command — this guards against accidental misuse, not a malicious caller.
- `retrieve_docs(proposal, k=3, max_distance=0.55)` shall query the same collection restricted to `kind="doc"` and return formatted, source-cited snippets (`[source#chunk_index] "..."`) for hits within `max_distance`.
- `build_rag_context(proposal)` (CPYEXT-RAG-001) shall include a `RELEVANT DOCS:` block from `retrieve_docs()` alongside `SIMILAR PAST DECISIONS:`, each present only if non-empty.
- No document corpus ships pre-committed to the repo (no pinned/versioned corpus) — nothing is ingested until a user runs `consilium ingest`. A natural first corpus is the repo's own docs (`README.md`, `CLAUDE.md`, `requirements/*.md`), used as the fixture for `eval_rag.py` (see CPYSCRIPT-EVALRAG-001) but not committed as pre-built embeddings.

## WHAT — Verify intent

None — doc is unambiguous.

## WHAT — Notes & known limitations

- Corpus pinning/versioning (fixing the embedding model + committing a corpus for fully reproducible retrieval) is deliberately out of scope for this first version — there's no corpus to pin yet, and pinning nothing is premature. Revisit once real ingest usage exists.
- Cross-encoder reranking and a pluggable embedding backend (`CONSILIUM_EMBED` env var) are deliberately out of scope — both are optimizations for a corpus/scale that doesn't exist yet (see TODO.md for the deferred rationale).

## HOW — Acceptance

- Given a markdown file, when `consilium ingest <path>` is run, then `retrieve_docs()` on a query matching its content returns a snippet citing that file as `source`.
- Given a file larger than 1 MB, when ingested, then it is skipped and a message is printed to stderr; no chunk is indexed for it.
- Given a binary file with a `.md` extension, when ingested, then it is skipped (UTF-8 decode failure) and a message is printed to stderr.
- Given a directory with mixed ingestable and non-ingestable files, when ingested, then only files matching the supported suffixes are chunked and indexed.
- Given a `kind="run"` entry and a `kind="doc"` entry both similar to a query, when `build_rag_context()` is called, then both a `SIMILAR PAST DECISIONS:` and a `RELEVANT DOCS:` block appear, each containing only its own kind.

## WHERE — Current implementation

- `src/consilium/rag.py` (`ingest_path`, `_chunk_text`, `retrieve_docs`)
- `src/consilium/cli.py` (`consilium ingest` command)
