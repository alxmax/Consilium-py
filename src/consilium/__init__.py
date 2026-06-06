# implements: CPYBUS-API-001
from consilium.modes.dialectic import run_dialectic
from consilium.modes.sequential import run_sequential
from consilium.modes.trias import run_trias
from consilium.models import DeliberationInput, Report

_SUPPORTED_MODES = ("sequential", "dialectic", "trias", "langgraph")


def deliberate(
    proposal: str,
    context: str = "",
    mode: str = "sequential",
    model: str = "claude-sonnet-4-6",
    skeptic_can_override: bool = False,
    rag: bool = False,
) -> Report:
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

    # RAG: persist + index the run after deliberation.
    if rag:
        run_id = new_run_id()
        save_run(run_id, inp, report)
        index(run_id, inp, report)

    return report
