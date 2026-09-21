---
id: CPYBUS-APIANSWER-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-API-001, CPYBUS-VOI-001]
---

# Public Python API — non-deliberation answers and RAG grounding

How `deliberate()` post-processes the selected mode's report: bypass answers for non-deliberation and scale-down inputs, and the RAG grounding those answers and every report carry. Split out of CPYBUS-API-001.

## WHAT — Contract

- When the selected mode returns a report with `reason == "not_a_proposal"` (a non-deliberation input — greeting, chit-chat, or empty), `deliberate()` shall replace it with a plain answer rather than return the `BLOCK`: a `Report` with `verdict = "ANSWER"`, the conversational reply from a single `voices.plain_answer()` call in `recommendation`, empty `voices`, and `confidence = 0.0`. Such answers are not persisted to RAG. (Problems and decision-questions are reframed into candidates by the Generator and never carry this reason; dataless predictions use the `no_data` gate, a low-confidence STOP.)
- When the selected mode returns a report with `reason == "scale_down"` (a trivial request the deliberation compressed to a short answer), `deliberate()` shall replace the placeholder recommendation with an actual reply from a single `voices.short_response()` call, keeping the verdict — producing the 2-sentence response the compressed path promises instead of leaking the instruction.
- Both bypass calls (`plain_answer`, `short_response`) shall receive the assembled `context` — including any RAG block — via their `context` argument. These paths discard the pipeline result, so without this the reply is produced with no sight of the retrieved material and is silently ungrounded while the surface implies otherwise.
- When `rag=True`, `deliberate()` shall populate `Report.sources` with the retrieved doc-chunk ids returned by `build_rag_bundle`, on both the ANSWER path and the normal aggregated path. With `rag=False` it shall be empty. Grounding that the caller cannot inspect is indistinguishable from no grounding.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given the selected mode returns a report with `reason == "not_a_proposal"`, when `deliberate` is called, then the returned report has `verdict == "ANSWER"` with `recommendation` supplied by `plain_answer()` (tested-by `tests/test_api.py::TestNonDeliberationAnswer`).
- Given the selected mode returns a report with `reason == "scale_down"`, when `deliberate` is called, then `report.recommendation` is the output of `short_response()` and the verdict is unchanged (tested-by `tests/test_api.py::TestNonDeliberationAnswer::test_scale_down_gets_real_short_response`).
- Given `rag=True` and a RAG block naming a fact, when a `not_a_proposal` or `scale_down` report is returned, then that block reaches `plain_answer` / `short_response` via `context` (tested-by `tests/test_api.py::TestBypassAnswersAreGrounded::test_not_a_proposal_answer_receives_rag_context` and `test_scale_down_response_receives_rag_context`).
- Given `rag=False`, when `deliberate` is called, then the bypass call receives `context == ""` (tested-by `tests/test_api.py::TestBypassAnswersAreGrounded::test_answer_without_rag_passes_empty_context`).
- Given `rag=True` and retrieval returning `["spec.md#0"]`, when `deliberate` is called, then `report.sources == ["spec.md#0"]` on both the ANSWER and aggregated paths, and is empty when `rag=False` (tested-by `tests/test_api.py::TestBypassAnswersAreGrounded::test_answer_reports_the_sources_it_was_grounded_in`, `test_deliberated_verdict_reports_sources_too`, `test_sources_empty_when_rag_disabled`).

## WHERE — Current implementation

- `src/consilium/__init__.py`
