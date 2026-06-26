"""explain_module — stateless codebase explanation via a single call_voice dispatch."""
from __future__ import annotations

from pathlib import Path

from consilium.models import ExplainReport
from consilium.voices import call_voice, extract_json, load_prompt

# Guards against context-window overflow: cap before sending to the model.
_MAX_FILES = 20
_MAX_CHARS = 40_000  # ~10k tokens at 4 chars/token


def explain_module(path: str, model: str) -> ExplainReport:
    """Read Python files under *path* and return a structured ExplainReport."""
    p = Path(path)
    if p.is_file():
        sources = [p] if p.suffix == ".py" else []
    else:
        sources = sorted(p.rglob("*.py"))[:_MAX_FILES]

    if not sources:
        return ExplainReport(summary=f"No Python files found at {path!r}.")

    parts: list[str] = []
    total = 0
    for f in sources:
        src = f.read_text(encoding="utf-8", errors="replace")
        if total + len(src) > _MAX_CHARS:
            parts.append(f"# {f} [truncated — char limit reached]")
            break
        parts.append(f"# {f}\n{src}")
        total += len(src)

    combined = "\n\n".join(parts)
    system_prompt = load_prompt("explain")
    raw = call_voice("explain", system_prompt, combined, model)
    data = extract_json(raw)

    # Fallback: if model returned prose instead of JSON, use the first 300 chars as summary.
    summary = data.get("summary") or raw[:300].strip() or f"Explained {len(sources)} file(s)."
    return ExplainReport(
        summary=summary,
        public_api=data.get("public_api", []),
        dependencies=data.get("dependencies", []),
        data_flow=data.get("data_flow", ""),
        gotchas=data.get("gotchas", []),
    )
