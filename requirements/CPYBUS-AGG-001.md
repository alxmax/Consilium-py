---
id: CPYBUS-AGG-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-VOI-001]
---

# Sequential aggregation — veto cascade and verdict mapping

Converts the three raw voice text outputs into a `Report` (a Pydantic model). Runs a veto cascade (a fixed series of checks that can short-circuit the pipeline before the normal scoring path) and maps the result to a verdict.

## WHAT — Contract

- `aggregate_sequential(cons_text, gen_text, ctrl_text, _inp)` shall parse each text argument as JSON (via `extract_json`) and run the veto cascade in this fixed priority order:
  1. `glossary_fail` from Control → `BLOCK`
  2. `irreversibility_flag` in any Conservator score → `BLOCK`
  3. Generator `abstain.triggered` with `abstain.reason == "not_a_proposal"` → `BLOCK` (the input is not a code-change or decision proposal — nothing to deliberate). This is distinct from the two *soft* abstain reasons (`contradiction`, `goal_undefined`), which do not short-circuit and instead discount `confidence_methodology` on the `AGGREGATE` path. The third Generator abstain, `no_data`, is NOT soft — it short-circuits to `STOP` (step 6).
  4. Three or more simultaneous triggers (substantial disagreement, scale_down/scale_up, soft generator abstain) → `ESCALATE` (reason `multiple_triggers`)
  5. Substantial disagreement in Control → `REWORK` → mapped to `MODIFY`
  6. Generator `abstain.reason == "no_data"` → `NO_DATA` → mapped to `STOP` at confidence `0.1` (a prediction with no evidence to weigh). Sits ABOVE `scale_down`, so such input never becomes a `GO`.
  7. `scale_down` meta-recommendation → `ADAPT_SHORT` (reason `scale_down`) → mapped to `GO`. `deliberate()` then replaces the placeholder recommendation with a generated short response (see CPYBUS-APIANSWER-001).
  8. `scale_up` meta-recommendation → `ADAPT_EXTENDED` (reason `scale_up`) → mapped to `MODIFY`
  9. Default → `AGGREGATE` (normal scoring)
- In the `AGGREGATE` path, `confidence` shall equal `confidence_methodology` (0.0–1.0). A `confidence_methodology ≥ 0.7` maps to verdict `GO`; `≥ 0.4` to `MODIFY`; below to `STOP`.
- Non-`AGGREGATE` results map as: `BLOCK`→`BLOCK`, `REWORK`→`MODIFY`, `ESCALATE`→`ESCALATE`, `ADAPT_SHORT`→`GO`, `ADAPT_EXTENDED`→`MODIFY`, `NO_DATA`→`STOP`. `REWORK` is not an exposed verdict in `Report`; it maps to `MODIFY` so callers receive a consistent surface. The `recommendation` field carries the rework context. Bypass verdicts (BLOCK, REWORK, ESCALATE, NO_DATA) carry categorical confidence values (e.g. `0.1` for BLOCK and NO_DATA); no scoring floor is applied to them.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given Conservator output with `irreversibility_flag: true`, when `aggregate_sequential` is called, then verdict is `BLOCK` and confidence is `0.1`.
- Given clean voice outputs with no triggers, when `aggregate_sequential` is called, then result is `AGGREGATE` and verdict is `GO` when `confidence_methodology ≥ 0.7`.
- Given Control output with `glossary_fail: true`, when `aggregate_sequential` is called, then verdict is `BLOCK`.
- Given Generator output with `abstain.reason == "not_a_proposal"`, when `aggregate_sequential` is called, then verdict is `BLOCK`, confidence is `0.1`, and the recommendation states it is not a deliberation input (tested-by `tests/test_sequential.py::TestRunSequential::test_not_a_proposal_blocks`). A soft abstain reason (`contradiction`, `goal_undefined`) does not short-circuit; `no_data` does (next AC).
- Given Generator `abstain.reason == "no_data"` (a prediction with no evidence), when `aggregate_sequential` is called, then verdict is `STOP`, confidence is `0.1`, and `Report.reason == "no_data"` — and this holds even when a Conservator score recommends `scale_down`, because the `no_data` gate sits above `scale_down` (tested-by `tests/test_sequential.py::TestRunSequential::test_no_data_stops_low_confidence` and `test_no_data_beats_scale_down`).

## WHERE — Current implementation

- `src/consilium/aggregator.py`
