# Abstain-Aware Non-Proposal Short-Circuit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Generator flags an input as not a deliberation proposal, the sequential aggregator returns a `BLOCK` verdict with a clear "not a deliberation input" message instead of a `GO`/`MODIFY`.

**Architecture:** A single early-return guard in `_run_sequential_scheme` (mirroring the existing `glossary_fail`/`irreversibility` short-circuits) fires only when the Generator sets `abstain.reason == "not_a_proposal"` — a new, distinct reason code that does not disturb the three existing soft-abstain senses. The outcome reuses the existing `BLOCK` verdict (already wired through `_RESULT_TO_VERDICT` with categorical confidence `0.1`), so no verdict literal is added and no downstream consumer changes. Dialectic mode skips the Skeptic on any `BLOCK` (nothing to challenge).

**Tech Stack:** Python 3.11, pydantic, unittest, `.venv` interpreter at `.venv/Scripts/python.exe`.

**Spec:** `docs/superpowers/specs/2026-06-22-consilium-abstain-shortcircuit-design.md`

---

### Task 1: Aggregator short-circuit on `not_a_proposal`

**Files:**
- Modify: `src/consilium/aggregator.py` (`_run_sequential_scheme`, insert after the irreversibility guard at line 70, before `disagreements = ...` at line 72)
- Test: `tests/test_sequential.py`

- [ ] **Step 1: Write the failing tests**

Add these three fixtures near the top of `tests/test_sequential.py` (after `CTRL_SUBSTANTIAL`, line 60):

```python
GEN_NOT_PROPOSAL = json.dumps({
    "options": [],
    "abstain": {"triggered": True, "reason": "not_a_proposal"},
})

GEN_SOFT_ABSTAIN = json.dumps({
    "preferred": "approach_a",
    "options": [{"id": "approach_a"}, {"id": "approach_b"}],
    "abstain": {"triggered": True, "reason": "goal_undefined"},
})
```

Add these tests inside `class TestRunSequential` (after `test_rework_carries_categorical_confidence`, line 112):

```python
    def test_not_a_proposal_blocks(self):
        """AC1: a non-proposal short-circuits to BLOCK, not GO/MODIFY."""
        report = self._run(CONS_GO, GEN_NOT_PROPOSAL, CTRL_GO)
        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.confidence, 0.1)
        self.assertNotIn(report.verdict, ("GO", "MODIFY"))
        self.assertIn("not a deliberation input", report.recommendation.lower())

    def test_malformed_generator_does_not_block(self):
        """AC2: unparseable Generator output falls through, never a silent short-circuit."""
        report = self._run(CONS_GO, "this is not json", CTRL_GO)
        self.assertNotEqual(report.verdict, "BLOCK")

    def test_soft_abstain_is_not_short_circuited(self):
        """AC3: a real proposal flagged with a soft abstain reason is NOT mislabeled."""
        report = self._run(CONS_GO, GEN_SOFT_ABSTAIN, CTRL_GO)
        self.assertNotEqual(report.verdict, "BLOCK")
        self.assertNotIn("not a deliberation input", report.recommendation.lower())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sequential.py -k "not_a_proposal or malformed_generator or soft_abstain" -v`
Expected: `test_not_a_proposal_blocks` FAILS (verdict is `GO`/`MODIFY`, not `BLOCK`). The other two may pass incidentally — that is fine; they are regression guards.

- [ ] **Step 3: Add the early-return guard**

In `src/consilium/aggregator.py`, in `_run_sequential_scheme`, immediately after the irreversibility block (the `if irrev_flagged:` block ending at line 70) and before `disagreements = control_out.get("disagreements", [])` (line 72), insert:

```python
    abstain = generator_out.get("abstain") or {}
    if abstain.get("triggered") and abstain.get("reason") == "not_a_proposal":
        return {
            "scheme": "sequential",
            "result": "BLOCK",
            "reason": "not_a_proposal",
            "action": (
                "Not a deliberation input — the input is not a code change or "
                "decision to deliberate. Rephrase it as a concrete proposal "
                "(e.g. 'Add Redis caching to the API')."
            ),
        }
```

