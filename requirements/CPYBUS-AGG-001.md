---
id: CPYBUS-AGG-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-VOI-001]
---

# Sequential aggregation — veto cascade, voice extraction, Report assembly

Converts the three raw voice text outputs into a `Report` (a Pydantic model). Runs a veto cascade (a fixed series of checks that can short-circuit the pipeline before the normal scoring path) and maps the result to a verdict.

## WHAT — Contract

- `aggregate_sequential(cons_text, gen_text, ctrl_text, _inp)` shall parse each text argument as JSON (via `extract_json`) and run the veto cascade in this fixed priority order:
  1. `glossary_fail` from Control → `BLOCK`
  2. `irreversibility_flag` in any Conservator score → `BLOCK`
  3. Three or more simultaneous triggers (substantial disagreement, scale_down/scale_up, generator abstain) → `ESCALATE`
  4. Substantial disagreement in Control → `REWORK` → mapped to `MODIFY`
  5. `scale_down` meta-recommendation → `ADAPT_SHORT` → mapped to `GO`
  6. `scale_up` meta-recommendation → `ADAPT_EXTENDED` → mapped to `MODIFY`
  7. Default → `AGGREGATE` (normal scoring)
- In the `AGGREGATE` path, `confidence` shall equal `confidence_methodology` (0.0–1.0). A `confidence_methodology ≥ 0.7` maps to verdict `GO`; `≥ 0.4` to `MODIFY`; below to `STOP`.
- Non-`AGGREGATE` results map as: `BLOCK`→`BLOCK`, `REWORK`→`MODIFY`, `ESCALATE`→`ESCALATE`, `ADAPT_SHORT`→`GO`, `ADAPT_EXTENDED`→`MODIFY`. `REWORK` is not an exposed verdict in `Report`; it maps to `MODIFY` so callers receive a consistent surface. The `recommendation` field carries the rework context. Bypass verdicts (BLOCK, REWORK, ESCALATE) carry categorical confidence values (e.g. `0.1` for BLOCK); no scoring floor is applied to them.
- The returned `Report` shall contain one `VoiceOutput` per voice (conservator, generator, control) with `vote`, `score`, `reasoning`, and `concerns` fields populated from the parsed JSON.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given Conservator output with `irreversibility_flag: true`, when `aggregate_sequential` is called, then verdict is `BLOCK` and confidence is `0.1`.
- Given clean voice outputs with no triggers, when `aggregate_sequential` is called, then result is `AGGREGATE` and verdict is `GO` when `confidence_methodology ≥ 0.7`.
- Given Control output with `glossary_fail: true`, when `aggregate_sequential` is called, then verdict is `BLOCK`.

## WHERE — Current implementation

- `src/consilium/aggregator.py`
