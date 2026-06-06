---
id: CPYMOD-TRI-001
status: confirmed
layer: feature
owner: human
depends_on: [CPYBUS-VOI-001, CPYBUS-AGG-001]
---

# Trias deliberation mode — 3 parallel personalities with democratic vote

Dispatches three personality-biased Sequential deliberations in parallel (Pioneer, Architect, Steward). Each personality runs with its lens prompt prepended to every voice system prompt, biasing perception without changing the voice's role. Results are aggregated by democratic majority vote.

## WHAT — Contract

- `run_trias(inp)` shall dispatch `_run_personality` for each of the three personalities concurrently via `asyncio.to_thread` + `asyncio.gather`.
- Each personality shall prepend its lens (`prompts/voices/{name}_lens.md`) to each voice system prompt, separated from the core prompt by `\n\n---\n\n`.
- After all three complete, the function shall perform a majority vote over the three `chosen` values:
  - If ≥ 2 personalities chose the same candidate → that candidate wins.
  - Otherwise → no winner.
- Vote confidence shall follow: `3-0` → 0.95, `2-1` → 0.75, `2-0` → 0.70. No majority → verdict `ESCALATE`, confidence 0.30.
- When a winner exists, the verdict and recommendation are taken from the winning personality's `Report`.
- The returned `Report` shall contain exactly three `VoiceOutput` entries, one per personality (pioneer, architect, steward), not the 9 individual voice calls.
- The `mode` field of the returned `Report` shall be `"trias"`.
- The democratic vote is over `chosen` candidate IDs, not over verdicts. When two personalities agree on `chosen`, the winning personality's `Report` (with its verdict) is used verbatim. The public API is synchronous (`asyncio.run` inside `run_trias`); making it async would require all callers to be async.


## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given three personalities all returning `chosen="a"`, when `run_trias` is called, then `report.verdict == "GO"`, `report.confidence == 0.95`, `report.chosen == "a"`, `report.mode == "trias"`.
- Given two personalities returning `chosen="a"` and one returning `chosen="b"`, then `report.confidence == 0.75` and `report.chosen == "a"`.
- Given three personalities each returning a different `chosen`, then `report.verdict == "ESCALATE"` and `report.chosen is None`.
- The `report.voices` list shall contain exactly 3 entries with names `{"pioneer", "architect", "steward"}`.

## WHERE — Current implementation

- `src/consilium/modes/trias.py`
- `tests/test_trias.py`
