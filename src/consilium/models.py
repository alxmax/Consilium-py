from pydantic import BaseModel
from typing import Literal


class DeliberationInput(BaseModel):
    proposal: str
    context: str = ""
    model: str = "openrouter/google/gemini-2.0-flash-001"
    effort: Literal["low", "medium", "high"] = "medium"


class VoiceOutput(BaseModel):
    voice: str
    vote: Literal["GO", "MODIFY", "STOP", "BLOCK"]
    reasoning: str
    concerns: list[str] = []
    score: float = 0.5


class SkepticObjection(BaseModel):
    can_object: bool
    failure_mode: str | None = None
    addressable: Literal["in_place", "requires_redesign", "unaddressable"] | None = None
    concrete_concerns: list[str] = []
    notes: str = ""


class Report(BaseModel):
    verdict: Literal["GO", "MODIFY", "STOP", "BLOCK", "ESCALATE"]
    confidence: float
    recommendation: str
    voices: list[VoiceOutput]
    chosen: str | None = None
    # "How to implement" — the chosen candidate's detail, surfaced from the
    # Generator so a GO/MODIFY verdict carries actionable guidance, not just a
    # verdict line. Populated only when a candidate is chosen.
    chosen_summary: str | None = None
    chosen_sketch: str | None = None
    chosen_rationale: str | None = None
    # Machine-readable bypass reason (e.g. "not_a_proposal", "glossary_fail").
    # None on a normal aggregated verdict. Lets callers branch without parsing
    # the human-facing recommendation text.
    reason: str | None = None
    pipeline_executed: bool = True
    mode: str = "sequential"
    skeptic: SkepticObjection | None = None
