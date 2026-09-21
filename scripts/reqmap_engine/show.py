"""`gate --show`: one requirement's consolidated dossier."""
import json

from .model import RISK_ADVICE, _as_list
from .risk import _risk_signals
from .sections import CONTRACT_LABELS, _from_any
from .text import _bullets, _distinct_intent, _req_title, _verify_bullets


def show_record(ws, cap_id, levels=None):
    # implements: ARCH-SHOW-015  # implements: ARCH-VLEVEL-037  # implements: REQ-SHOW-917
    # implements: REQ-SHOW-918  # implements: REQ-SHOW-919  # implements: REQ-TRACE-935
    # implements: REQ-VLEVEL-946
    """The dossier as data, or None for an unknown id: what `gate --show` prints, plus the
    requirement's frontmatter and body for a reader that wants the whole file."""
    reqs, members = ws.reqs, ws.members
    r = reqs.get(cap_id)
    if not r:
        return None
    m, body = r["meta"], r["body"]
    # {(file, line): level} for this requirement, so a levelled tested-by link shows the
    # level it asserts rather than leaving the reader to open the file.
    at = {}
    for lvl, hits in (levels or {}).get(cap_id, {}).items():
        for hit in hits:
            at[hit] = lvl
    mem = members.get(cap_id, [])
    node = {"status": m.get("status", "draft"), "layer": m.get("layer", "feature"),
            "members": mem, "verify": _verify_bullets(body), "test_exempt": m.get("test_exempt")}
    return {
        "id": cap_id, "status": m.get("status", "draft"), "layer": m.get("layer", "?"),
        "priority": m.get("priority"), "milestone": m.get("milestone"),
        "title": _req_title(body, cap_id),
        "intent": _distinct_intent(body),   # "" when it would just repeat the Contract
        "contract": _from_any(_bullets, body, CONTRACT_LABELS),
        "depends_on": _as_list(m.get("depends_on")),
        "depended_on_by": sorted(rid for rid, rr in reqs.items()
                                 if cap_id in _as_list(rr["meta"].get("depends_on"))),
        # implements: ARCH-TRACE-020
        "satisfies": _as_list(m.get("satisfies")),
        "satisfied_by": sorted(rid for rid, rr in reqs.items()
                               if cap_id in _as_list(rr["meta"].get("satisfies"))),
        "members": [{"role": role, "file": fp, "line": ln, "level": at.get((fp, ln))}
                    for role, fp, ln in sorted(mem)],
        "open_verify": [b for b in _verify_bullets(body)
                        if b and not b.lstrip("*_ ").lower().startswith("none")],
        "risk": [{"signal": s, "advice": RISK_ADVICE[s]} for s in _risk_signals(node)],
        "path": r.get("path"), "frontmatter": m, "body": body,
    }


def _print_show(rec):  # implements: REQ-SHOW-917  # implements: REQ-SHOW-918
    """The human-readable dossier, printed from the record."""
    head = "{} · {} · {}".format(rec["id"], rec["status"], rec["layer"])
    for extra in (rec["priority"], rec["milestone"]):
        head += " · " + extra if extra else ""
    print(head)
    print(rec["title"])
    if rec["intent"]:
        print("  " + rec["intent"])
    print("\nContract:")
    for b in rec["contract"]:
        print("  - " + b)
    if not rec["contract"]:
        print("  (none — no '## Description' section)")
    print("\nDepends on: " + (", ".join(rec["depends_on"]) or "(none)"))
    print("Depended on by: " + (", ".join(rec["depended_on_by"]) or "(none)"))
    # upstream traceability: only shown when the requirement participates in it,
    # so requirements that don't use `satisfies` get no extra noise.
    if rec["satisfies"] or rec["satisfied_by"]:
        print("Satisfies (upstream): " + (", ".join(rec["satisfies"]) or "(none)"))
        print("Satisfied by: " + (", ".join(rec["satisfied_by"]) or "(none)"))
    print("\nMembers in code ({}):".format(len(rec["members"])))
    for mb in rec["members"]:
        print("  {:18} {}:{}{}".format(mb["role"], mb["file"], mb["line"],
                                      " @" + mb["level"] if mb["level"] else ""))
    if not rec["members"]:
        print("  (none tagged)")
    if rec["open_verify"]:
        print("\nOpen verify-intent:")
        for b in rec["open_verify"]:
            print("  - " + b)
    if rec["risk"]:
        print("\nRisk signals:")
        for s in rec["risk"]:
            print("  [{}] {}".format(s["signal"], s["advice"]))
    print("\n{}".format(rec["path"]))


def cmd_show(ws, cap_id, levels=None, as_json=False):
    # implements: ARCH-SHOW-015  # implements: REQ-SHOW-919
    """Print one consolidated dossier for a single requirement: its status/layer/intent,
    contract, dependencies (both directions), members grouped by role, open verify-intent
    questions, and risk signals — the 'what does this do / where is X' view in one
    command. Read-only; returns 1 on an unknown id so a typo is visible to a caller or CI.
    `as_json` prints the record, or `{"error": ...}` for an unknown id."""
    rec = show_record(ws, cap_id, levels)
    if rec is None:
        msg = "no requirement with id {} (expected requirements/{}.md)".format(cap_id, cap_id)
        print(json.dumps({"id": cap_id, "error": msg}) if as_json else msg)
        return 1
    if as_json:
        print(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    else:
        _print_show(rec)
    return 0
