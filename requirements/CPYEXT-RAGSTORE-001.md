---
id: CPYEXT-RAGSTORE-001
status: confirmed
layer: feature
owner: human
depends_on: [CPYEXT-RAG-001]
---

# RAG storage root, run persistence and tenancy

Where the `[rag]` extra (CPYEXT-RAG-001) keeps its data and whose data a call may see: the raw run records `save_run` writes, the storage root `CONSILIUM_HOME` relocates, and the per-call tenant scope applied to every index write and retrieval read.

## WHAT — Contract

- `save_run(run_id, inp, report)` shall persist `{id, timestamp, proposal, context, report}` to `~/.consilium/runs/<run_id>.json`. The proposal text must be inside the record (not only in the filename).
- The ChromaDB store is global (`~/.consilium/chroma/`). A per-project store (`.consilium/chroma/` in the repo) would be more isolated but requires project-root detection; global is simpler and sufficient for the current scope.
- The storage root shall be resolvable at call time via `runs_dir()` / `chroma_dir()`, which return `$CONSILIUM_HOME/runs` and `$CONSILIUM_HOME/chroma` when `CONSILIUM_HOME` is set and `~/.consilium/...` otherwise. Resolution must be per call, not at import: under a server the process home is the service account's, often ephemeral (containers) or shared, so the location has to be settable from outside the package.
- **Tenancy — two modes.** `index()`, `ingest_path()`, `retrieve()`, `_doc_hits()`, `build_rag_bundle()` and `build_rag_context()` shall accept `tenant: str | None = None`. With `None` no tenant key is written and no tenant clause is applied (the shared single-operator corpus, and the original behaviour). With a tenant string, writes carry `metadata['tenant']` and reads add a `{'tenant': <id>}` clause, so a scoped query returns neither another tenant's records nor untagged ones — fail closed, so pre-tenancy data is never served to a tenant. `ingest_path` shall also scope its stale-chunk `delete` to the tenant, or re-ingesting a same-named file would purge another tenant's chunks.
- The tenant shall be resolved server-side from the authenticated caller (`CONSILIUM_API_KEYS`), never from a request field — otherwise a caller selects their own scope.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `CONSILIUM_HOME` set to a temp dir, when `runs_dir()` / `chroma_dir()` are called, then they resolve beneath it, and `save_run()` writes there rather than under the user's home; unset, they resolve under `~/.consilium` (tested-by `tests/test_rag.py::TestStorageRootOverride`).
- Given `tenant='acme'`, when `index()` / `ingest_path()` are called, then the written metadata carries `tenant='acme'`; with `tenant=None` no such key is written; and `retrieve()` / `retrieve_docs()` add a `{'tenant': ...}` clause only when scoped (tested-by `tests/test_rag.py::TestTenantScoping`).

## WHERE — Current implementation

- `src/consilium/rag.py` (`runs_dir`, `chroma_dir`, `save_run`, `_tenant_clause`, `tenant` parameters)
