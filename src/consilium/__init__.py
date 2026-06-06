from consilium.modes.sequential import run_sequential
from consilium.models import DeliberationInput, Report


def deliberate(
    proposal: str,
    context: str = "",
    mode: str = "sequential",
    model: str = "claude-sonnet-4-6",
) -> Report:
    inp = DeliberationInput(proposal=proposal, context=context, model=model)
    if mode == "sequential":
        return run_sequential(inp)
    raise ValueError(f"Unknown mode: {mode!r}. v1 supports: sequential")
