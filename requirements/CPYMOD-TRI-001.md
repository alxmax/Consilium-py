---
id: CPYMOD-TRI-001
status: confirmed
layer: feature
owner: human
depends_on: [CPYBUS-VOI-001, CPYBUS-AGG-001, CPYBUS-SKEPTIC-001]
---

# Trias deliberation mode — 3 parallel personalities + post-vote Skeptic

Dispatches three personality-biased Sequential deliberations in parallel (Pioneer, Architect, Steward) over a **shared candidate set** produced by one neutral (lens-free) Generator run. Each personality runs with its lens prompt prepended to every voice system prompt, biasing perception without changing the voice's role; its Generator selects `preferred` among the shared candidate ids, so votes are semantically comparable. Results are aggregated by democratic majority vote; on a decisive vote, one post-vote Skeptic then challenges the winner.

## WHAT — Contract

- `run_trias(inp, skeptic_can_override=False)` shall first run one neutral Generator (`_neutral_generator`) to produce the shared candidate set, then dispatch `_run_personality(name, inp, shared_gen)` for each of the three personalities concurrently via `asyncio.to_thread` + `asyncio.gather`.
- Each personality runs its internal Sequential pipeline in Generator-first order (Generator → Conservator → Control), with its lens (`prompts/voices/{name}_lens.md`) prepended to each voice system prompt, separated from the core prompt by `\n\n---\n\n`. The personality's Generator message includes the shared candidates with the instruction to keep the exact ids and select `preferred` among them.
- **Categorical veto propagation.** If any personality's `Report` has `verdict == "BLOCK"` (glossary_fail, irreversibility, not_a_proposal, voice_unparseable), `run_trias` shall return that report (with `mode="trias"`) without voting — safety vetoes are not out-votable, and the propagated `reason` lets `deliberate()` convert `not_a_proposal` to `ANSWER`.
- After all three complete, the function shall perform a majority vote over the three `chosen` values:
  - If ≥ 2 personalities chose the same candidate → that candidate wins.
  - Otherwise → no winner.
- Vote confidence shall follow: `3-0` → 0.95, `2-1` → 0.75, `2-0` → 0.70. No majority → verdict `ESCALATE`, confidence 0.30.
- When a winner exists, the verdict and recommendation are taken from the winning personality's `Report`, and its `chosen_summary`/`chosen_sketch`/`chosen_rationale` are propagated to the trias `Report`.
- **Post-vote Skeptic.** When (and only when) a winner exists, one Skeptic (`CPYBUS-SKEPTIC-001`) shall challenge the winning candidate. Its objection is attached as `report.skeptic` and a `voice="skeptic"` `VoiceOutput` is appended.
  - **Advisory** (`skeptic_can_override=False`, default): the vote verdict, confidence, and `chosen` are unchanged regardless of the objection; an advisory note may be appended to the recommendation.
  - **Override** (`skeptic_can_override=True`): a `can_object=True` objection downgrades the verdict — `in_place`+`GO`→`MODIFY`; `requires_redesign`→`MODIFY`, confidence ≤ 0.5; `unaddressable`→`BLOCK`, confidence 0.1. `chosen` is never changed.
  - On `ESCALATE` (no winner) the Skeptic does not fire and `report.skeptic` is `None`.
- The returned `Report` shall contain one `VoiceOutput` per personality (pioneer, architect, steward) plus, on a decisive vote, a `skeptic` entry — i.e. 3 voices on `ESCALATE`, 4 on a decisive vote — not the individual voice calls.
- The `mode` field of the returned `Report` shall be `"trias"`.
- The democratic vote is over `chosen` candidate IDs, not over verdicts. When two personalities agree on `chosen`, the winning personality's `Report` (with its verdict) is used verbatim. The public API is synchronous (`asyncio.run` inside `run_trias`); making it async would require all callers to be async.


## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given three personalities all returning `chosen="a"` and a no-objection Skeptic, when `run_trias` is called, then `report.verdict == "GO"`, `report.confidence == 0.95`, `report.chosen == "a"`, `report.mode == "trias"`.
- Given two personalities returning `chosen="a"` and one returning `chosen="b"`, then `report.confidence == 0.75` and `report.chosen == "a"`.
- Given three personalities each returning a different `chosen`, then `report.verdict == "ESCALATE"`, `report.chosen is None`, `report.skeptic is None`, and `len(report.voices) == 3` (no Skeptic).
- Given a decisive vote, then `report.voices` contains 4 entries: `{"pioneer", "architect", "steward", "skeptic"}`.
- Given advisory mode and a Skeptic with `can_object=True`, then `chosen` and verdict are unchanged.
- Given override mode and a Skeptic with `addressable="unaddressable"`, then `report.verdict == "BLOCK"` and confidence `0.1`.

## WHERE — Current implementation

- `src/consilium/modes/trias.py`
- `tests/test_trias.py`
