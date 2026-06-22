# Deliberate Non-Proposals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Generator reframe problems and decision-questions into candidate approaches instead of BLOCKing them, while still refusing greeting/empty input and routing dataless predictions to a low-confidence `no_data` abstain.

**Architecture:** Prompt-only change to `prompts/voices/generator.md`. The Generator already owns "is this a proposal?"; we replace its binary proposal/not-a-proposal rule with a three-way classification (proposal · reframe · `no_data` · `not_a_proposal`). The aggregator is unchanged — it still BLOCKs on `not_a_proposal` and soft-discounts `no_data`; only how often the Generator emits each flag changes.

**Tech Stack:** Markdown prompt file; Python test suite (pytest/unittest, voices mocked); reqmap drift gate.

**Testing note (read first):** Generator behavior lives in a prompt, and the test suite mocks `call_voice`, so this change has **no unit test** — that is correct, not an omission. Verification is two-pronged: (1) the existing suite stays green because no Python logic changed; (2) a live smoke matrix run by hand against a real model. Both are explicit steps below.

---

### Task 1: Rewrite the Generator's input classification

**Files:**
- Modify: `prompts/voices/generator.md` (the `## Abstain rule` section and the `Hard stop — not_a_proposal` paragraph)

- [ ] **Step 1: Add the "Input classification" section**

Insert this new section **immediately before** the existing `## Abstain rule` heading in `prompts/voices/generator.md`:

```markdown
## Input classification — what to deliberate

Before generating candidates, classify the input into exactly one of four kinds:

1. **Concrete proposal** — a specific code change or decision (e.g. "Add Redis
   caching to the API"). Generate candidates directly, as described in Task above.
2. **Problem or decision-question** — a stated problem (e.g. "the API is slow")
   or an open decision / "how should we" question (e.g. "should we migrate to
   Postgres?"). **Reframe** it into the implicit proposal *"propose approaches to
   address the stated problem / answer the stated decision"* and generate
   candidates against that goal. `success_criterion` is the resolution of the
   stated problem; `do_nothing` stays mandatory. Do NOT abstain.
   Examples: "the API is slow", "users keep mis-clicking the export button",
   "should we add Redis caching?".
3. **Prediction / factual question with no actionable data** — asks what will
   happen in a domain with no data to act on. Set `abstain.reason = "no_data"`
   (a soft code — see Abstain rule). The aggregator continues at discounted
   confidence; do not fabricate a confident answer.
   Examples: "who will win the World Cup in 2026?", "what will the stock do
   tomorrow?".
4. **Not a deliberation input** — a greeting, an empty string, or placeholder
   text with no goal at all. Set `abstain.reason = "not_a_proposal"` (a hard
   stop — see below).
   Examples: "hi", "thanks", "test", "".
```

- [ ] **Step 2: Narrow the `not_a_proposal` hard stop**

Replace the existing paragraph (currently lines ~66–70):

```markdown
**Hard stop — `not_a_proposal`:** if the input is not a code-change or decision
proposal at all (a question, an information request, a greeting, or placeholder/empty
text such as "test"), set `abstain.triggered = true` and `abstain.reason = "not_a_proposal"`.
Unlike the soft codes above, this short-circuits the deliberation to a `BLOCK` — there
is no proposal to deliberate.
```

with:

```markdown
**Hard stop — `not_a_proposal`:** reserve this for input with no deliberable goal
at all — a greeting, an empty string, or placeholder text such as "test" or "hi"
(kind 4 in Input classification). Set `abstain.triggered = true` and
`abstain.reason = "not_a_proposal"`. Unlike the soft codes above, this
short-circuits the deliberation to a `BLOCK`. A problem or a decision-question is
NOT a hard stop — reframe it (kind 2); a dataless prediction is `no_data` (kind 3),
not `not_a_proposal`.
```

- [ ] **Step 3: Run the full test suite to confirm no regression**

