"""RAG context injection from past deliberation runs and ingested reference documents.

TENANCY — two modes, chosen per call via the `tenant` argument:

- `tenant=None` (default): one shared corpus, no scope key written or filtered.
  This is the single-operator mode and the original behaviour.
- `tenant="<id>"`: reads AND writes are scoped to that id. A scoped query cannot
  see another tenant's records, and — deliberately — cannot see *untagged* ones
  either. That fail-closed choice means records written before tenancy existed
  are invisible in scoped mode rather than leaking to the first tenant who asks.

The tenant id must be resolved server-side from the authenticated caller, never
read from a request body — otherwise the caller picks their own scope.

Switching an existing shared corpus to scoped mode is not retroactive: already
written records carry no tenant key, so they need re-ingesting under a tenant
(`consilium ingest <path> --tenant <id>`) to become visible again.
"""
# implements: CPYEXT-RAG-001
# implements: CPYEXT-DOCRAG-001
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from consilium.models import DeliberationInput, Report

_RUNS_DIR = Path.home() / ".consilium" / "runs"
_CHROMA_DIR = Path.home() / ".consilium" / "chroma"


def runs_dir() -> Path:
    """Directory for raw run JSON. `CONSILIUM_HOME` overrides the default.

    Resolved per call, not at import: a server process runs as a service account
    whose home directory is often ephemeral (containers) or shared, so the
    location has to be settable from outside the package.
    """
    override = os.environ.get("CONSILIUM_HOME")
    return Path(override) / "runs" if override else _RUNS_DIR


def chroma_dir() -> Path:
    """Directory for the ChromaDB index. See `runs_dir` for the override rule."""
    override = os.environ.get("CONSILIUM_HOME")
    return Path(override) / "chroma" if override else _CHROMA_DIR


_COLLECTION = "consilium_runs_v2"
_LEGACY_COLLECTION = "consilium_runs"  # pre-cosine, L2-distance index — see _legacy_index_hint

# Calibrated against tests/test_rag.py::test_max_distance_separates_known_pairs —
# cosine distance for genuinely-similar proposal pairs clustered at 0.14-0.41,
# unrelated pairs at 0.85-0.85 (all-MiniLM-L6-v2). 0.55 sits in the gap.
_MAX_DISTANCE = 0.55
_MIN_CONFIDENCE = 0.5
_EXCLUDED_VERDICTS = ("STOP", "BLOCK")
_TOP_K = 3

# consilium ingest: guards against embedding huge/binary/out-of-scope files.
# 10 MB, not 1 MB: a single PDF routinely exceeds the old cap, and the real
# blast-radius guard is the extracted-text length, not the container size.
_MAX_INGEST_FILE_BYTES = 10_000_000  # 10 MB
_CHUNK_SIZE = 1200  # characters
_CHUNK_OVERLAP = 200  # characters
_PLAIN_TEXT_SUFFIXES = {".md", ".txt", ".py", ".rst"}

# CSV preview: enough rows to show the shape, few enough that no aggregate can
# be read off them. See _extract_csv for why rows are deliberately not embedded.
_CSV_PREVIEW_ROWS = 5


def _extract_html(path: Path) -> str:
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "Ingesting HTML requires beautifulsoup4. "
            "Install with: pip install 'consilium-py[docs]'"
        )
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _extract_docx(path: Path) -> str:
    try:
        import docx  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "Ingesting .docx requires python-docx. "
            "Install with: pip install 'consilium-py[docs]'"
        )
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def _extract_pdf(path: Path) -> str:
    try:
        import fitz  # noqa: PLC0415  (PyMuPDF)
    except ImportError:
        raise ImportError(
            "Ingesting PDF requires PyMuPDF. "
            "Install with: pip install 'consilium-py[docs]'"
        )
    with fitz.open(str(path)) as doc:
        # get_text() is overloaded on its `option` arg; the default returns str.
        return "\n".join(str(page.get_text()) for page in doc)


def _extract_csv(path: Path) -> str:
    """Describe a CSV's *structure*; deliberately do not embed its rows.

    Semantic retrieval over table rows is the wrong tool for tabular data: a
    top-k cosine match returns a handful of arbitrary rows, from which a model
    will happily compute a confident and wrong aggregate. Embedding the schema
    instead lets retrieval answer "which dataset holds this?" while forcing any
    actual figure to come from a deterministic query over the real file.
    """
    import csv  # noqa: PLC0415

    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return ""
        preview: list[str] = []
        total = 0
        for row in reader:
            total += 1
            if len(preview) < _CSV_PREVIEW_ROWS:
                preview.append(", ".join(row))

    lines = [
        f"DATASET: {path.name}",
        f"COLUMNS ({len(header)}): {', '.join(header)}",
        f"ROWS: {total}",
        "",
        f"First {len(preview)} row(s), for shape only — this summary is "
        "not a source for numeric answers; query the file directly for figures:",
        *preview,
    ]
    return "\n".join(lines)


