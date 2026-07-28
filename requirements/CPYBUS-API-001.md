---
id: CPYBUS-API-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYMOD-SEQ-001, CPYMOD-DIA-001, CPYMOD-TRI-001]
---

# Public Python API — deliberate()

The single public entry point for programmatic use. Routes a proposal to the requested mode and returns a `Report`.

## WHAT — Contract

- `deliberate(proposal, context="", mode="sequential", model="claude-sonnet-4-6", skeptic_can_override=False, rag=False)` shall route to `run_sequential`, `run_dialectic`, `run_trias`, or `run_langgraph` based on `mode`.
- Valid modes are `"sequential"`, `"dialectic"`, `"trias"`, and `"langgraph"`. Any other value shall raise `ValueError` with the list of valid modes.
- `context` accepts raw text only; it is injected verbatim into the proposal message for all modes. File path expansion is the CLI's responsibility — the Python API always receives pre-loaded text strings.
- If the `CONSILIUM_MODEL` env var is set, it overrides the `model` parameter before any voice runs.
- `model` (after env var resolution) is passed through to every API call.
- `skeptic_can_override` is forwarded only to `run_dialectic`; it is silently ignored for other modes.
- `rag=True` enables RAG context injection (requires `consilium-py[rag]` extra; see CPYEXT-RAG-001).
- The return type is always `consilium.models.Report`.
- When the selected mode returns a report with `reason == "not_a_proposal"` (a non-deliberation input — greeting, chit-chat, or empty), `deliberate()` shall replace it with a plain answer rather than return the `BLOCK`: a `Report` with `verdict = "ANSWER"`, the conversational reply from a single `voices.plain_answer()` call in `recommendation`, empty `voices`, and `confidence = 0.0`. Such answers are not persisted to RAG. (Problems and decision-questions are reframed into candidates by the Generator and never carry this reason; dataless predictions use the `no_data` gate, a low-confidence STOP.)
- When the selected mode returns a report with `reason == "scale_down"` (a trivial request the deliberation compressed to a short answer), `deliberate()` shall replace the placeholder recommendation with an actual reply from a single `voices.short_response()` call, keeping the verdict — producing the 2-sentence response the compressed path promises instead of leaking the instruction.
- Both bypass calls (`plain_answer`, `short_response`) shall receive the assembled `context` — including any RAG block — via their `context` argument. These paths discard the pipeline result, so without this the reply is produced with no sight of the retrieved material and is silently ungrounded while the surface implies otherwise.
- When `rag=True`, `deliberate()` shall populate `Report.sources` with the retrieved doc-chunk ids returned by `build_rag_bundle`, on both the ANSWER path and the normal aggregated path. With `rag=False` it shall be empty. Grounding that the caller cannot inspect is indistinguishable from no grounding.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `mode="sequential"`, when `deliberate` is called, then `report.mode == "sequential"`.
- Given `mode="trias"`, when `deliberate` is called, then `report.mode == "trias"`.
- Given `mode="langgraph"`, when `deliberate` is called, then `report.mode == "langgraph"`.
- Given `mode="unknown"`, when `deliberate` is called, then `ValueError` is raised.
- Given `CONSILIUM_MODEL=claude-haiku-4-5` in env, when `deliberate("test", model="claude-sonnet-4-6")` is called, then all voice calls use `claude-haiku-4-5`.
- Given the selected mode returns a report with `reason == "not_a_proposal"`, when `deliberate` is called, then the returned report has `verdict == "ANSWER"` with `recommendation` supplied by `plain_answer()` (tested-by `tests/test_api.py::TestNonDeliberationAnswer`).
- Given the selected mode returns a report with `reason == "scale_down"`, when `deliberate` is called, then `report.recommendation` is the output of `short_response()` and the verdict is unchanged (tested-by `tests/test_api.py::TestNonDeliberationAnswer::test_scale_down_gets_real_short_response`).
- Given `rag=True` and a RAG block naming a fact, when a `not_a_proposal` or `scale_down` report is returned, then that block reaches `plain_answer` / `short_response` via `context` (tested-by `tests/test_api.py::TestBypassAnswersAreGrounded::test_not_a_proposal_answer_receives_rag_context` and `test_scale_down_response_receives_rag_context`).
- Given `rag=False`, when `deliberate` is called, then the bypass call receives `context == ""` (tested-by `tests/test_api.py::TestBypassAnswersAreGrounded::test_answer_without_rag_passes_empty_context`).
- Given `rag=True` and retrieval returning `["spec.md#0"]`, when `deliberate` is called, then `report.sources == ["spec.md#0"]` on both the ANSWER and aggregated paths, and is empty when `rag=False` (tested-by `tests/test_api.py::TestBypassAnswersAreGrounded::test_answer_reports_the_sources_it_was_grounded_in`, `test_deliberated_verdict_reports_sources_too`, `test_sources_empty_when_rag_disabled`).

## WHERE — Current implementation

- `src/consilium/__init__.py`
