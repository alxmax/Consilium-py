---
id: CPYEXT-RAG-001
status: confirmed
layer: feature
owner: human
depends_on: [CPYBUS-API-001, CPYBUS-VOI-001]
---

# RAG context injection from past deliberation runs

Optional `[rag]` extra that indexes past deliberation runs into a ChromaDB vector store and injects semantically similar past verdicts as context before voices run. Demonstrates RAG retrieval-augmented generation patterns.

## WHAT — Contract

- `save_run(run_id, inp, report)` shall persist `{id, timestamp, proposal, context, report}` to `~/.consilium/runs/<run_id>.json`. The proposal text must be inside the record (not only in the filename).
- `index(run_id, inp, report)` shall upsert the run into a ChromaDB collection `consilium_runs_v2` at `~/.consilium/chroma/`, using `metadata={"kind": "run", ...}` and `proposal + context` (not proposal alone) as the embedded document.
- The collection shall be created with `metadata={"hnsw:space": "cosine"}` — explicit, not ChromaDB's unstated default (L2/squared-L2).
- `retrieve(proposal, k=3, max_distance=0.55)` shall return at most `k` formatted snippets whose cosine distance to the query is ≤ `max_distance`, restricted to `kind="run"` entries with `confidence >= 0.5` and `verdict not in (STOP, BLOCK)` — a design default (failed/low-confidence runs are not "similar past guidance"), not an empirically-validated quality claim. If the index is empty, print a user-visible message to stderr and return `[]`. If no run qualifies (all distances > threshold, or all excluded by the quality filter), return `[]`.
- `0.55` is calibrated, not arbitrary — see `tests/test_rag.py::TestMaxDistanceCalibration`, which asserts known-similar proposal pairs land ≤ 0.55 and known-dissimilar pairs land > 0.55 against the real embedding function.
- `build_rag_context(proposal)` shall call `retrieve()` and `retrieve_docs()` (see CPYEXT-DOCRAG-001) and return `SIMILAR PAST DECISIONS:` / `RELEVANT DOCS:` blocks (each only if non-empty), joined by a blank line, or `""` if both are empty.
- When `chromadb` is not installed, any call into the RAG module shall raise `ImportError` with a `pip install consilium-py[rag]` hint — not silently skip.
- The RAG context block, when non-empty, shall be prepended to `inp.context` before voices run, ahead of any user-supplied `--context` content.
- The ChromaDB store is global (`~/.consilium/chroma/`). A per-project store (`.consilium/chroma/` in the repo) would be more isolated but requires project-root detection; global is simpler and sufficient for the current scope.
- Migration note: `consilium_runs` (the pre-cosine, default-distance collection) is superseded by `consilium_runs_v2`, not migrated automatically — mixing L2 and cosine vectors in one index would make distances meaningless. If the new collection is empty and the old one has data, `retrieve()`/`retrieve_docs()` print an upgrade-specific stderr hint (distinct from the generic empty-index message) pointing at `consilium index` to rebuild.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given a seeded index with one run (verdict GO, proposal "Add health check"), when `retrieve("Add health endpoint")` is called, then the returned snippet contains "GO" and the proposal text.
- Given `max_distance=0.55` and a query with no similar run, when `retrieve()` is called, then it returns `[]` without raising.
- Given a run with `verdict="STOP"` or `confidence<0.5`, when `retrieve()` is called with a query that would otherwise match it, then it is excluded from the results.
- Given `chromadb` not installed, when `index()` or `retrieve()` is called, then `ImportError` is raised with the install hint.
- Given an empty index, when `retrieve()` is called, then a message is printed to stderr and `[]` is returned.
- Given the legacy `consilium_runs` collection has data and `consilium_runs_v2` is empty, when `retrieve()`/`retrieve_docs()` is called, then an upgrade-specific stderr hint naming both collections is printed.

## WHERE — Current implementation

- `src/consilium/rag.py`
- `src/consilium/__init__.py` (rag param + persistence wiring)
- `src/consilium/cli.py` (--rag flag / CONSILIUM_RAG env var, `consilium index` command)