# suffix -> extractor. Add an entry to support a new format; nothing else in the
# ingest path needs to change. Screenshots (.png/.jpg) are deliberately absent:
# OCR needs an external tesseract binary, and a silent empty extraction is worse
# than an explicit skip.
_EXTRACTORS: dict[str, "Callable[[Path], str]"] = {
    ".html": _extract_html,
    ".htm": _extract_html,
    ".docx": _extract_docx,
    ".pdf": _extract_pdf,
    ".csv": _extract_csv,
}

_INGESTABLE_SUFFIXES = _PLAIN_TEXT_SUFFIXES | set(_EXTRACTORS)


def extract_text(path: Path) -> str | None:
    """Return the ingestable text of `path`, or None if the format is unsupported.

    Raises ImportError (with a `pip install` hint) when the format is supported
    but its optional dependency is missing — a missing extractor must be loud,
    never a silently empty document.
    """
    suffix = path.suffix.lower()
    if suffix in _PLAIN_TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")
    extractor = _EXTRACTORS.get(suffix)
    return extractor(path) if extractor else None


def _get_collection():
    try:
        import chromadb  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "RAG requires chromadb. Install with: pip install 'consilium-py[rag]'"
        )
    client = chromadb.PersistentClient(path=str(chroma_dir()))
    # Explicit cosine distance space (chromadb's unstated default is L2/squared-L2).
    # Uses chromadb's built-in DefaultEmbeddingFunction (all-MiniLM-L6-v2 via onnxruntime).
    # Swap for chromadb.utils.embedding_functions.OpenAIEmbeddingFunction(api_key=...)
    # if you prefer OpenAI embeddings — note this requires re-indexing everything,
    # since distances across two embedding spaces aren't comparable.
    return client.get_or_create_collection(
        name=_COLLECTION, metadata={"hnsw:space": "cosine"}
    )


def _legacy_index_hint() -> None:
    """The switch to an explicit cosine collection (`consilium_runs_v2`) starts
    fresh rather than reusing the old default-distance `consilium_runs` collection
    (mixing L2 and cosine vectors in one index would make distances meaningless).
    If the new collection is empty but the old one has data, say so — otherwise
    an upgrading user can't tell "orphaned by the rename" from "never indexed."
    """
    try:
        import chromadb  # noqa: PLC0415
    except ImportError:
        return
    client = chromadb.PersistentClient(path=str(chroma_dir()))
    try:
        legacy = client.get_collection(name=_LEGACY_COLLECTION)
    except Exception:
        return
    if legacy.count() > 0:
        print(
            f"[RAG] Legacy index '{_LEGACY_COLLECTION}' has {legacy.count()} run(s) "
            f"not carried over to '{_COLLECTION}' (distance space changed to cosine). "
            "Run `consilium index` to rebuild.",
            file=sys.stderr,
        )


def new_run_id() -> str:
    return uuid.uuid4().hex


def save_run(run_id: str, inp: "DeliberationInput", report: "Report") -> Path:
    """Persist {id, timestamp, proposal, context, report} to ~/.consilium/runs/<id>.json."""
    runs = runs_dir()
    runs.mkdir(parents=True, exist_ok=True)
    record = {
        "id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proposal": inp.proposal,
        "context": inp.context,
        "report": report.model_dump(),
    }
    path = runs / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def index(
    run_id: str, inp: "DeliberationInput", report: "Report", tenant: str | None = None
) -> None:
    """Add a run to the ChromaDB vector index, keyed by run_id.

    `tenant=None` writes no tenant key at all (shared single-user corpus);
    a tenant string scopes the record so only that tenant can retrieve it.
    """
    col = _get_collection()
    document = inp.proposal + (f"\n\n{inp.context}" if inp.context else "")
    metadata: dict = {
        "kind": "run",
        "verdict": report.verdict,
        "confidence": report.confidence,
        "recommendation": report.recommendation[:500],
        "mode": report.mode,
    }
    if tenant is not None:
        metadata["tenant"] = tenant
    col.upsert(ids=[run_id], documents=[document], metadatas=[metadata])


def _tenant_clause(tenant: str | None) -> list[dict]:
    """`where` clauses scoping a query to one tenant, or none in shared mode.

    Fail closed: in scoped mode the clause also excludes records that carry no
    `tenant` key at all, so pre-tenancy data is never served to a tenant.
    """
    return [] if tenant is None else [{"tenant": tenant}]


