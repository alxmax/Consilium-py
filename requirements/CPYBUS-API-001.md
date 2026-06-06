---
id: CPYBUS-API-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYMOD-SEQ-001, CPYMOD-DIA-001, CPYMOD-TRI-001]
---

# Public Python API — deliberate()

The single public entry point for programmatic use. Routes a proposal to the requested mode and returns a `Report`.

## WHAT — Contract

- `deliberate(proposal, context="", mode="sequential", model="claude-sonnet-4-6", skeptic_can_override=False, rag=False)` shall route to `run_sequential`, `run_dialectic`, `run_trias`, or `run_langgraph` based on `mode`.
- Valid modes are `"sequential"`, `"dialectic"`, `"trias"`, and `"langgraph"`. Any other value shall raise `ValueError` with the list of valid modes.
- `context` accepts raw text only; it is injected verbatim into the proposal message for all modes. File path expansion is the CLI's responsibility — the Python API always receives pre-loaded text strings.
- If the `CONSILIUM_MODEL` env var is set, it overrides the `model` parameter before any voice runs.
- `model` (after env var resolution) is passed through to every API call.
- `skeptic_can_override` is forwarded only to `run_dialectic`; it is silently ignored for other modes.
- `rag=True` enables RAG context injection (requires `consilium-py[rag]` extra; see CPYEXT-RAG-001).
- The return type is always `consilium.models.Report`.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `mode="sequential"`, when `deliberate` is called, then `report.mode == "sequential"`.
- Given `mode="trias"`, when `deliberate` is called, then `report.mode == "trias"`.
- Given `mode="langgraph"`, when `deliberate` is called, then `report.mode == "langgraph"`.
- Given `mode="unknown"`, when `deliberate` is called, then `ValueError` is raised.
- Given `CONSILIUM_MODEL=claude-haiku-4-5` in env, when `deliberate("test", model="claude-sonnet-4-6")` is called, then all voice calls use `claude-haiku-4-5`.

## WHERE — Current implementation

- `src/consilium/__init__.py`
