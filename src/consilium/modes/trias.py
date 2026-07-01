"""Trias mode — 3 parallel personalities (Pioneer / Architect / Steward).

A neutral Generator first produces one shared candidate set; each personality
then runs a full Sequential deliberation with its lens prepended to every
voice prompt, selecting its preferred among the SHARED candidate ids — so the
democratic majority vote tallies semantically comparable choices (independent
generators produced id collisions: a coincidental 'do_nothing' 3-0 scored
0.95, while the same approach under three names escalated as 'no majority').
API calls are dispatched in parallel via asyncio.to_thread (thread-pool I/O).
"""
# implements: CPYMOD-TRI-001
from __future__ import annotations

import asyncio
from typing import Any

from consilium.aggregator import aggregate_sequential
from consilium.models import DeliberationInput, Report, SkepticObjection, VoiceOutput
from consilium.skeptic import challenge as skeptic_challenge
from consilium.voices import call_voice, load_prompt

PERSONALITIES = ["pioneer", "architect", "steward"]

# Vote-pattern → confidence (ported from the original Consilium skill's confidence.py)
_VOTE_CONFIDENCE: dict[str, float | None] = {
    "3-0": 0.95,
    "2-1": 0.75,
    "2-0": 0.70,
    "1-1-1": None,
    "1-1-0": None,
    "1-0-0": None,
    "0-0-0": None,
}


# ── shared candidate set ─────────────────────────────────────────────────────

def _neutral_generator(inp: DeliberationInput) -> str:
    """One lens-free Generator run — the shared candidate set every
    personality votes on. Without it, ids are per-run labels and the vote
    tallies coincidences instead of choices."""
    proposal_msg = f"PROPOSAL:\n{inp.proposal}"
    if inp.context:
        proposal_msg += f"\n\nCONTEXT:\n{inp.context}"
    return call_voice("generator", load_prompt("generator"), proposal_msg, inp.model)


# ── single personality ───────────────────────────────────────────────────────

def _run_personality(name: str, inp: DeliberationInput, shared_gen: str) -> Report:
    lens = load_prompt(f"{name}_lens")
    sep = "\n\n---\n\n"

    proposal_msg = f"PROPOSAL:\n{inp.proposal}"
    if inp.context:
        proposal_msg += f"\n\nCONTEXT:\n{inp.context}"

    # Generator runs FIRST — blind to risk framing (anti-anchoring). It
    # evaluates the SHARED candidates through this personality's lens so its
    # `preferred` is comparable across personalities in the team vote.
    gen_msg = (
        f"{proposal_msg}\n\n"
        f"--- SHARED CANDIDATES (from a neutral Generator) ---\n{shared_gen}\n\n"
        "Evaluate THESE candidates through your lens. Keep the exact candidate "
        "ids — do not invent new ids; select your `preferred` among them. You "
        "may refine sketches/rationales, and you may still abstain per your "
        "abstain rule."
    )
    gen_out = call_voice(
        "generator",
        lens + sep + load_prompt("generator"),
        gen_msg,
        inp.model,
    )
    cons_msg = f"{proposal_msg}\n\n--- GENERATOR OUTPUT ---\n{gen_out}"
    cons_out = call_voice(
        "conservator",
        lens + sep + load_prompt("conservator"),
        cons_msg,
        inp.model,
    )
    ctrl_msg = f"{cons_msg}\n\n--- CONSERVATOR OUTPUT ---\n{cons_out}"
    ctrl_out = call_voice(
        "control",
        lens + sep + load_prompt("control"),
        ctrl_msg,
        inp.model,
    )

    return aggregate_sequential(cons_out, gen_out, ctrl_out, inp)


# ── parallel dispatch ────────────────────────────────────────────────────────

async def _run_all(inp: DeliberationInput, shared_gen: str) -> list[Report]:
    tasks = [asyncio.to_thread(_run_personality, name, inp, shared_gen) for name in PERSONALITIES]
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

def run_trias(inp: DeliberationInput, skeptic_can_override: bool = False) -> Report:
    shared_gen = _neutral_generator(inp)
    results = asyncio.run(_run_all(inp, shared_gen))

    # Categorical veto propagation: a BLOCK from any personality (glossary_fail,
    # irreversibility, not_a_proposal, voice_unparseable) is absolute — safety
    # vetoes are not out-votable, and propagating the reason lets deliberate()
    # convert not_a_proposal to ANSWER exactly like the other modes.
    blocked = next((r for r in results if r.verdict == "BLOCK"), None)
    if blocked is not None:
        return blocked.model_copy(update={"mode": "trias"})

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
    winner_report: Report | None = None
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

    # Post-vote Skeptic — fires only on a decisive vote (a winner emerged).
    # Advisory by default: never flips the winner, only annotates. With
    # skeptic_can_override it can downgrade the verdict (mirrors Dialectic).
    skeptic: SkepticObjection | None = None
    if winner_id is not None and winner_report is not None:
        sk, skeptic_voice = skeptic_challenge(
            winner_id, inp,
            summary=winner_report.chosen_summary,
            sketch=winner_report.chosen_sketch,
            rationale=winner_report.chosen_rationale,
        )
        skeptic = sk
        voices.append(skeptic_voice)
        if skeptic_can_override and sk.can_object:
            if sk.addressable == "unaddressable":
                verdict = "BLOCK"
                confidence = 0.1
                recommendation = f"Skeptic blocked winner ({sk.failure_mode}): {sk.notes}"
            elif sk.addressable == "requires_redesign":
                verdict = "MODIFY"
                confidence = min(confidence, 0.5)
                recommendation = f"Skeptic requires redesign ({sk.failure_mode}): {sk.notes}"
            elif sk.addressable == "in_place" and verdict == "GO":
                verdict = "MODIFY"
                recommendation = f"Skeptic: in-place fix needed ({sk.failure_mode}): {sk.notes}. {recommendation}"
        elif sk.can_object:
            recommendation = f"{recommendation} | Skeptic (advisory): {sk.notes}"

    return Report(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=round(confidence, 3),
        recommendation=recommendation,
        voices=voices,
        chosen=winner_id,
        chosen_summary=winner_report.chosen_summary if winner_report else None,
        chosen_sketch=winner_report.chosen_sketch if winner_report else None,
        chosen_rationale=winner_report.chosen_rationale if winner_report else None,
        pipeline_executed=True,
        mode="trias",
        skeptic=skeptic,
    )
