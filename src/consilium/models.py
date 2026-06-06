from pydantic import BaseModel
from typing import Literal


class DeliberationInput(BaseModel):
    proposal: str
    context: str = ""
    model: str = "claude-sonnet-4-6"
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
    pipeline_executed: bool = True
    mode: str = "sequential"
    skeptic: SkepticObjection | None = None