No other change is needed: `aggregate_sequential` already maps `result == "BLOCK"` to verdict `BLOCK` via `_RESULT_TO_VERDICT` (line 221) with categorical confidence `0.1` (line 253), and sets `recommendation = agg.get("action")` (line 254).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sequential.py -v`
Expected: all tests PASS, including the three new ones.

- [ ] **Step 5: Commit**

```bash
git add src/consilium/aggregator.py tests/test_sequential.py
git commit -m "feat: short-circuit non-proposal inputs to BLOCK in aggregator"
```

---

### Task 2: Teach the Generator the `not_a_proposal` reason code

**Files:**
- Modify: `prompts/voices/generator.md` (the `## Abstain rule` section, lines 55-63)

- [ ] **Step 1: Rewrite the Abstain rule section**

Replace the section that currently reads (lines 55-63):

```markdown
## Abstain rule (soft — non-blocking)

Set `abstain.triggered = true` in these 2 cases only:
1. Input contains an internal contradiction (user wants X and explicitly not-X)
2. Input asks for a prediction in a domain with no available data

(A missing prerequisite from Control's `glossary_fail` is not a Generator trigger — Control runs *after* Generator, and a `glossary_fail` is handled by the aggregator's Priority-1 BLOCK, not a Generator abstain.)

An abstain is NOT a veto — the aggregator continues but discounts `confidence_methodology`.
```

with:

```markdown
## Abstain rule

Set `abstain.triggered = true` and `abstain.reason` to one of the **soft** codes
below. Soft abstains are NOT a veto — the aggregator continues but discounts
`confidence_methodology`:
1. `contradiction` — input contains an internal contradiction (user wants X and explicitly not-X)
2. `no_data` — input asks for a prediction in a domain with no available data
3. `goal_undefined` — the user cannot articulate a fallback in 2 attempts

(A missing prerequisite from Control's `glossary_fail` is not a Generator trigger — Control runs *after* Generator, and a `glossary_fail` is handled by the aggregator's Priority-1 BLOCK, not a Generator abstain.)

**Hard stop — `not_a_proposal`:** if the input is not a code-change or decision
proposal at all (a question, an information request, a greeting, or placeholder/empty
text such as "test"), set `abstain.triggered = true` and `abstain.reason = "not_a_proposal"`.
Unlike the soft codes above, this short-circuits the deliberation to a `BLOCK` — there
is no proposal to deliberate.
```

- [ ] **Step 2: Verify the prompt still loads**

Run: `.venv/Scripts/python.exe -c "from consilium.voices import load_prompt; print('not_a_proposal' in load_prompt('generator'))"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add prompts/voices/generator.md
git commit -m "feat: add not_a_proposal abstain reason to generator prompt"
```

---

### Task 3: Dialectic mode skips the Skeptic on a BLOCK verdict

**Files:**
- Modify: `src/consilium/modes/dialectic.py` (`run_dialectic`, after `report = run_sequential(inp)` at line 11)
- Test: `tests/test_dialectic.py`

- [ ] **Step 1: Write the failing test**

Add this fixture near the top of `tests/test_dialectic.py` (after `CTRL_GO`, line 16):

```python
GEN_NOT_PROPOSAL = json.dumps({
    "options": [],
    "abstain": {"triggered": True, "reason": "not_a_proposal"},
})
```

Add this test inside `class TestRunDialectic` (after `test_advisory_unaddressable_stays_go`, line 102):

```python
    def test_block_skips_skeptic(self):
        """AC4: a not_a_proposal BLOCK from sequential skips the Skeptic entirely."""
        from consilium.models import DeliberationInput
        from consilium.modes.dialectic import run_dialectic

        seq_outputs = iter([GEN_NOT_PROPOSAL, CONS_GO, CTRL_GO])
        skeptic_calls = []

        def mock_seq(*_a, **_kw):
            return next(seq_outputs)

        def mock_skeptic(*_a, **_kw):
            skeptic_calls.append(1)
            return SKEPTIC_NO_OBJECTION

        with patch("consilium.modes.sequential.call_voice", side_effect=mock_seq), \
             patch("consilium.skeptic.call_voice", side_effect=mock_skeptic):
            report = run_dialectic(DeliberationInput(proposal="weather in Suceava?"))

        self.assertEqual(report.verdict, "BLOCK")
        self.assertEqual(report.mode, "dialectic")
        self.assertEqual(len(skeptic_calls), 0)
        self.assertEqual(len(report.voices), 3)
        self.assertIsNone(report.skeptic)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dialectic.py::TestRunDialectic::test_block_skips_skeptic -v`
