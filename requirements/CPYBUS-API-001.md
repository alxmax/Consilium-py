---
id: CPYBUS-API-001
status: baseline
layer: bus
owner: human
depends_on: [CPYMOD-SEQ-001, CPYMOD-DIA-001, CPYMOD-TRI-001]
---

# Public Python API — deliberate()

The single public entry point for programmatic use. Routes a proposal to the requested mode and returns a `Report`.

## WHAT — Contract

- `deliberate(proposal, context="", mode="sequential", model="claude-sonnet-4-6", skeptic_can_override=False)` shall route to `run_sequential`, `run_dialectic`, or `run_trias` based on `mode`.
- Valid modes are `"sequential"`, `"dialectic"`, and `"trias"`. Any other value shall raise `ValueError` with the list of valid modes.
- `context` is injected verbatim into the proposal message for all modes.
- `model` is passed through to every API call.
- `skeptic_can_override` is forwarded only to `run_dialectic`; it is silently ignored for other modes.
- The return type is always `consilium.models.Report`.

## WHAT — Verify intent

- Should `context` accept a file path or only raw text? Currently raw text only; the CLI handles file loading before calling `deliberate`.

## HOW — Acceptance

- Given `mode="sequential"`, when `deliberate` is called, then `report.mode == "sequential"`.
- Given `mode="trias"`, when `deliberate` is called, then `report.mode == "trias"`.
- Given `mode="unknown"`, when `deliberate` is called, then `ValueError` is raised.

## WHERE — Current implementation

- `src/consilium/__init__.py`
