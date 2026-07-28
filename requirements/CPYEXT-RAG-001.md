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
- `build_rag_bundle(proposal)` shall return `(context_block, doc_source_ids)` from a **single** retrieval pass, where each id is `"<source>#<chunk_index>"`. `build_rag_context(proposal)` shall return only its first element, preserving its existing signature. Past-run snippets shall NOT be cited: they are prior deliberations, not source documents.
- The storage root shall be resolvable at call time via `runs_dir()` / `chroma_dir()`, which return `$CONSILIUM_HOME/runs` and `$CONSILIUM_HOME/chroma` when `CONSILIUM_HOME` is set and `~/.consilium/...` otherwise. Resolution must be per call, not at import: under a server the process home is the service account's, often ephemeral (containers) or shared, so the location has to be settable from outside the package.
- **Tenancy — two modes.** `index()`, `ingest_path()`, `retrieve()`, `_doc_hits()`, `build_rag_bundle()` and `build_rag_context()` shall accept `tenant: str | None = None`. With `None` no tenant key is written and no tenant clause is applied (the shared single-operator corpus, and the original behaviour). With a tenant string, writes carry `metadata['tenant']` and reads add a `{'tenant': <id>}` clause, so a scoped query returns neither another tenant's records nor untagged ones — fail closed, so pre-tenancy data is never served to a tenant. `ingest_path` shall also scope its stale-chunk `delete` to the tenant, or re-ingesting a same-named file would purge another tenant's chunks.
- The tenant shall be resolved server-side from the authenticated caller (`CONSILIUM_API_KEYS`), never from a request field — otherwise a caller selects their own scope.
- **Document extractors.** `extract_text(path)` shall return the ingestable text for a supported suffix, `None` for an unsupported one, and raise `ImportError` with a `pip install 'consilium-py[docs]'` hint when the format is supported but its optional dependency is absent — a missing extractor must be loud, never a silently empty document. The registry `_EXTRACTORS` maps suffix → callable: `.pdf` (PyMuPDF), `.docx` (python-docx), `.html`/`.htm` (beautifulsoup4, `<script>`/`<style>` stripped), `.csv` (stdlib). Plain-text suffixes bypass the registry.
- **CSV is summarised, not embedded.** `_extract_csv` shall emit the filename, column list, row count, and at most `_CSV_PREVIEW_ROWS` rows labelled as shape-only, and shall NOT index the remaining rows. Rationale: top-k cosine retrieval over table rows returns arbitrary rows from which a model computes confident wrong aggregates; a figure must come from a deterministic query, not from retrieval. `.sql` is out of scope for the same reason (a schema script is not data).
- Images shall not be ingested: OCR requires an external `tesseract` binary and a silently empty extraction is worse than an explicit skip.
- `_MAX_INGEST_FILE_BYTES` shall be 10 MB, not 1 MB — a single PDF routinely exceeds the old cap.
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
- Given a doc chunk from `README.md` at chunk index 2, when `build_rag_bundle()` is called, then the text contains `RELEVANT DOCS` and the ids are `["README.md#2"]`; given an empty index, both halves are empty (tested-by `tests/test_rag.py::TestBuildRagBundle`).
- Given `CONSILIUM_HOME` set to a temp dir, when `runs_dir()` / `chroma_dir()` are called, then they resolve beneath it, and `save_run()` writes there rather than under the user's home; unset, they resolve under `~/.consilium` (tested-by `tests/test_rag.py::TestStorageRootOverride`).
- Given `tenant='acme'`, when `index()` / `ingest_path()` are called, then the written metadata carries `tenant='acme'`; with `tenant=None` no such key is written; and `retrieve()` / `retrieve_docs()` add a `{'tenant': ...}` clause only when scoped (tested-by `tests/test_rag.py::TestTenantScoping`).
- Given an `.html`, `.docx`, `.pdf` or `.csv` file, when `extract_text()` is called, then it returns extracted text (HTML free of `<script>`/`<style>`, CSV a schema summary whose tail rows are absent); an unsupported suffix returns `None`; and a supported suffix with its dependency missing raises `ImportError` naming `consilium-py[docs]` (tested-by `tests/test_rag.py::TestDocumentExtractors`).
- Given an HTML file, when `ingest_path()` runs, then the stored chunk contains the extracted text and NOT the raw markup — the discriminating assertion, since raw `read_text` would also contain the body substring (tested-by `tests/test_rag.py::TestDocumentExtractors::test_ingest_routes_html_through_the_extractor`).

## WHERE — Current implementation

- `src/consilium/rag.py`
- `src/consilium/__init__.py` (rag param + persistence wiring)
- `src/consilium/cli.py` (--rag flag / CONSILIUM_RAG env var, `consilium index` command)
