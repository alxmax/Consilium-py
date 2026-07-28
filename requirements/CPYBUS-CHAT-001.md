---
id: CPYBUS-CHAT-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-VOI-001, CPYEXT-DOCRAG-001]
---

# Chat Q&A surface — retrieve-then-answer, deliberation opt-in

A question typed into a chat box is not a code-change proposal. Routed through
`deliberate()` it is classified `not_a_proposal`, the whole pipeline result is
discarded, and a single reply is produced anyway — so the caller pays for 3–10
voice calls to reach a one-call answer. `ask()` is the direct path: retrieve from
the ingested-doc corpus, answer once, and return the chunks used.

## WHAT — Contract

- `ask(question, model=DEFAULT_MODEL, rag=True, mode=None)` shall return a `Report`.
- With `mode is None` (the default) it shall NOT invoke any deliberation mode. It
  shall build the RAG block via `build_rag_bundle(question)` when `rag` is true,
  pass that block to `plain_answer(..., context=...)`, and return
  `verdict="ANSWER"`, `confidence=0.0`, `voices=[]`, `reason="chat_answer"`,
  `pipeline_executed=False`, `mode="chat"`, and `sources` = the retrieved
  doc-chunk ids.
- With `mode` set to a member of `_SUPPORTED_MODES` it shall delegate to
  `deliberate(question, model=..., mode=mode, rag=rag)` and return its `Report`
  unchanged. A `mode` outside that set shall raise `ValueError`.
- `rag` shall default to **true**, unlike `deliberate()`: grounding is the point
  of a Q&A surface, whereas a deliberation usually has the diff in hand. With
  `rag=False` no retrieval shall occur and `sources` shall be empty.
- `CONSILIUM_MODEL` shall override the `model` argument, as everywhere else.
- The module shall not import `fastapi`, so the chat surface is usable without
  the `[server]` extra.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given a question and `mode=None`, when `ask` is called, then `deliberate` is not called and `verdict == "ANSWER"` (tested-by `tests/test_chat.py::TestAskDefaultPath::test_does_not_run_the_voice_pipeline`).
- Given a retrieved block containing a fact, when `ask` is called, then that text reaches `plain_answer`'s `context` argument (tested-by `tests/test_chat.py::TestAskDefaultPath::test_answer_is_grounded_in_retrieved_context`).
- Given retrieval returning `["spec.md#0"]`, when `ask` is called, then `Report.sources == ["spec.md#0"]` (tested-by `tests/test_chat.py::TestAskDefaultPath::test_reports_its_sources`).
- Given `rag=False`, when `ask` is called, then `build_rag_bundle` is not called and `sources` is empty (tested-by `tests/test_chat.py::TestAskDefaultPath::test_rag_disabled_skips_retrieval_and_reports_no_sources`).
- Given `mode="sequential"`, when `ask` is called, then `deliberate` is called once with that mode and `plain_answer` is not called (tested-by `tests/test_chat.py::TestAskDeliberateOptIn::test_explicit_mode_runs_the_full_deliberation`).
- Given `mode="nonsense"`, when `ask` is called, then `ValueError` is raised (tested-by `tests/test_chat.py::TestAskDeliberateOptIn::test_unknown_mode_is_rejected`).
- Given the `[server]` extra, when `POST /ask` is called, then the body's `recommendation` and `sources` are returned and an unknown `mode` yields HTTP 400 rather than 500 (tested-by `tests/test_server.py::TestAskRoute`).

## WHERE — Current implementation

- `src/consilium/chat.py`
- `src/consilium/server.py` (the `POST /ask` transport shim)
