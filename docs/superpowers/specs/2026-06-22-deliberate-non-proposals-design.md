# Deliberate non-proposals (reframe problems & decision-questions)

- **Date:** 2026-06-22
- **Status:** design approved, pending spec review
- **Scope:** `prompts/voices/generator.md` only (prompt-only; no Python changes)

## Problem

Today the Generator hard-stops any input that isn't a concrete code-change or
decision proposal — a question, an information request, a greeting, or
placeholder text — with `abstain.reason = "not_a_proposal"`, which the
aggregator turns into a `BLOCK` (`generator.md` lines 66–70; `CPYBUS-AGG-001`).

That makes the engine refuse useful inputs that *are* deliberable once reframed:

- A **problem** — "the API is slow" — has obvious candidate solutions.
- A **decision-question** — "should we add Redis caching?" — is a decision to weigh.

Both currently dead-end at `BLOCK`. The user wants Consilium to deliberate these
("questions, suggestions, problems"), while still refusing input that genuinely
has nothing to deliberate.

## Goal / success criteria

Consilium produces a normal verdict (with the how-to-implement block) for
problems and decision-questions, **without** faking verdicts for inputs that
carry no actionable decision, and **without** new Python code or pipeline steps.

Concretely, after the change:

1. "the API is slow" → Generator emits candidates → GO/MODIFY with how-to-implement.
2. "should we add Redis caching?" → candidates → verdict.
3. "who will win the World Cup in 2026?" → `no_data` soft abstain → low confidence,
   STOP/MODIFY — **never** a confident GO, **never** a hard BLOCK.
4. "hi" / "test" / "" → still `not_a_proposal` → BLOCK.
5. The existing 80 tests stay green (no logic changed).

## Design

The decision of "what is deliberable" lives entirely in the Generator prompt,
and the aggregator already does the right thing with each abstain code. So the
change is to make the Generator classify input **three ways** instead of the
current binary, and reframe the deliberable middle case.

### Classification (rewrite of the `not_a_proposal` section)

| Input | Generator action | abstain | Downstream result |
|---|---|---|---|
| Concrete change / decision proposal | candidates as usual | none | normal verdict |
| **Problem** or **decision-question** | **reframe** as "propose approaches to address X", then candidates (incl. `do_nothing`) | none | normal verdict + how-to-implement |
| **Prediction / factual Q with no actionable data** | abstain | `no_data` (existing soft code) | deliberates, low confidence → STOP/MODIFY |
| **Greeting / empty / placeholder** ("hi", "test", "") | abstain | `not_a_proposal` (unchanged) | BLOCK |

### Reframing rule (added to the prompt)

When the input states a problem or asks a decision/"how should we" question
rather than naming a concrete change, treat it as the implicit proposal
"address the stated problem / answer the stated decision" and generate candidate
approaches against that goal. `do_nothing` remains mandatory; `success_criterion`
is the resolution of the stated problem.

### Boundary, made concrete with examples

The prompt will carry 2–3 worked examples per category so the deliberable-vs-
non-deliberable line is not left to unguided judgment:

- **Reframe:** "the API is slow", "users keep mis-clicking the export button",
  "should we migrate to Postgres?"
- **`no_data`:** "who wins the World Cup 2026?", "what will the stock do tomorrow?"
- **`not_a_proposal` (BLOCK):** "hi", "test", "", "thanks".

## What does NOT change

- `aggregator.py`: `not_a_proposal` → BLOCK and `no_data` → confidence discount
  are untouched. Only how *often* the Generator emits `not_a_proposal` drops.
- Conservator, Control, confidence, report assembly, and the how-to-implement
  output all work unchanged once candidates exist.
- The bounded interactive clarify branch stays as the backstop for inputs that
  still BLOCK.

## Verification

Prompt behavior is not unit-testable here (tests mock `call_voice`), so:

1. `python -m pytest` → 80 passed (no logic changed).
2. Live smoke matrix (run `consilium deliberate "<input>"`): the five success
   criteria above, checked by hand.
3. reqmap: confirm whether `generator.md`'s classification is a tracked contract
   (Generator/VOI requirement). If so, update the requirement + `sync` to
   re-baseline; gate must stay 0/0.

## Risks & mitigations

- **Fuzzy boundary** (LLM judgment on deliberable-vs-trivia): mitigated by the
  worked examples in each category, and by routing genuine-but-dataless
  questions to the softer `no_data` (low confidence) rather than a confident GO.
- **Verdict-semantics shift**: a GO now sometimes means "pursue this approach to
  the stated problem" rather than "accept this concrete change". Acceptable and
  already how a decision-question would read; the how-to-implement block makes
  the chosen approach explicit.

## Out of scope

- No new pipeline step or classifier code (rejected Approach B).
- No auto-rephrase inside the clarify branch (rejected Approach C — it would
  contradict the "human supplies the proposal" principle).
- No change to the `consilium` plugin skill's copy of `generator.md` (separate
  codebase; this spec is for `consilium-py`).
