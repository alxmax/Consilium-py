"""`gate --risk` / `next`: risk score and the counted, actionable buckets."""
import json, os

from . import config as cfg
from .lintrules import _count_ac, _oversize
from .model import ENFORCED, RISK_ADVICE, _as_list, _impl_exempt
from .orphans import _scan_untagged
from .plandrift import unplanned_items
from .similar import _redundant_groups
from .targets import load_targets
from .text import _req_file, _verify_bullets


def _risk_score(meta):  # implements: ARCH-NEXT-013  # implements: REQ-NEXT-885
    """Extract's per-file risk hint (0-3) from frontmatter, or 0 when absent /
    unparseable. Used only to float REVIEW-flagged drafts to the top of a bucket —
    never to gate. Hand-authored requirements have no `risk:` field -> 0."""
    try:
        return int(str(meta.get("risk")).strip())
    except (TypeError, ValueError):
        return 0


_PRIORITY_ORDER = {"must-have": 0, "should-have": 1, "could-have": 2, "wont-have": 3}


def _recorded_members(reqs_dir, ids):  # implements: ARCH-NEXT-013
    """{id: first member loc} from the committed `_map.json`, for those of `ids` whose
    node records a member there. The narrow default scan (no --code) cannot see a
    member outside its root, so a requirement lands in Orphans while the committed
    map proves it has code — this is what turns that into a hint instead of a
    puzzle. Fail-open ({}) when the map is absent or unreadable."""
    try:
        with open(os.path.join(reqs_dir, "_map.json"), encoding="utf-8") as f:
            nodes = json.load(f).get("nodes", [])
    except (OSError, ValueError):
        return {}
    want, out = set(ids), {}
    for n in nodes:
        mem = n.get("members") or []
        if n.get("id") in want and mem and isinstance(mem[0], dict):
            out[n["id"]] = mem[0].get("loc", "")
    return out


def _plan_gaps(reqs, code_root, reqs_dir):
    # implements: ARCH-NEXT-013  # implements: REQ-PLANGAPS-1033
    """The horizon work `next` names beside the corpus buckets, as (kind, text) pairs:
    open `Now`/`Next` items no bar schedules, open `Later` items with no `unpark:`, and
    items naming a `req:` the corpus does not hold.

    Empty — never a complaint — when the repo keeps no `ROADMAP.md`, which is most of
    them. These three already existed as one line each in `sync` and `gate --audit`;
    what they answer is "what is next", so they belong on the screen that asks it.
    Nothing here reads the code, so the whole thing costs one small file read."""
    # Imported at call time, not at the top: `mapdata` reads `_risk_signals` from this
    # module, so a module-level import would close the cycle. The engine's second
    # documented one, after `health._link_sync_errors` -> `rules`.
    from .mapdata import _read_roadmap, _roadmap_plan_gaps
    items = _read_roadmap(code_root) if code_root else None
    if not items:
        return []
    bars = load_targets(reqs_dir).get("bars", []) if reqs_dir else []
    missing, parked = _roadmap_plan_gaps(items, reqs)
    gaps = [("no bar", it["name"]) for it in unplanned_items(items, bars)]
    gaps += [("{} missing".format(it["req"]), it["name"]) for it in missing]
    gaps += [("no `unpark:`", it["name"]) for it in parked]
    return gaps


def _print_plan_bucket(gaps, show_all, top_n):
    # implements: ARCH-NEXT-013  # implements: REQ-PLANGAPS-1033
    """Print the Plan bucket and its advice."""
    print("Plan ({})".format(len(gaps)))
    for kind, name in (gaps if show_all else gaps[:top_n]):
        print("  {:<16} {}".format(kind, name[:70] + ("..." if len(name) > 70 else "")))
    if not show_all and len(gaps) > top_n:
        print("  ... {} more — run `reqmap.py gate --risk --all`".format(len(gaps) - top_n))
    print("  -> The plan and the corpus disagree. Give a `Now`/`Next` item dates in "
          "`_planning.json`, an `unpark:` condition to a `Later` one, or point a `req:` "
          "at a requirement that exists.\n")