def _query(text: str, *, kind: str, extra_where: list[dict] | None, k: int, max_distance: float):
    """Shared query path for both past-run and ingested-doc retrieval."""
    col = _get_collection()
    count = col.count()
    if count == 0:
        _legacy_index_hint()
        print(
            "[RAG] Index empty — run `consilium index` (past runs) or "
            "`consilium ingest <path>` (docs) to seed it.",
            file=sys.stderr,
        )
        return []

    from chromadb.api.types import IncludeEnum  # noqa: PLC0415

    # A single flat $and with all clauses — not a nested $and-in-$and. The flat
    # form is guaranteed supported across the chromadb range we pin; nested
    # logical operators are not universally accepted.
    clauses: list[dict] = [{"kind": kind}, *(extra_where or [])]
    where: dict = clauses[0] if len(clauses) == 1 else {"$and": clauses}

    results = col.query(
        query_texts=[text],
        n_results=min(k, count),
        where=where,
        include=[IncludeEnum.documents, IncludeEnum.metadatas, IncludeEnum.distances],
    )

    documents = results["documents"]
    metadatas = results["metadatas"]
    distances = results["distances"]
    assert documents is not None and metadatas is not None and distances is not None

    return [
        (doc, meta, dist)
        for doc, meta, dist in zip(documents[0], metadatas[0], distances[0])
        if dist <= max_distance
    ]


def retrieve(
    proposal: str, k: int = _TOP_K, max_distance: float = _MAX_DISTANCE,
    tenant: str | None = None,
) -> list[str]:
    """Return formatted snippets of past runs similar to proposal.

    Excludes STOP/BLOCK-verdict and low-confidence (<_MIN_CONFIDENCE) runs by
    design — a failed or low-confidence deliberation is not "similar past
    guidance" regardless of its embedding distance. This is a design default,
    not a measured quality claim.

    Returns an empty list if the index is empty or no run is within max_distance.
    Prints a visible message to stderr when the index is empty (not silent).
    """
    hits = _query(
        proposal, kind="run", k=k, max_distance=max_distance,
        extra_where=[
            {"confidence": {"$gte": _MIN_CONFIDENCE}},
            {"verdict": {"$nin": list(_EXCLUDED_VERDICTS)}},
            *_tenant_clause(tenant),
        ],
    )
    snippets = []
    for doc, meta, _dist in hits:
        rec = str(meta["recommendation"])[:120]
        snippets.append(f"[{meta['verdict']} {meta['confidence']:.2f}] {doc[:80]!r}: \"{rec}\"")
    return snippets


def _doc_hits(
    proposal: str, k: int = _TOP_K, max_distance: float = _MAX_DISTANCE,
    tenant: str | None = None,
) -> list[tuple[str, str]]:
    """Return `(source_id, cited_snippet)` for the nearest chunk per source file.

    Deduplicated by source: at most one chunk (the nearest) per file, so `k`
    diverse sources surface instead of `k` chunks that could all come from one
    large document. Over-fetches, then keeps the best chunk per source.

    The `source_id` half is what lets a caller verify grounding; the snippet half
    is what the voices read. Both are derived from the same single query.
    """
    hits = _query(proposal, kind="doc", k=k * 4, max_distance=max_distance,
                  extra_where=_tenant_clause(tenant))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for doc, meta, _dist in hits:  # hits are ordered nearest-first
        source = str(meta.get("source", "?"))
        if source in seen:
            continue
        seen.add(source)
        source_id = f"{source}#{meta.get('chunk_index', 0)}"
        out.append((source_id, f"[{source_id}] {doc[:200]!r}"))
        if len(out) >= k:
            break
    return out


def retrieve_docs(
    proposal: str, k: int = _TOP_K, max_distance: float = _MAX_DISTANCE,
    tenant: str | None = None,
) -> list[str]:
    """Return up to `k` source-cited snippets of ingested doc chunks similar to proposal."""
    return [snippet for _source_id, snippet in _doc_hits(proposal, k, max_distance, tenant)]


