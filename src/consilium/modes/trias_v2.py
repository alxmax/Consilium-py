"""Trias v2 — Trias + disagreement-aware aggregation + capped verification.
# implements: CPYMOD-TRI2-001

Builds on Trias (3 blind, parallel personalities + team vote) and adds the two
quality levers validated by Senate 2026-06-20 (build-in-consilium-py,
lever-before-vehicle, parallelism != smarter):

  1. Disagreement-aware aggregation — a scalar = number of distinct ``chosen``
     approaches across the 3 personalities (1 = consensus, 2/3 = split).
  2. Capped verification — on a SPLIT only, ONE skeptic pass challenges the
     team-vote winner, using the dissenter's choice as the counter-hypothesis.
     ADVISORY by default: it never changes the official ``chosen`` (independence
     audit — the vote is authoritative); it can only lower confidence / attach a
     caveat. Hard cap = ``VERIFICATION_CAP`` (1) — a single pass, never a loop.

Parallelism and blindness are inherited unchanged from Trias: the 3 personalities
are dispatched concurrently and never see each other (the de-correlation source).
LangGraph is intentionally NOT a dependency here — per Senate (Musk) the quality
lever is plain Python; a LangGraph presentation layer can wrap this later (F3).
"""
from __future__ import annotations

import asyncio

from consilium.models import DeliberationInput, Report, SkepticObjection, VoiceOutput
from consilium.modes.dialectic import _parse_skeptic
from consilium.modes.trias import (
    PERSONALITIES,
    _VOTE_CONFIDENCE,
    _run_all,
    _team_vote,
)
from consilium.voices import call_voice, extract_json, load_prompt

VERIFICATION_CAP = 1  # hard cap: at most one verification pass, never a loop

_VERDICT_TO_VOTE = {"GO": "GO", "MODIFY": "MODIFY", "STOP": "STOP",
                    "BLOCK": "BLOCK", "ESCALATE": "MODIFY"}


# ── capped verification (advisory; never flips the vote) ─────────────────────

def _verify_winner(
    winner: Report, runner_up: Report | None, inp: DeliberationInput,
) -> tuple[SkepticObjection, VoiceOutput]:
    """One capped skeptic pass on the team-vote winner. ADVISORY — no vote flip.

    The dissenter's chosen approach is supplied as a counter-hypothesis the skeptic
    must actively attack (coverage compensation for challenging only the winner).
    """
    counter = (runner_up.chosen if runner_up and runner_up.chosen
               else "the losing alternative")
    skeptic_input = (
        f"chosen:\n"
        f"  id: {winner.chosen}\n"
        f"  summary: {inp.proposal}\n"
        f"  rationale: {winner.recommendation}\n\n"
        f"runner_up_rationale: a dissenting personality chose '{counter}' instead — "
        f"attack the winner using that as a counter-hypothesis.\n\n"
        f"success_criterion: {inp.proposal}\n\n"
        f"verification: Manual verification by the implementer."
    )
    if inp.context:
        skeptic_input += f"\n\nContext:\n{inp.context}"
    raw = call_voice("skeptic", load_prompt("skeptic"), skeptic_input, inp.model)
    return _parse_skeptic(extract_json(raw), raw)


# ── public entry point ───────────────────────────────────────────────────────

def run_trias_v2(inp: DeliberationInput) -> Report:
    results: list[Report] = asyncio.run(_run_all(inp))

    p_data = [
        {"name": name, "chose": results[i].chosen}
        for i, name in enumerate(PERSONALITIES)
    ]
    candidate_ids = {r.chosen for r in results if r.chosen}
    candidates = [{"id": cid} for cid in candidate_ids]

    vote = _team_vote(p_data, candidates)
    vote_pattern: str = vote["vote_pattern"]
    winner_id: str | None = vote["chosen"]

    # Disagreement scalar — distinct chosen values (None counts as a value).
    disagreement = len({r.chosen for r in results})

    base_conf = _VOTE_CONFIDENCE.get(vote_pattern, 0.3) or 0.3
    confidence = base_conf

    # Per-personality voice outputs.
    voices: list[VoiceOutput] = []
    for name, report in zip(PERSONALITIES, results):
        voices.append(VoiceOutput(
            voice=name,
            vote=_VERDICT_TO_VOTE.get(report.verdict, "MODIFY"),  # type: ignore[arg-type]
            reasoning=report.recommendation,
            concerns=[f"chosen: {report.chosen}"] if report.chosen else [],
            score=report.confidence,
        ))

    # No majority → escalate (nothing decisive to verify).
    if winner_id is None:
        return Report(
            verdict="ESCALATE",
            confidence=round(confidence, 3),
            recommendation=(
                f"[{vote_pattern} vote · disagreement={disagreement}] No majority — "
                "3 personalities chose different approaches. Manual resolution required."
            ),
            voices=voices,
            chosen=None,
            pipeline_executed=True,
            mode="trias_v2",
        )

    winner = next(r for r in results if r.chosen == winner_id)
    verdict = winner.verdict
    recommendation = f"[{vote_pattern} vote · disagreement={disagreement}] {winner.recommendation}"

    # Disagreement-aware aggregation: verify ONLY on a split, capped at 1 pass.
    sk: SkepticObjection | None = None
    if disagreement >= 2 and VERIFICATION_CAP >= 1:
        runner_up = next(
            (r for r in results if r.chosen and r.chosen != winner_id), None
        )
        sk_res, verifier_voice = _verify_winner(winner, runner_up, inp)
        sk = sk_res
        voices.append(verifier_voice)
        # ADVISORY: adjust confidence / caveat, but NEVER change `chosen` or the vote.
        if sk_res.can_object:
            if sk_res.addressable == "unaddressable":
                confidence = min(confidence, 0.40)
                recommendation = (
                    f"[{vote_pattern} vote · disagreement={disagreement} · verified] "
                    f"CAVEAT ({sk_res.failure_mode}): {sk_res.notes} — winner stands (advisory)."
                )
            else:
                confidence = min(confidence, 0.60)
                recommendation = (
                    f"[{vote_pattern} vote · disagreement={disagreement} · verified] "
                    f"{winner.recommendation}  [skeptic flagged: {sk_res.failure_mode}]"
                )

    return Report(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=round(confidence, 3),
        recommendation=recommendation,
        voices=voices,
        chosen=winner_id,  # independence audit: unchanged by verification
        pipeline_executed=True,
        mode="trias_v2",
        skeptic=sk,
    )