Expected: FAIL — the Skeptic is still invoked (`len(skeptic_calls)` is 1, and `report.voices` has length 4).

- [ ] **Step 3: Add the BLOCK guard**

In `src/consilium/modes/dialectic.py`, immediately after `report = run_sequential(inp)` (line 11) and before the `# Skeptic sees only the chosen` comment (line 13), insert:

```python
    # A categorical BLOCK (e.g. not_a_proposal, irreversibility, glossary_fail)
    # leaves nothing for the Skeptic to challenge — propagate it unchanged.
    if report.verdict == "BLOCK":
        return report.model_copy(update={"mode": "dialectic"})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_dialectic.py -v`
Expected: all tests PASS, including `test_block_skips_skeptic`.

- [ ] **Step 5: Commit**

```bash
git add src/consilium/modes/dialectic.py tests/test_dialectic.py
git commit -m "feat: dialectic skips skeptic on BLOCK verdict"
```

---

### Task 4: Full suite + requirement contract sync

**Files:**
- Modify: `requirements/CPYBUS-AGG-001.md` (document the new short-circuit)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all tests PASS (no regressions in trias/langgraph/cli/api/etc.).

- [ ] **Step 2: Document the short-circuit in the requirement contract**

Open `requirements/CPYBUS-AGG-001.md`. In its `## WHAT — Contract` section, add one bullet:

```markdown
- When the Generator sets `abstain.triggered = true` with `abstain.reason ==
  "not_a_proposal"`, the sequential scheme short-circuits to verdict `BLOCK`
  (confidence `0.1`) with a "Not a deliberation input" recommendation, without
  running normal aggregation. The three soft abstain reasons (`contradiction`,
  `no_data`, `goal_undefined`) are unaffected and stay on the confidence-discount path.
```

In its `## HOW — Acceptance` section, add:

```markdown
- Given a Generator output with `abstain.reason == "not_a_proposal"`, when
  `aggregate_sequential` runs, then `verdict == "BLOCK"` and `confidence == 0.1`
  (tested-by `tests/test_sequential.py::TestRunSequential::test_not_a_proposal_blocks`).
```

- [ ] **Step 3: Sync the requirement lock + map and run the gate**

Run:
```bash
.venv/Scripts/python.exe scripts/reqmap.py sync --accept-drift
.venv/Scripts/python.exe scripts/reqmap.py gate
```
Expected: `sync` rewrites the lock + map; `gate` prints `0 errors` (warnings acceptable).

- [ ] **Step 4: Manual smoke test (optional, needs a working model key)**

Run:
```bash
GEMINI_API_KEY=... CONSILIUM_MODEL=gemini/gemini-2.5-flash .venv/Scripts/consilium.exe deliberate "can you tell me how is the weather in Suceava?"
```
Expected: `Verdict: BLOCK`, `Confidence: 0.10`, and a "Not a deliberation input" message — not `GO`/`MODIFY`.

- [ ] **Step 5: Commit**

```bash
git add requirements/CPYBUS-AGG-001.md requirements/_reqlock.json requirements/_map.md requirements/_map.json requirements/_map.html docs/map.html
git commit -m "docs: document not_a_proposal short-circuit in CPYBUS-AGG-001"
```

---

## Self-review notes

- **Spec coverage:** AC1 → Task 1 `test_not_a_proposal_blocks`; AC2 → Task 1 `test_malformed_generator_does_not_block`; AC3 → Task 1 `test_soft_abstain_is_not_short_circuited`; AC4 → Task 3 `test_block_skips_skeptic`. Generator prompt change → Task 2. Contract update → Task 4.
- **Deviation from spec (intentional):** the spec's "Out of scope" note assumed the short-circuit naturally skips the Conservator/Control calls. It does not — `run_sequential` calls all three voices before aggregation. Detection stays solely in the aggregator (DRY); the two extra calls on a rare non-proposal are accepted rather than duplicating abstain logic into `sequential.py`.
- **No new verdict literal**, no `models.py` change, no `_RESULT_TO_VERDICT` entry, no CLI change — `BLOCK` is reused end-to-end, matching the approved decision.
- **Type consistency:** `abstain.reason == "not_a_proposal"` is the single discriminator used identically in Task 1 (aggregator) and Task 2 (prompt). `report.model_copy(update={"mode": "dialectic"})` uses pydantic v2 `model_copy`.
