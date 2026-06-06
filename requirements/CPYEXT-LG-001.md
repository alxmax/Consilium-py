---
id: CPYEXT-LG-001
status: confirmed
layer: feature
owner: human
depends_on: [CPYBUS-API-001, CPYBUS-VOI-001, CPYBUS-AGG-001]
---

# LangGraph orchestration mode

Optional `[langgraph]` extra that re-expresses the Conservator→Generator→Control pipeline as a LangGraph `StateGraph`. Adds `mode="langgraph"` as an additional dispatch option alongside `sequential`, `dialectic`, and `trias`. Demonstrates LangGraph state machine orchestration patterns.

## WHAT — Contract

- `run_langgraph(inp)` shall run the three voices in the same order as `run_sequential` (Conservator→Generator→Control), using the same `call_voice()` and prompt loading contract.
- The pipeline shall be expressed as a `StateGraph` with `DeliberationState(TypedDict)` holding `proposal`, `context`, `model`, `conservator_out`, `generator_out`, `control_out`.
- Each node shall call `call_voice()` from `voices.py` directly — no `langchain-anthropic` dependency.
- `aggregate_sequential` shall be called on the final state to produce the `Report`.
- The `mode` field of the returned `Report` shall be `"langgraph"`.
- `run_langgraph` shall be additive: `run_sequential()` is not modified. Both routes produce equivalent `Report` verdicts for the same input.
- When `langgraph` is not installed, importing `langgraph_mode` shall raise `ImportError` with a `pip install consilium-py[langgraph]` hint.
- `mode="langgraph"` is available for both `consilium deliberate` and `consilium check` (both CLI Choice lists include it; no CLI-specific restriction applies).


## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given a proposal with mocked `call_voice`, when `run_langgraph(inp)` is called, then `report.mode == "langgraph"` and `report.pipeline_executed is True`.
- Given the same proposal and mocked voices, when `run_langgraph` and `run_sequential` are called, then both return the same `verdict`.
- Given `langgraph` not installed, when `langgraph_mode` is imported, then `ImportError` is raised with the install hint.
- Given `mode="langgraph"` passed to `deliberate()`, when called, then dispatch reaches `run_langgraph` without raising `ValueError`.

## WHERE — Current implementation

- `src/consilium/modes/langgraph_mode.py`
- `src/consilium/__init__.py` (mode dispatch)
- `src/consilium/cli.py` (click.Choice)
