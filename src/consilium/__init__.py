# implements: CPYBUS-API-001
# implements: CPYEXT-LTL-001
from __future__ import annotations

import os

from consilium.modes.dialectic import run_dialectic
from consilium.modes.sequential import run_sequential
from consilium.modes.trias import run_trias
from consilium.models import DeliberationInput, Report
from consilium.voices import plain_answer, short_response

_SUPPORTED_MODES = ("sequential", "dialectic", "trias", "langgraph")
_DEFAULT_MODEL = "openrouter/google/gemini-2.0-flash-001"


def deliberate(
    proposal: str,
    context: str = "",
    mode: str = "sequential",
    model: str = _DEFAULT_MODEL,
    skeptic_can_override: bool = False,
    rag: bool = False,
) -> Report:
    model = os.environ.get("CONSILIUM_MODEL", model)
    # RAG: prepend similar past decisions to context before voices run.
    if rag:
        from consilium.rag import build_rag_context, index, new_run_id, save_run  # noqa: PLC0415
        rag_block = build_rag_context(proposal)
        if rag_block:
            context = rag_block + ("\n\n" + context if context else "")

    inp = DeliberationInput(proposal=proposal, context=context, model=model)

    if mode == "sequential":
        report = run_sequential(inp)
    elif mode == "dialectic":
        report = run_dialectic(inp, skeptic_can_override=skeptic_can_override)
    elif mode == "trias":
        report = run_trias(inp)
    elif mode == "langgraph":
        from consilium.modes.langgraph_mode import run_langgraph  # noqa: PLC0415
        report = run_langgraph(inp)
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Supported: {', '.join(_SUPPORTED_MODES)}")

    # A non-deliberation input (greeting / chit-chat / empty) is not BLOCKed — it
    # is answered directly. The Generator flags these `not_a_proposal`; here we
    # replace that BLOCK sentinel with a plain ANSWER so every mode behaves the
    # same. (Problems and decision-questions are reframed into candidates by the
    # Generator and never reach here; dataless predictions stay a low-confidence
    # `no_data` deliberation.) Not persisted to RAG — it is not a deliberation.
    if report.reason == "not_a_proposal":
        return Report(
            verdict="ANSWER",
            confidence=0.0,
            recommendation=plain_answer(proposal, model),
            voices=[],
            reason="not_a_proposal",
            mode=mode,
        )

    # scale_down: the deliberation compressed to a short response. Generate the
    # actual 2-sentence reply rather than leak the "give a short response"
    # instruction (the recommendation) to the user.
    if report.reason == "scale_down":
        report = report.model_copy(update={"recommendation": short_response(proposal, model)})

    # RAG: persist + index the run after deliberation.
    if rag:
        run_id = new_run_id()
        save_run(run_id, inp, report)
        index(run_id, inp, report)

    return report
