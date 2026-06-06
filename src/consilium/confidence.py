"""Derive report confidence from voice-score variance.

Adapted from Consilium skill scripts/confidence.py (stdlib logic only).
"""
from __future__ import annotations

import statistics

VOICES = ("generator", "control", "conservator")
MAX_STDEV_3VALS = (2 / 9) ** 0.5
AGREEMENT_WEIGHT = 0.7
SEPARATION_WEIGHT = 0.3
CONFIDENCE_FLOOR = 0.05
CONFIDENCE_CEIL = 0.99


def _utility_vec(scores: dict) -> list[float]:
    return [
        float(scores["generator"]),
        float(scores["control"]),
        1.0 - float(scores["conservator"]),
    ]


def _utility(scores: dict) -> float:
    return statistics.fmean(_utility_vec(scores))


def _spread(scores: dict) -> float:
    return statistics.pstdev(_utility_vec(scores))


def derive(candidates: list[dict], chosen: str | None) -> dict:
    if chosen is None:
        return {"confidence": None, "reason": "no chosen candidate"}

    by_id = {c["id"]: c for c in candidates}
    if chosen not in by_id:
        return {"confidence": None, "reason": f"chosen={chosen!r} not in candidates"}

    chosen_c = by_id[chosen]
    agreement = 1.0 - (_spread(chosen_c["scores"]) / MAX_STDEV_3VALS)
    agreement = max(0.0, min(1.0, agreement))

    others = [c for c in candidates if c["id"] != chosen]
    if others:
        chosen_u = _utility(chosen_c["scores"])
        runner_up_u = max(_utility(c["scores"]) for c in others)
        separation = max(0.0, chosen_u - runner_up_u)
    else:
        separation = 1.0

    raw = AGREEMENT_WEIGHT * agreement + SEPARATION_WEIGHT * separation
    confidence = max(CONFIDENCE_FLOOR, min(CONFIDENCE_CEIL, raw))

    return {
        "confidence": round(confidence, 3),
        "agreement": round(agreement, 3),
        "separation": round(separation, 3),
    }
