"""RAG context injection from past deliberation runs."""
# implements: CPYEXT-RAG-001
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
_COLLECTION = "consilium_runs"
_MAX_DISTANCE = 0.35
_TOP_K = 3


def _get_collection():
    try:
        import chromadb  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "RAG requires chromadb. Install with: pip install 'consilium-py[rag]'"
        )
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    # Uses chromadb's built-in DefaultEmbeddingFunction (all-MiniLM-L6-v2 via onnxruntime).
    # Swap for chromadb.utils.embedding_functions.OpenAIEmbeddingFunction(api_key=...)
    # if you prefer OpenAI embeddings.
    return client.get_or_create_collection(name=_COLLECTION)


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
    col.upsert(
        ids=[run_id],
        documents=[inp.proposal],
        metadatas=[{
            "verdict": report.verdict,
            "confidence": report.confidence,
            "recommendation": report.recommendation[:500],
            "mode": report.mode,
        }],
    )


def retrieve(proposal: str, k: int = _TOP_K, max_distance: float = _MAX_DISTANCE) -> list[str]:
    """Return formatted snippets of past runs similar to proposal.

    Returns an empty list if the index is empty or no run is within max_distance.
    Prints a visible message to stderr when the index is empty (not silent).
    """
    col = _get_collection()
    count = col.count()
    if count == 0:
        print(
            "[RAG] Index empty — run `consilium index` to seed from past runs.",
            file=sys.stderr,
        )
        return []

    results = col.query(
        query_texts=[proposal],
        n_results=min(k, count),
        include=["documents", "metadatas", "distances"],
    )

    snippets: list[str] = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        if dist <= max_distance:
            rec = meta["recommendation"][:120]
            snippets.append(
                f"[{meta['verdict']} {meta['confidence']:.2f}] {doc[:80]!r}: \"{rec}\""
            )

    return snippets


def build_rag_context(proposal: str) -> str:
    """Return a SIMILAR PAST DECISIONS block to prepend to context, or empty string."""
    snippets = retrieve(proposal)
    if not snippets:
        return ""
    lines = "\n".join(f"  - {s}" for s in snippets)
    return f"SIMILAR PAST DECISIONS:\n{lines}"


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
