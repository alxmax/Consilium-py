---
id: CPYMOD-SEQ-001
status: baseline
layer: feature
owner: human
depends_on: [CPYBUS-VOI-001, CPYBUS-AGG-001]
---

# Sequential deliberation mode

Runs Conservator, Generator, and Control in a fixed single-context chain. Each voice sees the outputs of all prior voices. Returns a `Report` with verdict, confidence, and one `VoiceOutput` per voice.

## WHAT — Contract

- `run_sequential(inp)` shall call the three voices in this order: Conservator first (no prior context), Generator second (sees Conservator output), Control third (sees both).
- Each voice call shall use the system prompt from `prompts/voices/{name}.md` with the proposal and optional context in the user message.
- The function shall return the `Report` produced by `aggregate_sequential`.
- The `mode` field of the returned `Report` shall be `"sequential"`.

## WHAT — Verify intent

- Should the proposal language be English-only, or multilingual? The prompts are in English; a Romanian proposal will work but responses may mix languages.

## HOW — Acceptance

- Given a proposal with no risk triggers, when `run_sequential` is called (with mocked `call_voice`), then `report.mode == "sequential"` and `report.pipeline_executed is True`.
- Given Conservator output with `irreversibility_flag: true`, when `run_sequential` is called, then `report.verdict == "BLOCK"`.
- Given clean voice outputs, when `run_sequential` is called, then `len(report.voices) == 3` with voices named conservator, generator, control.

## WHERE — Current implementation

- `src/consilium/modes/sequential.py`
- `tests/test_sequential.py`