def _next_pending(reqs, members, code_root, reqs_dir):
    # implements: ARCH-NEXT-013  # implements: REQ-NEXT-883
    """Everything `next` has to say about the corpus, before a word of it is
    formatted: the headline counts, the risk buckets in priority order, the
    untagged files, the two corpus-shape advisories and the plan's own gaps.
    Returns None when the corpus is empty, which the caller reports differently
    from a clean one."""
    total = len(reqs)
    if total == 0:   # distinguish "nothing set up yet" from "all clean"
        print("No requirements yet. Run `reqmap.py init` to bootstrap from existing "
              "code, or write requirements/AREA-NAME-NNN.md to author one.")
        return None
    confirmed = sum(1 for r in reqs.values() if r["meta"].get("status") == "confirmed")
    tested = sum(1 for rid in reqs if any(role == "tested-by" for role, *_ in members.get(rid, [])))
    # `unreviewed` = draft + baseline, the same population the "Drafts to review" bucket
    # holds; the header used to count `draft` only and disagree with the bucket beneath it.
    unreviewed = sum(1 for r in reqs.values()
                     if r["meta"].get("status", "draft") in ("draft", "baseline"))
    print("{} requirement(s) · {} confirmed · {} tested · {} unreviewed\n".format(
        total, confirmed, tested, unreviewed))

    dependents = {rid: 0 for rid in reqs}
    for rid, r in reqs.items():
        for dep in _as_list(r["meta"].get("depends_on")):
            if dep in dependents:
                dependents[dep] += 1
    buckets = {}  # signal -> [(rid, risk_score)]
    for rid, r in reqs.items():
        m = r["meta"]
        node = {"status": m.get("status", "draft"), "layer": m.get("layer", "feature"),
                "members": members.get(rid, []),
                "verify": _verify_bullets(r["body"]), "test_exempt": m.get("test_exempt")}
        for sig in _risk_signals(node):
            buckets.setdefault(sig, []).append((rid, _risk_score(m)))
    # Action buckets, MOST-URGENT FIRST: an unimplemented contract outranks an
    # unreviewed draft. Each bucket is shown and truncated
    # independently, so a high-priority bucket is never hidden below a long low one.
    PLAN = [
        ("unimplemented",     "Orphans (confirmed, no code)"),
        ("untested",          "Needs tests"),
        ("unverified-intent", "Needs intent review"),
        ("unreviewed",        "Drafts to review"),
    ]
    def _priority_ord(rid):
        p = reqs[rid]["meta"].get("priority", "")
        return _PRIORITY_ORDER.get(p, 99)

    pending = [(sig, label, sorted(buckets[sig], key=lambda x: (_priority_ord(x[0]), -x[1], x[0])))
               for sig, label in PLAN if buckets.get(sig)]
    untagged = _scan_untagged(code_root, reqs_dir) if code_root else []
    # Granularity advisory: requirements with many ACs covering disjoint behaviors.
    # Shares `_oversize` with lint's `ac-count-high` check (same threshold, same
    # LINT_STATUSES scoping, same `lint_exempt` honoring) so `next` and `lint`
    # can never report a different set for the same corpus.
    oversize = sorted(
        [(rid, _count_ac(r["body"]))
         for rid, r in reqs.items()
         if _oversize(rid, r)],
        key=lambda x: (-x[1], x[0])
    )
    # The other direction of the same concern: covering the code with FEWER requirements.
    # Granularity above says "this one does too much"; this says "these say the same thing".
    redundant = _redundant_groups(reqs)
    # The horizon, read from the plan files rather than from the corpus: work the
    # ROADMAP says is open and the plan does not schedule. implements: REQ-PLANGAPS-1033
    gaps = _plan_gaps(reqs, code_root, reqs_dir)
    return (total, confirmed, tested, unreviewed, pending, untagged,
            oversize, redundant, gaps)

