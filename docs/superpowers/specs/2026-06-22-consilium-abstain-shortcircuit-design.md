# Design — abstain-aware short-circuit for non-proposals

**Date:** 2026-06-22
**Status:** approved (brainstorming → spec)
**Audit:** Senate verdict MODIFY (6 GO · 3 MODIFY · 0 STOP), 3 blocking conditions —
`runs/senate/2026-06-22_114319-consilium-abstain-shortcircuit.json` (in the Senate repo).

## Problem

`consilium deliberate "<not a proposal>"` (e.g. `"test"`, `"can you tell me how is
the weather in Suceava?"`) returns a `GO`/`MODIFY` verdict at ~0.6–0.7 confidence
instead of clearly rejecting the input.

Root cause (`src/consilium/aggregator.py`): when the Generator sets
`abstain.triggered=true`, `_run_sequential_scheme` records `generator_abstain` as
**one** trigger. With fewer than three triggers and no other signal, control falls
through to the `AGGREGATE` branch, which merely subtracts `0.3` from
`methodology_confidence` (`aggregator.py:137-138`). The verdict is then derived from
that confidence (`aggregator.py:246`), so a meaningless input still yields
`GO`/`MODIFY`, with the abstain reason buried in `methodology_notes`. A deliberation
tool emitting `GO` on the word "test" is a correctness bug.

## Decisive finding (from the Senate audit)

`prompts/voices/generator.md` defines `abstain` as a **soft, explicitly non-veto**
flag (line 63: "An abstain is NOT a veto") for exactly three senses:

1. internal contradiction (user wants X and not-X),
2. a prediction in a domain with no available data,
3. `goal_undefined` (no articulable fallback).

`abstain` does **not** mean "input is not a proposal." The observed
non-proposal abstains are the model improvising beyond its spec. Therefore:

- Short-circuiting on *any* `abstain` would also kill real-but-contradictory or
  underspecified proposals (senses 1 & 3) — a false-positive that silently rejects a
  legitimate deliberation, which is strictly worse than today's buried-note behavior.
- We need a **distinct** signal for "not a deliberation input", separate from
  `abstain`'s existing three senses.

## Decision

Introduce a dedicated reason code and short-circuit **only** on it. Map the outcome
to the existing `BLOCK` verdict (not a new literal) to keep the blast radius minimal —
`BLOCK` is already in `_RESULT_TO_VERDICT` and already carries categorical confidence
`0.1`, so `trias.py`, `rag.py`, and the `consilium-implement` consumers need no change.

## Changes

### 1. Generator prompt — `prompts/voices/generator.md`
Add a distinct rule, leaving the existing soft-abstain contract intact:
- When the input is **not a code-change or decision proposal** (a question, an
  information request, or placeholder/empty text), set `abstain.triggered=true` **and**
  `abstain.reason="not_a_proposal"`.
- The three existing senses keep their current `abstain.reason` values and stay on the
  soft-discount path. They describe real proposals and must not be short-circuited.

### 2. Aggregator — `src/consilium/aggregator.py` (`_run_sequential_scheme`)
Add one early-return, alongside the `glossary_fail` and `irreversibility` guards
(`aggregator.py:53-70`), firing **only** when
`generator_out.get("abstain",{}).get("triggered")` **and**
`generator_out["abstain"].get("reason") == "not_a_proposal"`:

```python
return {
    "scheme": "sequential",
    "result": "BLOCK",
    "reason": "not_a_proposal",
    "action": f"Not a deliberation input: {abstain_reason_text}",
}
```

- `result:"BLOCK"` → verdict `BLOCK`, confidence `0.1` (both already wired via
  `_RESULT_TO_VERDICT` and the categorical-confidence tuple at `aggregator.py:253`).
  No new result string or verdict literal is required.
- **Fail-safe:** malformed Generator output makes `extract_json` return `{}`, so
  `abstain` is absent, the guard is false, and control proceeds to normal deliberation.
  Non-proposal detection never depends on parse success in a way that silently mislabels.

### 3. Modes — `src/consilium/modes/dialectic.py`
If the underlying sequential `Report` is the `not_a_proposal` `BLOCK`, propagate it and
**skip the Skeptic** (challenging a non-proposal is meaningless). Detect via the
sequential report's verdict/chosen — guard before `skeptic_challenge`.

`trias` needs no code change: a personality that returns `BLOCK` contributes
`chosen=None`, which `_team_vote` already counts as an abstention. Covered by a test.

### 4. CLI — `src/consilium/cli.py`
No change expected: `_print_report` already prints `report.recommendation`, which
carries the `action` headline. Confirm the printed output reads clearly for the
`BLOCK`/`not_a_proposal` case; adjust the message wording only if needed.

### 5. Requirement contract
Update `requirements/CPYBUS-AGG-001.md` (aggregation contract) and the generator
requirement to document the new short-circuit, in the **same commit**. Then run
`python scripts/reqmap.py sync` (or `--accept-drift` if the confirmed contract text
changed) and `reqmap.py gate`.

## Acceptance criteria (tests)

Binary success criterion: a non-proposal input never yields `GO`/`MODIFY`.

- **AC1** — Given a Generator output with `abstain.triggered=true,
  reason="not_a_proposal"`, when `aggregate_sequential` runs, then `report.verdict ==
  "BLOCK"`, `report.confidence == 0.1`, and `report.recommendation` contains the
  abstain reason text; `report.verdict not in ("GO","MODIFY")`.
- **AC2** — Given a malformed Generator output (`extract_json → {}`), the result is the
  normal aggregation path, **not** the `not_a_proposal` BLOCK (no silent short-circuit
  on absent data).
- **AC3** — Given a real proposal whose Generator output carries `abstain.reason` in
  `{contradiction, no_data, goal_undefined}`, the `not_a_proposal` short-circuit does
  **not** fire (the proposal is not mislabeled "not a proposal"). Anti-misclassification.
- **AC4** — Given a dialectic run whose sequential result is the `not_a_proposal`
  BLOCK, the Skeptic is not invoked and the BLOCK propagates unchanged.

## Out of scope / explicitly not done

- No new verdict literal (`NOT_A_PROPOSAL`) — rejected for blast radius; `BLOCK` reused.
- No pre-flight non-LLM classifier (candidate approach B) — would duplicate the
  Generator's intent classification.
- No "keep all voices but forbid GO" (candidate approach C) — wastes the two downstream
  voice calls the abstain signal exists to skip.
- The `not_a_proposal` short-circuit fires after the Generator call (one model call);
  skipping the Conservator/Control calls is a natural consequence of the early-return,
  not a separate optimization to design.

## Risks accepted

- **False-positive abstain** (model flags a genuine terse proposal as `not_a_proposal`):
  reversible — the headline tells the user exactly why, and they resubmit with more
  detail. Not worth a Control backstop (that resurrects approach C's cost). Documented,
  not engineered around.
