---
id: CPYEXT-RAG-001
status: baseline
layer: feature
owner: human
depends_on: [CPYBUS-API-001, CPYBUS-VOI-001]
---

# RAG context injection from past deliberation runs

Optional `[rag]` extra that indexes past deliberation runs into a ChromaDB vector store and injects semantically similar past verdicts as context before voices run. Demonstrates RAG retrieval-augmented generation patterns.

## WHAT — Contract

- `save_run(run_id, inp, report)` shall persist `{id, timestamp, proposal, context, report}` to `~/.consilium/runs/<run_id>.json`. The proposal text must be inside the record (not only in the filename).
- `index(run_id, inp, report)` shall upsert the run into a ChromaDB collection at `~/.consilium/chroma/`, using the proposal text as the embedded document.
- `retrieve(proposal, k=3, max_distance=0.35)` shall return at most `k` formatted snippets whose cosine distance to the query is ≤ `max_distance`. If the index is empty, print a user-visible message to stderr and return `[]`. If no run qualifies (all distances > threshold), return `[]`.
- `build_rag_context(proposal)` shall call `retrieve()` and return a `SIMILAR PAST DECISIONS:` block, or `""` if empty.
- When `chromadb` is not installed, any call into the RAG module shall raise `ImportError` with a `pip install consilium-py[rag]` hint — not silently skip.
- The RAG context block, when non-empty, shall be prepended to `inp.context` before voices run. Its ordering relative to user-supplied `--context` must be documented.

## WHAT — Verify intent

- Should the index be scoped per-project (e.g. `.consilium/chroma/` in the repo) or global (`~/.consilium/chroma/`)? Current design chooses global; a per-project store would be more isolated.

## HOW — Acceptance

- Given a seeded index with one run (verdict GO, proposal "Add health check"), when `retrieve("Add health endpoint")` is called, then the returned snippet contains "GO" and the proposal text.
- Given `max_distance=0.35` and a query with no similar run, when `retrieve()` is called, then it returns `[]` without raising.
- Given `chromadb` not installed, when `index()` or `retrieve()` is called, then `ImportError` is raised with the install hint.
- Given an empty index, when `retrieve()` is called, then a message is printed to stderr and `[]` is returned.

## WHERE — Current implementation

- `src/consilium/rag.py`
- `src/consilium/__init__.py` (rag param + persistence wiring)
- `src/consilium/cli.py` (--rag flag, `consilium index` command)