def build_rag_bundle(proposal: str, tenant: str | None = None) -> tuple[str, list[str]]:
    """Return `(context_block, doc_source_ids)` for a proposal.

    The block is prepended to the voices' context; the ids travel back to the
    caller on `Report.sources` so grounding is verifiable from outside the
    process. Past-run snippets are deliberately not cited — they are prior
    deliberations, not source documents.
    """
    blocks = []

    run_snippets = retrieve(proposal, tenant=tenant)
    if run_snippets:
        lines = "\n".join(f"  - {s}" for s in run_snippets)
        blocks.append(f"SIMILAR PAST DECISIONS:\n{lines}")

    doc_hits = _doc_hits(proposal, tenant=tenant)
    if doc_hits:
        lines = "\n".join(f"  - {snippet}" for _source_id, snippet in doc_hits)
        blocks.append(f"RELEVANT DOCS:\n{lines}")

    return "\n\n".join(blocks), [source_id for source_id, _snippet in doc_hits]


def build_rag_context(proposal: str, tenant: str | None = None) -> str:
    """Return SIMILAR PAST DECISIONS / RELEVANT DOCS blocks to prepend to context.

    Empty string if neither has anything to say.
    """
    return build_rag_bundle(proposal, tenant)[0]


def index_all_runs() -> int:
    """Index every saved run in ~/.consilium/runs/. Returns count of runs indexed."""
    runs = runs_dir()
    if not runs.exists():
        return 0
    indexed = 0
    for path in sorted(runs.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if "proposal" not in record or "report" not in record:
                continue
            from consilium.models import DeliberationInput, Report  # noqa: PLC0415
            inp = DeliberationInput(
                proposal=record["proposal"],
                context=record.get("context", ""),
            )
            report = Report(**record["report"])
            index(record["id"], inp, report)
            indexed += 1
        except Exception:
            continue
    return indexed


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping character-window chunks."""
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    step = size - overlap
    while start < len(text):
        chunk = text[start : start + size]
        if chunk.strip():
            chunks.append(chunk)
        start += step
    return chunks


def _iter_ingestable_files(path: Path):
    if path.is_file():
        yield path
        return
    for p in sorted(path.rglob("*")):
        if p.is_file() and p.suffix in _INGESTABLE_SUFFIXES:
            yield p


def ingest_path(path: str, tenant: str | None = None) -> int:
    """Chunk and index every ingestable file under `path` (file or directory).

    Returns the number of chunks indexed. Guards: skips files above
    _MAX_INGEST_FILE_BYTES, skips files that don't decode as UTF-8 text (binary
    files misdetected by extension), skips symlinks that resolve outside `path`'s
    own resolved tree (no ingesting arbitrary filesystem content via a crafted
    symlink). This command is a trusted-operator tool — it does not sandbox
    against a malicious *caller*, only against accidental misuse (huge files,
    binaries, stray symlinks).
    """
    root = Path(path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"No such file or directory: {path}")

    col = _get_collection()
    total_chunks = 0

    for file_path in _iter_ingestable_files(root):
        resolved = file_path.resolve()
        try:
            resolved.relative_to(root if root.is_dir() else root.parent)
        except ValueError:
            print(f"[ingest] Skipping {file_path} — resolves outside {root}", file=sys.stderr)
            continue

        if resolved.stat().st_size > _MAX_INGEST_FILE_BYTES:
            print(f"[ingest] Skipping {file_path} — exceeds {_MAX_INGEST_FILE_BYTES} bytes", file=sys.stderr)
            continue

        try:
            text = extract_text(resolved)
        except ImportError:
            raise  # a missing extractor dependency is loud, never a silent skip
        except (UnicodeDecodeError, OSError, ValueError) as e:
            print(f"[ingest] Skipping {file_path} — unreadable ({type(e).__name__})",
                  file=sys.stderr)
            continue
        if text is None:
            print(f"[ingest] Skipping {file_path} — no extractor for {resolved.suffix!r}",
                  file=sys.stderr)
            continue

        source = str(file_path.relative_to(root) if root.is_dir() else file_path.name)
        chunks = _chunk_text(text)
        if not chunks:
            continue

        # Drop any previous chunks for this source before re-indexing, so a file
        # that now has fewer chunks doesn't leave stale orphans behind (upsert
        # alone only overwrites matching ids, never removes surplus ones).
        delete_where: dict = {"source": source}
        if tenant is not None:
            # scope the purge: an unscoped delete would wipe another tenant's
            # chunks for a same-named file.
            delete_where = {"$and": [{"source": source}, {"tenant": tenant}]}
        col.delete(where=delete_where)

        ids = [f"doc:{source}:{i}" for i in range(len(chunks))]
        scope = {} if tenant is None else {"tenant": tenant}
        metadatas = [
            {"kind": "doc", "source": source, "chunk_index": i, **scope}
            for i in range(len(chunks))
        ]
        col.upsert(ids=ids, documents=chunks, metadatas=metadatas)  # type: ignore[arg-type]
        total_chunks += len(chunks)

    return total_chunks
