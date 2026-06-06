from consilium.modes.dialectic import run_dialectic
from consilium.modes.sequential import run_sequential
from consilium.models import DeliberationInput, Report


def deliberate(
    proposal: str,
    context: str = "",
    mode: str = "sequential",
    model: str = "claude-sonnet-4-6",
    skeptic_can_override: bool = False,
) -> Report:
    inp = DeliberationInput(proposal=proposal, context=context, model=model)
    if mode == "sequential":
        return run_sequential(inp)
    if mode == "dialectic":
        return run_dialectic(inp, skeptic_can_override=skeptic_can_override)
    raise ValueError(f"Unknown mode: {mode!r}. Supported: sequential, dialectic")
