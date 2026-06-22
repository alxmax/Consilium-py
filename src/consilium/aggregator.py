"""Sequential aggregation: raw voice text → Report.

The _run_sequential_scheme() function is adapted from
Consilium skill scripts/aggregator.py (aggregate_sequential).
"""
# implements: CPYBUS-AGG-001
from __future__ import annotations

import statistics
from typing import Any

from consilium.models import DeliberationInput, Report, VoiceOutput
from consilium.voices import extract_json

# ── internal scheme logic (adapted from scripts/aggregator.py) ──────────────

def _sequential_methodology_notes(g: dict, c: dict) -> str:
    notes = []
    if g.get("abstain", {}).get("triggered"):
        notes.append(f"Generator abstain: {g['abstain'].get('reason', '?')}")
    if g.get("challenge_upward", {}).get("triggered"):
        notes.append("Generator challenged Conservator (challenge_upward)")
    if c.get("disagreements"):
        n = len(c["disagreements"])
        notes.append(f"{n} disagreement(s) detected")
    return " | ".join(notes) if notes else "Deliberation completed without anomalies"


def _any_irreversibility_flag(conservator_out: dict) -> tuple[bool, str | None]:
    for s in conservator_out.get("scores") or []:
        if isinstance(s, dict) and s.get("irreversibility_flag"):
            rr = s.get("regression_risk")
            return True, (rr.get("magnitude") if isinstance(rr, dict) else None)
    return False, None


def _chosen_candidate(generator_out: dict, chosen_id: str | None) -> dict:
    """Return the Generator candidate dict matching chosen_id (or {})."""
    if not chosen_id:
        return {}
    options = generator_out.get("options", generator_out.get("candidates", []))
    for opt in options:
        if isinstance(opt, dict) and opt.get("id") == chosen_id:
            return opt
    return {}


def _net_concern_for(conservator_out: dict, cid: str, default: float = 0.15) -> float:
    for s in conservator_out.get("scores") or []:
        if isinstance(s, dict) and s.get("id") == cid:
            rr = s.get("regression_risk")
            if isinstance(rr, dict) and isinstance(rr.get("net_concern"), (int, float)):
                return float(rr["net_concern"])
    return default


def _run_sequential_scheme(
    generator_out: dict,
    control_out: dict,
    conservator_out: dict,
) -> dict[str, Any]:
    triggers: list[str] = []

    if control_out.get("glossary_fail"):
        return {
            "scheme": "sequential",
            "result": "BLOCK",
            "reason": "glossary_fail",
            "attempts": control_out.get("glossary_attempts", []),
            "action": "Reformulate the question using operationally-verifiable terms",
        }

    irrev_flagged, irrev_magnitude = _any_irreversibility_flag(conservator_out)
    if irrev_flagged:
        return {
            "scheme": "sequential",
            "result": "BLOCK",
            "reason": "irreversibility_no_consent",
            "magnitude": irrev_magnitude,
            "action": "Confirm explicitly that this decision is irreversible before proceeding",
        }

    abstain = generator_out.get("abstain") or {}
    if abstain.get("triggered") and abstain.get("reason") == "not_a_proposal":
        return {
            "scheme": "sequential",
            "result": "BLOCK",
            "reason": "not_a_proposal",
            "action": (
                "Not a deliberation input — the input is not a code change or "
                "decision to deliberate. Rephrase it as a concrete proposal "
                "(e.g. 'Add Redis caching to the API')."
            ),
        }

    disagreements = control_out.get("disagreements", [])
    substantial = [d for d in disagreements if isinstance(d, dict) and d.get("type") == "substantial"]
    if substantial:
        triggers.append("substantial_disagreement")

    _scores = conservator_out.get("scores") or []
    _metas = [s.get("meta_recommendation") for s in _scores if isinstance(s, dict) and s.get("meta_recommendation")]
    meta = "scale_up" if "scale_up" in _metas else ("scale_down" if "scale_down" in _metas else None)
    if meta == "scale_down":
        triggers.append("scale_down")
    elif meta == "scale_up":
        triggers.append("scale_up")

    if generator_out.get("abstain", {}).get("triggered"):
        triggers.append("generator_abstain")

    if len(triggers) >= 3:
        return {
            "scheme": "sequential",
            "result": "ESCALATE",
            "triggers": triggers,
            "action": (
                "Multiple critical signals detected simultaneously. "
                "Choose the resolution order:\n"
                + "\n".join(f"  - {t}" for t in triggers)
            ),
        }

    if "substantial_disagreement" in triggers:
        return {
            "scheme": "sequential",
            "result": "REWORK",
            "reason": "substantial_disagreement",
            "disagreements": substantial,
            "action": "Voices show substantial disagreement — clarify before final aggregation",
        }

    if "scale_down" in triggers:
        preferred = generator_out.get("preferred")
        return {
            "scheme": "sequential",
            "result": "ADAPT_SHORT",
            "meta_recommendation": "scale_down",
            "chosen": preferred,
            "action": "Compressed deliberation — short response (max 2 sentences)",
        }

    if "scale_up" in triggers:
        return {
            "scheme": "sequential",
            "result": "ADAPT_EXTENDED",
            "meta_recommendation": "scale_up",
            "action": "Extended deliberation required — ask user for clarification before proceeding",
        }

    preferred = generator_out.get("preferred")
    options = generator_out.get("options", generator_out.get("candidates", []))
    confidence_per_option: dict[str, float] = {}
    for opt in options:
        oid = opt.get("id", "")
        base = 1.0 if oid == preferred else 0.5
        net_concern = _net_concern_for(conservator_out, oid)
        confidence_per_option[oid] = round(base * (1.0 - net_concern), 3)

    methodology_confidence = 1.0
    if "generator_abstain" in triggers:
        methodology_confidence -= 0.3
    if not control_out.get("glossary"):
        methodology_confidence -= 0.1
    if control_out.get("disagreements"):
        methodology_confidence -= 0.05 * len(control_out["disagreements"])
    methodology_confidence = max(0.0, round(methodology_confidence, 2))

    result: dict[str, Any] = {
        "scheme": "sequential",
        "result": "AGGREGATE",
        "chosen": preferred,
        "confidence_per_option": confidence_per_option,
        "confidence_methodology": methodology_confidence,
        "methodology_notes": _sequential_methodology_notes(generator_out, control_out),
    }
    if methodology_confidence < 0.5:
        result["warning"] = "Deliberation incomplete — treat the result as preliminary"
    return result


