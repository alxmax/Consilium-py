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


class Report(BaseModel):
    verdict: Literal["GO", "MODIFY", "STOP", "BLOCK", "ESCALATE"]
    confidence: float
    recommendation: str
    voices: list[VoiceOutput]
    chosen: str | None = None
    pipeline_executed: bool = True
    mode: str = "sequential"