def _print_pending_bucket(sig, label, ids, reqs_dir, disp):
    # implements: ARCH-NEXT-013  # implements: REQ-NEXT-883  # implements: REQ-NEXT-884
    # implements: REQ-NEXT-885  # implements: REQ-NEXT-886  # implements: REQ-NEXT-887
    """Print one risk bucket's requirement list and advice, plus (for
    'unimplemented') the committed-map cross-scan-root hint. `disp` is the shared
    (reqs, show_all, top_n) display context every bucket printer takes."""
    reqs, show_all, top_n = disp
    print("{} ({})".format(label, len(ids)))
    shown = ids if show_all else ids[:top_n]
    for rid, score in shown:
        flag = "  [REVIEW]" if score >= 2 else ""
        print("  {}{}   {}".format(rid, flag, _req_file(reqs, rid)))
    if not show_all and len(ids) > top_n:
        print("  ... {} more — run `reqmap.py gate --risk --all`".format(len(ids) - top_n))
    print("  -> {}\n".format(RISK_ADVICE[sig]))
    if sig == "unimplemented" and reqs_dir:
        recorded = _recorded_members(reqs_dir, [rid for rid, _ in ids])
        if recorded:
            rid0 = sorted(recorded)[0]
            print(("  note: the committed _map.json records member(s) for {} of these "
                   "(e.g. {} <- {}) that this scan did not reach — if they live outside "
                   "the scan root, re-run with `--code <dir>`.\n")
                  .format(len(recorded), rid0, recorded[rid0]))


def _print_untagged_bucket(untagged, show_all, top_n):
    # implements: ARCH-NEXT-013  # implements: REQ-NEXT-883  # implements: REQ-NEXT-884
    # implements: REQ-NEXT-885  # implements: REQ-NEXT-886  # implements: REQ-NEXT-887
    """Print the Untagged files bucket and its advice."""
    shown_u = untagged if show_all else untagged[:top_n]
    print("Untagged files ({})".format(len(untagged)))
    for fp in shown_u:
        print("  {}".format(fp))
    if not show_all and len(untagged) > top_n:
        print("  ... {} more — run `reqmap.py gate --risk --all`"
              .format(len(untagged) - top_n))
    print("  -> Run `reqmap.py init` to auto-extract requirements, "
          "or add to .reqmapignore to silence.\n")


def _print_oversize_bucket(oversize, disp):
    # implements: ARCH-NEXT-013  # implements: REQ-NEXT-883  # implements: REQ-NEXT-884
    # implements: REQ-NEXT-885  # implements: REQ-NEXT-886  # implements: REQ-NEXT-887
    """Print the Granularity bucket and its advice."""
    reqs, show_all, top_n = disp
    print("Granularity ({})".format(len(oversize)))
    shown_o = oversize if show_all else oversize[:top_n]
    for rid, n in shown_o:
        print("  {}   ({} ACs) — consider splitting   {}".format(
            rid, n, _req_file(reqs, rid)))
    if not show_all and len(oversize) > top_n:
        print("  ... {} more — run `reqmap.py gate --risk --all`"
              .format(len(oversize) - top_n))
    print(
        "  -> A requirement with more than {} acceptance criteria covering disjoint "
        "behaviors is a split candidate. Author two requirements, each with its own "
        "contract.\n"
        .format(cfg.LINT_AC_MAX)
    )


def _print_redundant_bucket(redundant, disp):
    # implements: ARCH-NEXT-013  # implements: REQ-NEXT-883  # implements: REQ-NEXT-884
    # implements: REQ-NEXT-885  # implements: REQ-NEXT-886  # implements: REQ-NEXT-887
    """Print the Redundancy bucket and its advice."""
    reqs, show_all, top_n = disp
    spare = sum(len(g) - 1 for g in redundant)
    print("Redundancy ({})".format(len(redundant)))
    shown_r = redundant if show_all else redundant[:top_n]
    for g in shown_r:
        print("  {}   identical contract   {}".format(", ".join(g), _req_file(reqs, g[0])))
    if not show_all and len(redundant) > top_n:
        print("  ... {} more — run `reqmap.py gate --risk --all`"
              .format(len(redundant) - top_n))
    print(
        "  -> {} requirement(s) state an obligation another already states, word for "
        "word. Fold each group into one and re-point the tags, or make the contracts "
        "say different things. Exact matches only — run `reqmap.py ask --dupes` for the "
        "near-matches this cannot see.\n".format(spare)
    )


