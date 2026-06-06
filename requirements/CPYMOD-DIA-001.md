---
id: CPYMOD-DIA-001
status: baseline
layer: feature
owner: human
depends_on: [CPYMOD-SEQ-001, CPYBUS-VOI-001]
---

# Dialectic deliberation mode — Sequential + Skeptic challenger

Runs Sequential to produce a base report, then dispatches the Skeptic voice on the chosen candidate. The Skeptic sees only the chosen candidate, not the full deliberation. By default the Skeptic's objection is advisory (logged but does not change the verdict). With `skeptic_can_override=True` the Skeptic can downgrade the verdict.

## WHAT — Contract

- `run_dialectic(inp, skeptic_can_override=False)` shall first call `run_sequential(inp)`.
- After Sequential, it shall call the Skeptic voice once. The Skeptic's input shall contain only: the chosen candidate id + summary, the proposal as `success_criterion`, and the optional context.
- The Skeptic output shall be parsed into a `SkepticObjection` and added as `report.skeptic`.
- A fourth `VoiceOutput` with `voice="skeptic"` shall be appended to `report.voices`.
- **Advisory mode** (`skeptic_can_override=False`, default): the Sequential verdict and confidence are unchanged regardless of Skeptic's objection.
- **Override mode** (`skeptic_can_override=True`): if `can_object=True`, the verdict shall be downgraded:
  - `addressable="in_place"` + current verdict `GO` → `MODIFY`
  - `addressable="requires_redesign"` → `MODIFY`, confidence capped at 0.5
  - `addressable="unaddressable"` → `BLOCK`, confidence set to 0.1
- The `mode` field of the returned `Report` shall be `"dialectic"`.

## WHAT — Verify intent

- Should the Skeptic run even when Sequential returns `BLOCK` or `ESCALATE`? Currently it always runs. The Consilium skill skips it only when `chosen` is None — but `BLOCK` can also have `chosen=None`.

## HOW — Acceptance

- Given clean Sequential (GO), no Skeptic objection, when `run_dialectic` is called, then `report.verdict == "GO"` and `report.mode == "dialectic"` and `len(report.voices) == 4`.
- Given advisory mode with `can_object=True, addressable="in_place"`, when called, then verdict remains `GO`.
- Given override mode with `can_object=True, addressable="in_place"`, when called, then verdict is `MODIFY`.
- Given override mode with `addressable="unaddressable"`, when called, then verdict is `BLOCK` and confidence is `0.1`.

## WHERE — Current implementation

- `src/consilium/modes/dialectic.py`
- `tests/test_dialectic.py`
