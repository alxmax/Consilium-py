from consilium.models import DeliberationInput, Report, SkepticObjection, VoiceOutput
from consilium.modes.sequential import run_sequential
from consilium.voices import call_voice, extract_json, load_prompt


def _parse_skeptic(skeptic_out: dict, raw_text: str) -> tuple[SkepticObjection, VoiceOutput]:
    can_object: bool = bool(skeptic_out.get("can_object"))
    objection = skeptic_out.get("objection") or {}
    notes: str = skeptic_out.get("notes") or ""

    concerns: list[str] = objection.get("concrete_concerns") or []
    failure_mode: str | None = objection.get("failure_mode") or None
    addressable = objection.get("addressable") or None

    sk = SkepticObjection(
        can_object=can_object,
        failure_mode=failure_mode,
        addressable=addressable,  # type: ignore[arg-type]
        concrete_concerns=concerns,
        notes=notes,
    )

    if can_object:
        vote = "STOP" if addressable == "unaddressable" else "MODIFY"
    else:
        vote = "GO"

    voice = VoiceOutput(
        voice="skeptic",
        vote=vote,  # type: ignore[arg-type]
        reasoning=raw_text[:800],
        concerns=concerns,
        score=0.2 if can_object and addressable == "unaddressable" else (0.5 if can_object else 0.9),
    )

    return sk, voice


def run_dialectic(
    inp: DeliberationInput,
    skeptic_can_override: bool = False,
) -> Report:
    report = run_sequential(inp)

    # Build skeptic input — sees only the chosen, not the full deliberation
    chosen_id = report.chosen or "the proposed approach"
    skeptic_input = (
        f"chosen:\n"
        f"  id: {chosen_id}\n"
        f"  summary: {inp.proposal}\n"
        f"  rationale: Selected by Generator in the sequential deliberation.\n\n"
        f"success_criterion: {inp.proposal}\n\n"
        f"verification: Manual verification by the implementer."
    )
    if inp.context:
        skeptic_input += f"\n\nContext:\n{inp.context}"

    skeptic_text = call_voice("skeptic", load_prompt("skeptic"), skeptic_input, inp.model)
    skeptic_out = extract_json(skeptic_text)

    sk, skeptic_voice = _parse_skeptic(skeptic_out, skeptic_text)

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
            recommendation = f"Skeptic: in-place fix needed ({sk.failure_mode})"

    return Report(
        verdict=verdict,
        confidence=confidence,
        recommendation=recommendation,
        voices=[*report.voices, skeptic_voice],
        chosen=report.chosen,
        pipeline_executed=True,
        mode="dialectic",
        skeptic=sk,
    )
