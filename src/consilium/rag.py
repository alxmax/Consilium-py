"""RAG context injection from past deliberation runs and ingested reference documents."""
# implements: CPYEXT-RAG-001
# implements: CPYEXT-DOCRAG-001
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from consilium.models import DeliberationInput, Report

_RUNS_DIR = Path.home() / ".consilium" / "runs"
_CHROMA_DIR = Path.home() / ".consilium" / "chroma"
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
_MAX_INGEST_FILE_BYTES = 1_000_000  # 1 MB
_CHUNK_SIZE = 1200  # characters
_CHUNK_OVERLAP = 200  # characters
_INGESTABLE_SUFFIXES = {".md", ".txt", ".py", ".rst"}


def _get_collection():
    try:
        import chromadb  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "RAG requires chromadb. Install with: pip install 'consilium-py[rag]'"
        )
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
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
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
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
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proposal": inp.proposal,
        "context": inp.context,
        "report": report.model_dump(),
    }
    path = _RUNS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def index(run_id: str, inp: "DeliberationInput", report: "Report") -> None:
    """Add a run to the ChromaDB vector index, keyed by run_id."""
    col = _get_collection()
    document = inp.proposal + (f"\n\n{inp.context}" if inp.context else "")
    col.upsert(
        ids=[run_id],
        documents=[document],
        metadatas=[{
            "kind": "run",
            "verdict": report.verdict,
            "confidence": report.confidence,
            "recommendation": report.recommendation[:500],
            "mode": report.mode,
        }],
    )


def _query(text: str, *, kind: str, extra_where: dict | None, k: int, max_distance: float):
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

    where: dict = {"kind": kind}
    if extra_where:
        where = {"$and": [where, extra_where]}

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


def retrieve(proposal: str, k: int = _TOP_K, max_distance: float = _MAX_DISTANCE) -> list[str]:
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
        extra_where={
            "$and": [
                {"confidence": {"$gte": _MIN_CONFIDENCE}},
                {"verdict": {"$nin": list(_EXCLUDED_VERDICTS)}},
            ]
        },
    )
    snippets = []
    for doc, meta, _dist in hits:
        rec = str(meta["recommendation"])[:120]
        snippets.append(f"[{meta['verdict']} {meta['confidence']:.2f}] {doc[:80]!r}: \"{rec}\"")
    return snippets


def retrieve_docs(proposal: str, k: int = _TOP_K, max_distance: float = _MAX_DISTANCE) -> list[str]:
    """Return formatted, source-cited snippets of ingested doc chunks similar to proposal."""
    hits = _query(proposal, kind="doc", k=k, max_distance=max_distance, extra_where=None)
    snippets = []
    for doc, meta, _dist in hits:
        source = meta.get("source", "?")
        chunk_index = meta.get("chunk_index", 0)
        snippets.append(f"[{source}#{chunk_index}] {doc[:200]!r}")
    return snippets


def build_rag_context(proposal: str) -> str:
    """Return SIMILAR PAST DECISIONS / RELEVANT DOCS blocks to prepend to context.

    Empty string if neither has anything to say.
    """
    blocks = []

    run_snippets = retrieve(proposal)
    if run_snippets:
        lines = "\n".join(f"  - {s}" for s in run_snippets)
        blocks.append(f"SIMILAR PAST DECISIONS:\n{lines}")

    doc_snippets = retrieve_docs(proposal)
    if doc_snippets:
        lines = "\n".join(f"  - {s}" for s in doc_snippets)
        blocks.append(f"RELEVANT DOCS:\n{lines}")

    return "\n\n".join(blocks)


def index_all_runs() -> int:
    """Index every saved run in ~/.consilium/runs/. Returns count of runs indexed."""
    if not _RUNS_DIR.exists():
        return 0
    indexed = 0
    for path in sorted(_RUNS_DIR.glob("*.json")):
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


def ingest_path(path: str) -> int:
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
            text = resolved.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            print(f"[ingest] Skipping {file_path} — not valid UTF-8 text", file=sys.stderr)
            continue

        source = str(file_path.relative_to(root) if root.is_dir() else file_path.name)
        chunks = _chunk_text(text)
        if not chunks:
            continue

        ids = [f"doc:{source}:{i}" for i in range(len(chunks))]
        metadatas = [{"kind": "doc", "source": source, "chunk_index": i} for i in range(len(chunks))]
        col.upsert(ids=ids, documents=chunks, metadatas=metadatas)  # type: ignore[arg-type]
        total_chunks += len(chunks)

    return total_chunks
