"""Shared Skeptic challenge — one adversarial pass on a chosen approach.
# implements: CPYBUS-SKEPTIC-001

Used by Dialectic (post-Sequential) and Trias (post-vote, on the winner).
The Skeptic sees ONLY the chosen approach, never the full deliberation —
its job is to produce a concrete objection or attest there is none.
"""
from __future__ import annotations

from consilium.models import DeliberationInput, SkepticObjection, VoiceOutput
from consilium.voices import call_voice, extract_json, load_prompt


def parse_skeptic(skeptic_out: dict, raw_text: str) -> tuple[SkepticObjection, VoiceOutput]:
    """Parse a raw Skeptic JSON output into (objection, voice)."""
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


def challenge(chosen_id: str, inp: DeliberationInput) -> tuple[SkepticObjection, VoiceOutput]:
    """Dispatch one Skeptic on the chosen approach; return (objection, voice)."""
    skeptic_input = (
        f"chosen:\n"
        f"  id: {chosen_id}\n"
        f"  summary: {inp.proposal}\n"
        f"  rationale: Selected by the deliberation.\n\n"
        f"success_criterion: {inp.proposal}\n\n"
        f"verification: Manual verification by the implementer."
    )
    if inp.context:
        skeptic_input += f"\n\nContext:\n{inp.context}"

    skeptic_text = call_voice("skeptic", load_prompt("skeptic"), skeptic_input, inp.model)
    return parse_skeptic(extract_json(skeptic_text), skeptic_text)
