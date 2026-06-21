# implements: CPYMOD-SEQ-001
from consilium.aggregator import aggregate_sequential
from consilium.models import DeliberationInput, Report
from consilium.voices import call_voice, load_prompt


def run_sequential(inp: DeliberationInput) -> Report:
    proposal_msg = f"PROPOSAL:\n{inp.proposal}"
    if inp.context:
        proposal_msg += f"\n\nCONTEXT:\n{inp.context}"

    # Generator runs FIRST — blind to risk framing (anti-anchoring).
    gen_out = call_voice("generator", load_prompt("generator"), proposal_msg, inp.model)

    # Conservator runs second — scores the risk of Generator's candidates.
    cons_msg = f"{proposal_msg}\n\n--- GENERATOR OUTPUT ---\n{gen_out}"
    cons_out = call_voice("conservator", load_prompt("conservator"), cons_msg, inp.model)

    # Control runs third — sees both candidates and risk.
    ctrl_msg = f"{cons_msg}\n\n--- CONSERVATOR OUTPUT ---\n{cons_out}"
    ctrl_out = call_voice("control", load_prompt("control"), ctrl_msg, inp.model)

    return aggregate_sequential(cons_out, gen_out, ctrl_out, inp)
