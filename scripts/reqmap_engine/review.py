"""`ask --review`: the JSON review plan."""
import json

from . import MAP_ENGINE_VERSION
from .lintrules import _count_ac
from .sections import ACCEPTANCE_LABELS, CONTRACT_LABELS, _from_any
from .text import _bullets, _first_quote, _title


def cmd_review(reqs, one_id=None):  # implements: ARCH-REVIEW-022  # implements: REQ-REVIEW-906
    """Emit a DETERMINISTIC, read-only review PLAN as JSON for an out-of-band AI quality
    pass. The engine never calls an LLM and writes no file — it gathers each requirement's
    prose (WHY/contract/acceptance/verify-intent) plus cheap STRUCTURAL anchors the AI
    consumer should focus on, a corpus coverage_summary, and the finding contract. The plan
    is byte-reproducible across runs; the AI findings DERIVED from it are advisory and NOT
    reproducible, and no gate path reads this output or any AI sidecar."""
    if one_id and one_id not in reqs:
        print("no requirement with id {} (expected requirements/{}.md)".format(one_id, one_id))
        return 1
    ids = [one_id] if one_id else sorted(reqs)
    items = []
    for rid in ids:
        r = reqs.get(rid)
        if not r:
            continue
        body = r["body"]
        contract = _from_any(_bullets, body, CONTRACT_LABELS)
        intent = _first_quote(body)
        ac_n = _count_ac(body)
        intent_words = len(intent.split())
        items.append({
            "id": rid,
            "title": _title(body),
            "layer": r["meta"].get("layer", "feature"),
            "status": r["meta"].get("status", "draft"),
            "intent": intent,
            "contract": contract,
            "acceptance": _from_any(_bullets, body, ACCEPTANCE_LABELS),
            "verify_intent": _bullets(body, "verify"),
            # cheap STRUCTURAL anchors (deterministic facts, NOT judgments) the AI examines:
            "anchors": {
                "contract_clauses": len(contract),
                "acceptance_count": ac_n,
                "intent_words": intent_words,
                # WHY may merely restate the title
                "intent_terse": intent_words < 12,
                "more_contract_than_acceptance": len(contract) > ac_n,  # a clause may be uncovered
            },
        })
    plan = {
        "engine_version": MAP_ENGINE_VERSION,
        "advisory": ("DETERMINISTIC read-only review plan. AI findings derived from it are "
                     "ADVISORY and NON-reproducible; they are never part of the gate and "
                     "never auto-applied."),
        "categories": [
            {"key": "untestable-contract",
             "desc": "a contract clause so vague it cannot be verified"},
            {"key": "why-restates-title",
             "desc": "the WHY restates the title instead of explaining why it exists"},
            {"key": "acceptance-doesnt-cover-contract",
             "desc": "a contract clause with no acceptance criterion exercising it"},
        ],
        "finding_contract": ("every AI finding MUST carry a concrete suggested_rewrite; "
                             "emit only high-confidence findings; severity is "
                             "advisory-only (never error/warn, never the gate)."),
        "coverage_summary": {"total_requirements": len(reqs), "requirements_in_plan": len(items)},
        "requirements": items,
    }
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0