Run: `python -m pytest -q`
Expected: `80 passed` (no Python logic changed; this confirms nothing broke).

- [ ] **Step 4: Confirm the reqmap gate is still clean**

Run: `python scripts/reqmap.py gate`
Expected: `0 errors, 0 warnings` (generator.md is untagged; the aggregator contract in `CPYBUS-AGG-001` — BLOCK-on-`not_a_proposal`, soft-discount-`no_data` — is unchanged, so no requirement edit and no drift).

- [ ] **Step 5: Commit**

```bash
git add prompts/voices/generator.md
git commit -m "feat: reframe problems and decision-questions instead of blocking

The Generator now classifies input four ways: concrete proposal, problem/
decision-question (reframed into candidate approaches), dataless prediction
(no_data soft abstain), and greeting/empty (not_a_proposal BLOCK). Prompt-only;
the aggregator is unchanged."
```

---

### Task 2: Live smoke-matrix acceptance

**Files:** none (manual acceptance against a real model)

This is the real behavioral verification, since prompt behavior is not unit-testable. Requires a working model (`ANTHROPIC_API_KEY`, or `CONSILIUM_MODEL=provider/model` with that provider's key).

- [ ] **Step 1: Run the five acceptance inputs**

```bash
consilium deliberate "the API is slow"
consilium deliberate "should we add Redis caching?"
consilium deliberate "who will win the World Cup in 2026?"
consilium deliberate "hi"
consilium deliberate "test"
```

- [ ] **Step 2: Check each result against the expected verdict**

| Input | Expected |
|---|---|
| "the API is slow" | candidates produced → `GO`/`MODIFY` with a "How to implement" block |
| "should we add Redis caching?" | candidates produced → a verdict (not BLOCK) |
| "who will win the World Cup in 2026?" | low confidence → `STOP`/`MODIFY`; **not** a confident `GO`, **not** `BLOCK` |
| "hi" | `BLOCK` — "Not a deliberation input" |
| "test" | `BLOCK` — "Not a deliberation input" |

Expected: all five rows match. If "the API is slow" or the Redis question still BLOCKs, the reframe instruction (Task 1 Step 1, kind 2) needs sharper wording or another worked example. If "who wins the World Cup" returns a confident GO, strengthen kind 3 (the `no_data` routing).

- [ ] **Step 3: Record the outcome in the spec**

Append a short "Acceptance results (YYYY-MM-DD)" note to
`docs/superpowers/specs/2026-06-22-deliberate-non-proposals-design.md` with the
five observed verdicts, then commit:

```bash
git add docs/superpowers/specs/2026-06-22-deliberate-non-proposals-design.md
git commit -m "docs: record deliberate-non-proposals acceptance results"
```

---

## Self-Review

**Spec coverage:**
- Three-way (four-kind) classification → Task 1 Step 1. ✓
- Reframe problems/decision-questions → Task 1 Step 1, kind 2. ✓
- Predictions → `no_data` → Task 1 Step 1, kind 3. ✓
- Greeting/empty/placeholder → `not_a_proposal` BLOCK → Task 1 Steps 1 (kind 4) + 2. ✓
- Worked examples per category → Task 1 Step 1 (each kind lists examples). ✓
- No Python/aggregator change; 80 tests green → Task 1 Step 3. ✓
- reqmap check → Task 1 Step 4. ✓
- Live smoke matrix (5 criteria) → Task 2. ✓
- Out-of-scope (no classifier code, no clarify auto-rephrase, no plugin-skill edit) → honored; no task touches those. ✓

No gaps.

**Placeholder scan:** No TBD/TODO/"handle edge cases"; the exact prompt text and commands are inline. ✓

**Type consistency:** The only identifiers are the abstain reason strings `not_a_proposal` and `no_data`, used consistently across both tasks and matching the existing `generator.md` / `aggregator.py` spelling. ✓