# ── voice-output → VoiceOutput ───────────────────────────────────────────────

def _extract_voice_output(name: str, voice_out: dict, raw_text: str) -> VoiceOutput:
    reasoning = raw_text[:800]

    if name == "conservator":
        scores = voice_out.get("scores") or []
        net_concerns = [
            float(s["regression_risk"]["net_concern"])
            for s in scores
            if isinstance(s, dict)
            and isinstance(s.get("regression_risk"), dict)
            and isinstance(s["regression_risk"].get("net_concern"), (int, float))
        ]
        avg_concern = statistics.fmean(net_concerns) if net_concerns else 0.15
        any_irrev = any(isinstance(s, dict) and s.get("irreversibility_flag") for s in scores)
        vote: str = "STOP" if any_irrev else ("MODIFY" if avg_concern > 0.6 else "GO")
        score = round(1.0 - avg_concern, 3)
        concerns = [str(s.get("irreversibility_flag")) for s in scores if isinstance(s, dict) and s.get("irreversibility_flag")]

    elif name == "generator":
        abstain = voice_out.get("abstain") or {}
        vote = "STOP" if abstain.get("triggered") else "GO"
        score = 0.8
        concerns = []

    else:  # control
        if voice_out.get("glossary_fail"):
            vote = "STOP"
            score = 0.1
        elif any(
            isinstance(d, dict) and d.get("type") == "substantial"
            for d in voice_out.get("disagreements", [])
        ):
            vote = "MODIFY"
            score = 0.5
        else:
            vote = "GO"
            score = 0.85
        concerns = [
            str(d.get("summary", d))
            for d in voice_out.get("disagreements", [])
            if isinstance(d, dict)
        ]
        # Mandatory dissent (Q5): surface a non-null strongest_objection so the
        # held-back reservation is visible even when the candidate is valid.
        objection = voice_out.get("strongest_objection")
        if objection:
            concerns.append(f"strongest_objection: {objection}")
            if vote == "GO":
                vote = "MODIFY"

    return VoiceOutput(
        voice=name,
        vote=vote,  # type: ignore[arg-type]
        reasoning=reasoning,
        concerns=concerns,
        score=score,
    )


# ── public entry point ───────────────────────────────────────────────────────

_RESULT_TO_VERDICT = {
    "BLOCK": "BLOCK",
    "REWORK": "MODIFY",
    "ESCALATE": "ESCALATE",
    "ADAPT_SHORT": "GO",
    "ADAPT_EXTENDED": "MODIFY",
}


def aggregate_sequential(
    cons_text: str,
    gen_text: str,
    ctrl_text: str,
    _inp: DeliberationInput,
) -> Report:
    """Parse raw voice text outputs and aggregate into a Report."""
    cons_out = extract_json(cons_text)
    gen_out = extract_json(gen_text)
    ctrl_out = extract_json(ctrl_text)

    agg = _run_sequential_scheme(gen_out, ctrl_out, cons_out)

    scheme_result: str = agg.get("result", "AGGREGATE")
    if scheme_result == "AGGREGATE":
        confidence = float(agg.get("confidence_methodology", 0.5))
        verdict = "GO" if confidence >= 0.7 else ("MODIFY" if confidence >= 0.4 else "STOP")
        recommendation = agg.get("methodology_notes", "Deliberation complete")
    else:
        verdict = _RESULT_TO_VERDICT.get(scheme_result, "MODIFY")
        # Bypass verdicts (BLOCK, REWORK, ESCALATE) carry a categorical low
        # confidence (CPYBUS-AGG-001). Test scheme_result, not verdict, because
        # REWORK is mapped to MODIFY above and would otherwise leak 0.5.
        confidence = 0.1 if scheme_result in ("BLOCK", "REWORK", "ESCALATE") else 0.5
        recommendation = agg.get("action", f"Result: {scheme_result}")

    voices = [
        _extract_voice_output("conservator", cons_out, cons_text),
        _extract_voice_output("generator", gen_out, gen_text),
        _extract_voice_output("control", ctrl_out, ctrl_text),
    ]

    chosen = agg.get("chosen")
    candidate = _chosen_candidate(gen_out, chosen)

    # description is the fixture/legacy field name; sketch is the prompt's field.
    sketch = candidate.get("sketch") or candidate.get("description")

    return Report(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=round(confidence, 3),
        recommendation=recommendation,
        voices=voices,
        chosen=chosen,
        chosen_summary=candidate.get("summary"),
        chosen_sketch=sketch,
        chosen_rationale=candidate.get("rationale"),
        reason=agg.get("reason"),
        pipeline_executed=True,
        mode="sequential",
    )