def cmd_next(ws, show_all=False, top_n=3):
    # implements: ARCH-NEXT-013  # implements: REQ-NEXT-883  # implements: REQ-NEXT-884
    # implements: REQ-NEXT-885  # implements: REQ-NEXT-886  # implements: REQ-NEXT-887
    """Terminal 'what should I do next': a focused, counted worklist over the same
    `_risk_signals` + `RISK_ADVICE` that drive the Risk tab. Prints a progress
    header, leads with the most-urgent bucket, shows the top few per bucket (the
    extract REVIEW-flagged ones first), and collapses the rest behind --all. Each
    item names the requirement file to open. Also surfaces scannable files that
    carry no membership tag (untagged bucket) and, last, the gaps in the plan
    itself (Plan bucket). Read-only, always exit 0."""
    reqs, members, reqs_dir, code_root = ws.reqs, ws.members, ws.reqs_dir, ws.code_root
    found = _next_pending(reqs, members, code_root, reqs_dir)
    if found is None:
        return 0
    (total, confirmed, tested, unreviewed, pending, untagged,
     oversize, redundant, gaps) = found
    # Computed BEFORE the early return: Granularity/Redundancy are their own findings, not
    # a footnote on the four risk buckets above — a corpus clean on every bucket but still
    # carrying an oversize or redundant requirement is NOT "nothing pending". The plan's
    # gaps join them for the same reason: a corpus in perfect order whose ROADMAP still
    # carries unscheduled work has something to do. implements: REQ-PLANGAPS-1033
    if not pending and not untagged and not oversize and not redundant and not gaps:
        print("Nothing pending — every confirmed requirement is implemented, tested and "
              "intent-checked.")
        return 0
    if pending:
        total_actions = sum(len(ids) for _, _, ids in pending)
        n_cat = (len(pending) + bool(untagged) + bool(oversize) + bool(redundant)
                 + bool(gaps))
        print("{} item(s) need attention across {} {}:\n".format(
            total_actions, n_cat, "category" if n_cat == 1 else "categories"))
    disp = (reqs, show_all, top_n)
    for sig, label, ids in pending:
        _print_pending_bucket(sig, label, ids, reqs_dir, disp)
    if untagged:
        _print_untagged_bucket(untagged, show_all, top_n)
    if oversize:
        _print_oversize_bucket(oversize, disp)
    if redundant:
        _print_redundant_bucket(redundant, disp)
    if gaps:
        _print_plan_bucket(gaps, show_all, top_n)
    return 0


def _member_roles(members):
    """Roles of a node's members, tolerant of both member shapes in play: the raw
    scan tuples (role, file, line) used by cmd_check and the {role, loc}
    dicts attached to map data nodes."""
    roles = []
    for m in members or []:
        if isinstance(m, dict):
            roles.append(m.get("role"))
        elif isinstance(m, (list, tuple)) and m:
            roles.append(m[0])
    return roles


def _risk_signals(node):
    signals = []
    # 'unimplemented' must mirror the gate, which errors when an ENFORCED requirement
    # has no `implements:` member (a `tested-by`-only member must not satisfy it).
    # Keying on the implements ROLE (not raw member-list emptiness) keeps next/show/
    # the Risk map agreeing with `check`. A `layer: need` is satisfied-by other
    # requirements, not implemented by code, so the gate exempts it (ARCH-TRACE-020) —
    # mirror that here, else the Risk/Problems views flag a passing gate as failing.
    roles = _member_roles(node.get("members"))
    if node["status"] in ENFORCED and "implements" not in roles and not _impl_exempt(node):
        signals.append("unimplemented")
    if node["status"] in ("draft", "baseline"):
        signals.append("unreviewed")
    # implemented-but-untested: has hand-written code linked but no acceptance test.
    # Gated on an implements member so not-yet-built drafts (already 'unreviewed')
    # are not double-flagged. Opt out per requirement with `test_exempt: <reason>`.
    if "implements" in roles and "tested-by" not in roles and not node.get("test_exempt"):
        signals.append("untested")
    # open verify-intent questions reconstructed from code — surface them on the map,
    # not just in the detail panel / _findings.md. Mirror collect_findings: a "None —"
    # placeholder bullet is not an open finding. A *draft* is suppressed here: its
    # intent questions are subsumed by 'unreviewed' (the whole draft is unreviewed),
    # and every auto-extracted draft carries a template verify TODO — flagging both
    # would double-count every draft. Re-surfaces once promoted past draft. This
    # rule lives in the shared signal source so `next` and the Risk tab agree.
    if node["status"] != "draft" and any(
            b and not b.lstrip("*_ ").lower().startswith("none")
            for b in (node.get("verify") or [])):
        signals.append("unverified-intent")
    return signals
