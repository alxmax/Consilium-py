"""Trias mode — 3 parallel personalities (Pioneer / Architect / Steward).
# implements: CPYMOD-TRI-001

Each personality runs a full Sequential deliberation with its lens prepended
to every voice prompt. The 3 results are aggregated by democratic majority vote.
API calls are dispatched in parallel via asyncio.to_thread (thread-pool I/O).
"""
from __future__ import annotations

import asyncio
from typing import Any

from consilium.aggregator import aggregate_sequential
from consilium.models import DeliberationInput, Report, VoiceOutput
from consilium.voices import call_voice, load_prompt

PERSONALITIES = ["pioneer", "architect", "steward"]

# Vote-pattern → confidence (from confidence.py VOTE_PATTERN_CONFIDENCE)
_VOTE_CONFIDENCE: dict[str, float | None] = {
    "3-0": 0.95,
    "2-1": 0.75,
    "2-0": 0.70,
    "1-1-1": None,
    "1-1-0": None,
    "1-0-0": None,
    "0-0-0": None,
}


# ── single personality ───────────────────────────────────────────────────────

def _run_personality(name: str, inp: DeliberationInput) -> Report:
    lens = load_prompt(f"{name}_lens")
    sep = "\n\n---\n\n"

    proposal_msg = f"PROPOSAL:\n{inp.proposal}"
    if inp.context:
        proposal_msg += f"\n\nCONTEXT:\n{inp.context}"

    cons_out = call_voice(
        "conservator",
        lens + sep + load_prompt("conservator"),
        proposal_msg,
        inp.model,
    )
    gen_msg = f"{proposal_msg}\n\n--- CONSERVATOR OUTPUT ---\n{cons_out}"
    gen_out = call_voice(
        "generator",
        lens + sep + load_prompt("generator"),
        gen_msg,
        inp.model,
    )
    ctrl_msg = f"{gen_msg}\n\n--- GENERATOR OUTPUT ---\n{gen_out}"
    ctrl_out = call_voice(
        "control",
        lens + sep + load_prompt("control"),
        ctrl_msg,
        inp.model,
    )

    return aggregate_sequential(cons_out, gen_out, ctrl_out, inp)


# ── parallel dispatch ────────────────────────────────────────────────────────

async def _run_all(inp: DeliberationInput) -> list[Report]:
    tasks = [asyncio.to_thread(_run_personality, name, inp) for name in PERSONALITIES]
    return await asyncio.gather(*tasks)


# ── team vote (adapted from aggregator.aggregate_team_vote) ─────────────────

def _team_vote(
    personalities_data: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(personalities_data) != 3:
        raise ValueError("team_vote requires exactly 3 personalities")

    valid_ids = {c["id"] for c in candidates} | {None}
    tally: dict[str, int] = {}
    abstained: list[dict] = []

    for p in personalities_data:
        chose = p.get("chose")
        if chose not in valid_ids:
            chose = None
        if chose is None:
            abstained.append({"name": p["name"]})
        else:
            tally[chose] = tally.get(chose, 0) + 1

    counts = sorted(tally.values(), reverse=True)
    pattern_parts = list(counts) + [0] * len(abstained)
    while len(pattern_parts) < 2:
        pattern_parts.append(0)
    vote_pattern = "-".join(str(x) for x in pattern_parts)

    chosen: str | None = None
    if counts and counts[0] >= 2:
        tied = [cid for cid, n in tally.items() if n == counts[0]]
        if len(tied) == 1:
            chosen = tied[0]

    return {
        "vote_pattern": vote_pattern,
        "chosen": chosen,
        "tally": tally,
        "abstained": abstained,
    }


# ── public entry point ───────────────────────────────────────────────────────

def run_trias(inp: DeliberationInput) -> Report:
    results = asyncio.run(_run_all(inp))

    # Collect what each personality chose
    p_data = [
        {"name": name, "chose": results[i].chosen}
        for i, name in enumerate(PERSONALITIES)
    ]
    candidate_ids = {r.chosen for r in results if r.chosen}
    candidates = [{"id": cid} for cid in candidate_ids]

    vote = _team_vote(p_data, candidates)
    vote_pattern: str = vote["vote_pattern"]
    winner_id: str | None = vote["chosen"]

    confidence = _VOTE_CONFIDENCE.get(vote_pattern, 0.3) or 0.3

    # Derive overall verdict and recommendation from the winning personality's report
    if winner_id is not None:
        winner_idx = next(
            (i for i, r in enumerate(results) if r.chosen == winner_id), 0
        )
        winner_report = results[winner_idx]
        verdict = winner_report.verdict
        recommendation = (
            f"[{vote_pattern} vote] {winner_report.recommendation}"
        )
    else:
        verdict = "ESCALATE"
        recommendation = (
            f"[{vote_pattern} vote] No majority — 3 personalities chose different approaches. "
            "Manual resolution required."
        )

    # Build one VoiceOutput per personality
    verdict_to_vote = {"GO": "GO", "MODIFY": "MODIFY", "STOP": "STOP",
                       "BLOCK": "BLOCK", "ESCALATE": "MODIFY"}
    voices = []
    for name, report in zip(PERSONALITIES, results):
        pv = verdict_to_vote.get(report.verdict, "MODIFY")
        voices.append(VoiceOutput(
            voice=name,
            vote=pv,  # type: ignore[arg-type]
            reasoning=report.recommendation,
            concerns=[f"chosen: {report.chosen}"] if report.chosen else [],
            score=report.confidence,
        ))

    return Report(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=round(confidence, 3),
        recommendation=recommendation,
        voices=voices,
        chosen=winner_id,
        pipeline_executed=True,
        mode="trias",
    )
