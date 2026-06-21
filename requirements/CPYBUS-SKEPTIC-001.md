---
id: CPYBUS-SKEPTIC-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-VOI-001]
---

# Shared Skeptic challenge

A single adversarial pass over a chosen approach, reused by Dialectic (post-Sequential) and Trias (post-vote, on the winner). The Skeptic sees only the chosen approach — never the full deliberation — and produces a concrete objection or attests there is none. Centralised in `src/consilium/skeptic.py` so both modes share one implementation.

## WHAT — Contract

- `parse_skeptic(skeptic_out, raw_text)` shall map a raw Skeptic JSON output to `(SkepticObjection, VoiceOutput)`:
  - `can_object` coerced to `bool`; `objection.concrete_concerns` → list; `objection.failure_mode`/`objection.addressable` → optional.
  - The `VoiceOutput` vote is `GO` when `can_object` is false, `STOP` when `addressable="unaddressable"`, else `MODIFY`.
  - Score: `0.9` (no objection), `0.5` (objection), `0.2` (unaddressable objection).
- `challenge(chosen_id, inp)` shall build a Skeptic input containing only the chosen id + summary (the proposal), the proposal as `success_criterion`, the optional context, then call the `skeptic` voice once and return `parse_skeptic(...)`.
- The Skeptic dispatch shall use `call_voice` / `load_prompt` from `voices.py` — no separate model client.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given a `can_object=false` output, when `parse_skeptic` is called, then the voice vote is `GO` and score `0.9`.
- Given `can_object=true, addressable="unaddressable"`, then the voice vote is `STOP` and score `0.2`.
- Given a chosen id and proposal, when `challenge` is called (with mocked `call_voice`), then exactly one `skeptic` voice call is made and a `(SkepticObjection, VoiceOutput)` pair is returned.

## WHERE — Current implementation

- `src/consilium/skeptic.py`
- exercised via `tests/test_dialectic.py` and `tests/test_trias.py`
