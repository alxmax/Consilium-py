# implements: CPYMOD-DIA-001
from consilium.models import DeliberationInput, Report
from consilium.modes.sequential import run_sequential
from consilium.skeptic import challenge as skeptic_challenge


def run_dialectic(
    inp: DeliberationInput,
    skeptic_can_override: bool = False,
) -> Report:
    report = run_sequential(inp)

    # A categorical BLOCK (e.g. not_a_proposal, irreversibility, glossary_fail)
    # leaves nothing for the Skeptic to challenge — propagate it unchanged.
    if report.verdict == "BLOCK":
        return report.model_copy(update={"mode": "dialectic"})

    # Skeptic sees only the chosen candidate (summary/sketch/rationale per its
    # contract), not the full deliberation.
    chosen_id = report.chosen or "the proposed approach"
    sk, skeptic_voice = skeptic_challenge(
        chosen_id, inp,
        summary=report.chosen_summary,
        sketch=report.chosen_sketch,
        rationale=report.chosen_rationale,
    )

    verdict = report.verdict
    confidence = report.confidence
    recommendation = report.recommendation

    if skeptic_can_override and sk.can_object:
        if sk.addressable == "unaddressable":
            verdict = "BLOCK"
            confidence = 0.1
            recommendation = f"Skeptic blocked ({sk.failure_mode}): {sk.notes}"
        elif sk.addressable == "requires_redesign":
            verdict = "MODIFY"
            confidence = min(confidence, 0.5)
            recommendation = f"Skeptic requires redesign ({sk.failure_mode}): {sk.notes}"
        elif sk.addressable == "in_place" and verdict == "GO":
            verdict = "MODIFY"
            recommendation = f"Skeptic: in-place fix needed ({sk.failure_mode}): {sk.notes}"

    # model_copy keeps chosen_summary/chosen_sketch/chosen_rationale/reason —
    # a full rebuild dropped them, hiding "How to implement" and breaking the
    # scale_down → short_response swap in deliberate().
    return report.model_copy(update={
        "verdict": verdict,
        "confidence": confidence,
        "recommendation": recommendation,
        "voices": [*report.voices, skeptic_voice],
        "mode": "dialectic",
        "skeptic": sk,
    })
