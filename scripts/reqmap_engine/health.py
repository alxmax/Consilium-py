"""`health` and `coverage`: the corpus coherence score and the acceptance-coverage table."""
import json, os

from .design_report import _design_summary
from .git import _git
from .locks import load_lock
from .mapdata import _roadmap_behind, _roadmap_signals
from .model import _as_list, _impl_exempt, gate_rule_by_id
from .orphans import _scan_untagged, untaggable_by_design
from .risk import _member_roles, _plan_gaps
from .scan import _walk_code
from .sections import binding_hash
from .versions import stale_plan_milestones, version_alignment_lines
from .text import _verify_bullets


def _link_sync_errors(reqs, members):  # implements: ARCH-HEALTH-017  # implements: REQ-RULES-947
    """`gate`'s ERROR-level link-sync problems (dangling tags, enforced requirements
    with no `implements:` member) as message strings, for `health` — the same two
    rules the gate runs (RM001, RM006), read from the registry so the two commands
    cannot drift apart again (RM-6 / Senate run reqmap-health-gate-cleanliness)."""
    # Imported here, not at the top: the gate's map-freshness rule embeds this
    # record (mapcmd -> health), and health runs two gate rules — mutual by design.
    from . import rules  # noqa: F401 - registers RM001/RM006 in GATE_RULES
    from .workspace import GateContext
    ctx = GateContext.__new__(GateContext)
    ctx.reqs, ctx.members, ctx.full_members = reqs, members, members
    ctx.cap_ids, ctx.since = set(reqs), None
    # honour `gate_exempt:` exactly as run_gate_rules does, or a requirement the gate
    # passes still counts as a link-sync error in `health` and the committed map
    return [msg for rule_id in ("RM001", "RM006")
            for rid, msg in gate_rule_by_id(rule_id).fn(ctx)
            if rid is None or not ctx.req(rid).exempt_from(rule_id)]


def cmd_coverage(ws, as_json=False):
    """Per-directory coverage report: how many scannable files in each top-level
    directory carry at least one membership tag vs. total scannable files.
    Helps identify which parts of the codebase have no requirement coverage."""
    members, reqs_dir, code_root = ws.members, ws.reqs_dir, ws.code_root
    # requirements dir holds spec files, not implementation files — excluded from coverage.
    # `_walk_files` already prunes it by realpath; this abspath test also catches an SSOT
    # dir reached through a symlink.
    reqs_abs = os.path.normcase(os.path.abspath(reqs_dir)) if reqs_dir else None
    tagged_files = set()
    for mlist in members.values():
        for _role, fp, _ln in mlist:
            tagged_files.add(os.path.normcase(os.path.abspath(os.path.join(code_root, fp))))

    buckets = {}  # dir_label -> [total, tagged]
    by_design = 0
    for fp, rel in _walk_code(code_root, reqs_dir):
        norm_fp = os.path.normcase(os.path.abspath(fp))
        if reqs_abs and norm_fp.startswith(reqs_abs + os.sep):
            continue
        # implements: REQ-UNTAGGEDSET-1007 — the same exclusion the "Untagged files"
        # bucket applies. Counting a file that will never carry a tag put the ratio's
        # ceiling below 100% and named no file the author could act on.
        if untaggable_by_design(rel):
            by_design += 1
            continue
        # Group by first path component (top-level directory or "." for root files)
        parts = rel.split("/")
        label = parts[0] if len(parts) > 1 else "."
        if label not in buckets:
            buckets[label] = [0, 0]
        buckets[label][0] += 1
        if norm_fp in tagged_files:
            buckets[label][1] += 1

    rows = []
    for label in sorted(buckets):
        total, tagged = buckets[label]
        pct = round(100 * tagged / total) if total else 0
        rows.append({"dir": label, "total": total, "tagged": tagged, "pct": pct})

    if as_json:
        print(json.dumps({"rows": rows, "excluded_by_design": by_design}, indent=2))
        return 0

    if not rows:
        print("No scannable files found.")
        return 0

    w = max(len(r["dir"]) for r in rows)
    for r in rows:
        bar = "#" * (r["pct"] // 5) + "." * (20 - r["pct"] // 5)
        print("{:<{w}}  {:>3}/{:<3}  ({:>3}%)  [{}]".format(
            r["dir"], r["tagged"], r["total"], r["pct"], bar, w=w))
    total_all = sum(r["total"] for r in rows)
    tagged_all = sum(r["tagged"] for r in rows)
    pct_all = round(100 * tagged_all / total_all) if total_all else 0
    print("\nTotal: {}/{} files tagged ({:>3}%)".format(tagged_all, total_all, pct_all))
    if by_design:
        print("({} file(s) excluded: they carry no tag by contract — decision records, "
              "CHANGELOG, LICENSE, issue templates. `gate --risk` skips the same set, so "
              "both reports name one list.)".format(by_design))
    return 0


def _commits_since_reqs_touch(code_root, reqs_dir):
    # implements: ARCH-REGISTRYLAG-035  # implements: REQ-REGISTRYLAG-903
    """Count commits on HEAD since the last commit that touched `reqs_dir`.

    The advisory "registry lag" signal: a large number means the registry has
    sat frozen while code raced ahead of it — the exact 18-day-freeze condition
    that let a money value drift with no requirement update. Returns None (not 0)
    when unmeasurable — git missing, `code_root` not a git worktree, or `reqs_dir`
    has no commit in history — so the reading is absent rather than falsely 0.
    Read-only; never a gate, never enters the score."""
    # reqs_dir must resolve against the CALLER's cwd, not against code_root — `git -C
    # code_root` changes where the pathspec is resolved, so a relative reqs_dir (e.g.
    # `--code ..` from `plugin/`) would silently look for `../requirements` instead of
    # `../plugin/requirements`. Mirrors the abspath(p) pattern `untracked_locks` already
    # uses for the same reason (ARCH-CHECK-006).
    sha = (_git(["-C", code_root, "log", "-1", "--format=%H", "--", os.path.abspath(reqs_dir)],
                timeout=5) or "").strip()
    if not sha:
        return None
    cnt = _git(["-C", code_root, "rev-list", "--count", "{}..HEAD".format(sha)], timeout=5)
    try:
        return int((cnt or "").strip())
    except ValueError:
        return None


def _requirement_health_flags(rid, r, members, lock, satisfied):
    # implements: ARCH-HEALTH-017  # implements: REQ-HEALTH-968
    """The per-requirement booleans `_health_record`'s loop aggregates into counters."""
    m, body = r["meta"], r["body"]
    status = m.get("status", "draft")
    roles = _member_roles(members.get(rid, []))
    has_impl = "implements" in roles
    # a need is covered by being satisfied, not implemented, and its test
    # axis is waived — a need is fulfilled by requirements, not by code.
    # An aggregate is covered the same way, downward: by its depends_on edges.
    is_need = m.get("layer") == "need"
    covered = has_impl
    if is_need:
        covered = rid in satisfied
    elif _impl_exempt(m):                     # aggregate: covered by its dependencies
        covered = bool(_as_list(m.get("depends_on")))
    has_test_member = "tested-by" in roles
    has_test = has_test_member or bool(m.get("test_exempt"))
    is_confirmed = status == "confirmed"
    open_now = status != "draft" and any(
        b and not b.lstrip("*_ ").lower().startswith("none")
        for b in _verify_bullets(body))
    old = lock.get(rid)
    is_drifted = bool(old) and old != binding_hash(body) and is_confirmed
    return {"status": status, "has_impl": has_impl, "has_test_member": has_test_member,
            "test_exempt": bool(m.get("test_exempt")), "has_test": has_test,
            "is_confirmed": is_confirmed, "covered": covered, "open_now": open_now,
            "is_drifted": is_drifted, "impl_exempt": _impl_exempt(m)}


def _reviewed_score(confirmed, drafts, healthy):
    # implements: ARCH-HEALTH-017  # implements: REQ-HEALTH-968
    """The reviewed-subset score (REQ-REVIEWEDSCORE-109) and its denominator, or
    (None, confirmed) when there is nothing for it to add."""
    # Reviewed-subset score (read-only, ADDITIVE). `score` counts every requirement,
    # and a `draft` can never be green because the first axis is status `confirmed` —
    # so each draft caps `score` by construction until someone confirms it. That makes
    # the headline unable to tell "rotting" from "not reviewed yet": a repo that runs
    # `init` over legacy code gets hundreds of drafts and a near-zero score that no
    # amount of care moves. This second number scores only the reviewed part, so the
    # two readings are separable. `score` itself is NOT redefined — CASE-2 binds an
    # all-draft corpus to zero, and every consumer badge already reads `score`.
    # Absent (not zero) when nothing has been reviewed, like `untagged` above: 0 of 0
    # is not 0%, and a consumer's schema must not gain a meaningless key.
    # implements: REQ-REVIEWEDSCORE-109
    # Emitted only when drafts and reviewed requirements BOTH exist: with no reviewed
    # requirement it would be 0 of 0, and with no draft it would restate `score` under a
    # second name, which is how a consumer's schema quietly grows a key that means nothing.
    # The denominator is `confirmed`, NOT "every non-draft". `healthy`'s first axis is
    # `status == confirmed`, so a `baseline`/`in-progress`/`implemented`/`deprecated`
    # requirement could enter a "non-draft" denominator but never the numerator — it
    # would depress the score with nothing rotting. A `deprecated` requirement is the
    # clearest case: retired, permanently un-green, and it would cap the score forever.
    # Invisible in THIS repo (all 72 non-drafts are `confirmed`, so the two readings
    # coincide at 100), which is exactly why it is pinned by a test instead of by luck.
    reviewed_total = confirmed  # implements: REQ-REVIEWEDSCORE-109
    reviewed_score = round(100 * healthy / reviewed_total) if (reviewed_total and drafts) else None
    return reviewed_score, reviewed_total


def _health_record(reqs, members, reqs_dir):
    # implements: ARCH-HEALTH-017  # implements: REQ-HEALTH-968
    """The corpus coherence snapshot as a record, with no printing and no code
    root: the headline `score` plus the component counts behind it. Split out of
    `cmd_health` so the map can carry the same numbers the console prints instead
    of a viewer recomputing them in JavaScript — two definitions of one score is
    how the CLI and the UI come to disagree about how the repo is doing.

    Depends only on the requirements, their members and the lock, so it is as
    deterministic as the rest of `_map.json` and can be checked for freshness.
    Everything that needs a code root (untagged files, registry lag, the design
    score) stays in `cmd_health`, which layers it on top of this record."""
    total = len(reqs)
    lock = load_lock(reqs_dir)
    satisfied = set()  # need ids with >=1 `satisfies:` edge (ARCH-TRACE-020)
    for r in reqs.values():
        satisfied.update(_as_list(r["meta"].get("satisfies")))
    confirmed = implemented = tested = orphans = untested = 0
    open_intent = drifted = drafts = healthy = retired = 0
    for rid, r in reqs.items():
        f = _requirement_health_flags(rid, r, members, lock, satisfied)
        retired += f["status"] == "deprecated"
        confirmed += f["is_confirmed"]
        implemented += f["has_impl"]
        tested += f["has_test_member"]
        drafts += f["status"] == "draft"
        orphans += f["is_confirmed"] and not f["covered"]
        untested += f["has_impl"] and not f["has_test_member"] and not f["test_exempt"]
        open_intent += f["open_now"]
        drifted += f["is_drifted"]
        if (f["is_confirmed"] and f["covered"] and (f["has_test"] or f["impl_exempt"])
                and not f["open_now"] and not f["is_drifted"]):
            healthy += 1
    # implements: REQ-HEALTH-858
    # A `deprecated` requirement is out of service and can never be green, so counting it
    # capped the headline forever: this repo read 97/100 with nothing wrong, 8 retired
    # requirements in the denominator. The reviewed score already excluded them.
    scored = total - retired
    score = round(100 * healthy / scored) if scored else 0
    reviewed_score, reviewed_total = _reviewed_score(confirmed, drafts, healthy)
    gate_errors = _link_sync_errors(reqs, members)
    data = {"score": score, "total": total, "scored": scored, "healthy": healthy,
            "deprecated": retired, "confirmed": confirmed, "implemented": implemented,
            "tested": tested,
            "drafts": drafts, "orphans": orphans, "untested": untested,
            "open_intent": open_intent, "drift": drifted,
            "gate_errors": len(gate_errors), "gate_link_sync_clean": not gate_errors}
    if reviewed_score is not None:
        data["reviewed_score"] = reviewed_score
        data["reviewed_total"] = reviewed_total
    return data


def _health_gather_signals(reqs, code_root, reqs_dir, data):
    # implements: ARCH-HEALTH-017  # implements: REQ-HEALTH-857
    # implements: REQ-HEALTH-858  # implements: REQ-HEALTH-859
    """Layer the code-root-dependent signals (untagged files, registry lag, design
    score, roadmap drift) onto `data`. Returns (data, untagged, lag, design)."""
    # Untagged-code coverage signal (read-only): count of scannable code files
    # carrying no membership tag — code traced to no requirement. Reuses
    # _scan_untagged (ARCH-NEXT-013). Informational only: it counts FILES, not
    # requirements, so it never enters the per-requirement score, and it is
    # absent (not zero) when no code root is available, e.g. a unit-test caller.
    # implements: ARCH-COVERAGE-029
    # implements: REQ-COVERAGE-836
    untagged = _scan_untagged(code_root, reqs_dir) if code_root else None
    if untagged is not None:
        data["untagged"] = len(untagged)
    # Registry-lag signal (read-only): commits since requirements/ was last
    # touched — a frozen registry while code moves ahead. Absent (not 0) when
    # unmeasurable (no git / no code root), like `untagged`. implements: ARCH-REGISTRYLAG-035
    lag = _commits_since_reqs_touch(code_root, reqs_dir) if code_root else None
    if lag is not None:
        data["commits_since_req_touch"] = lag  # implements: REQ-REGISTRYLAG-904
    # Roadmap signals (read-only): does TODO.md still track what shipped, and does every
    # section heading actually parse as a milestone. Absent (not empty) when the repo has
    # no TODO.md, so a repo that does not keep one sees nothing. implements: ARCH-ROADMAP-038
    # implements: REQ-DESIGN-954
    design = _design_summary(code_root, reqs_dir) if code_root else None
    if design is not None:
        data["design_score"] = design["score"]
        data["design_files"] = design["files"]
    roadmap = _roadmap_signals(code_root) if code_root else None
    if roadmap is not None:
        behind, newest_req, unmapped = _roadmap_behind(reqs, roadmap)
        if behind:
            data["roadmap_behind"] = {"todo": roadmap["newest_milestone"],
                                      "requirements": newest_req}
        if unmapped:
            data["roadmap_unmapped"] = {"shipped": roadmap["newest_shipped"],
                                        "requirements": newest_req}
        if roadmap["unversioned_headings"]:
            data["roadmap_unversioned_headings"] = roadmap["unversioned_headings"]
    # The plan's own gaps, counted here and named by `next`'s Plan bucket from the one
    # computation — `gate --risk` prints the bucket and `gate --risk --json` is this
    # record, so a signal on one surface and not the other is how the two come to
    # disagree about what is left to do. Absent (not 0) with no ROADMAP.md, like
    # `untagged`: a repo that keeps no plan gains no key. implements: REQ-PLANGAPS-1033
    gaps = _plan_gaps(reqs, code_root, reqs_dir)
    if gaps:
        data["plan_gaps"] = len(gaps)
    stale = stale_plan_milestones(reqs_dir, code_root) if reqs_dir else None
    if stale:  # implements: REQ-PLANSTALE-1013
        data["plan_shipped"] = stale
    misaligned = version_alignment_lines(reqs_dir, code_root) if reqs_dir else []
    if misaligned:  # implements: REQ-VERSIONALIGN-1016
        data["version_alignment"] = misaligned
    return data, untagged, lag, design


def _health_badge_payload(data):
    # implements: ARCH-HEALTH-017  # implements: REQ-HEALTH-857
    # implements: REQ-HEALTH-858  # implements: REQ-HEALTH-859
    """The shields.io badge payload for `--badge`, red whenever `gate` itself would
    fail with a link-sync error a green score would otherwise hide."""
    score, total, confirmed = data["score"], data["total"], data["confirmed"]
    gate_errors = data["gate_errors"]
    color = ("brightgreen" if score == 100 else "green" if score >= 80
             else "yellow" if score >= 60 else "red")
    message = "{}/{} | {}%".format(confirmed, total, score)
    # a badge cannot read "clean" while gate has link-sync errors gate itself
    # would fail on — this is the exact false-positive RM-6 closes.
    if gate_errors:
        color = "red"
        message += " | gate:{}".format(gate_errors)
    return {"schemaVersion": 1, "label": "requirements",
            "message": message, "color": color}


def _print_health_report(data, design, untagged, lag, headline_only):
    # implements: ARCH-HEALTH-017  # implements: REQ-HEALTH-857
    # implements: REQ-HEALTH-858  # implements: REQ-HEALTH-859
    """Print the human-readable health report built from an already-assembled
    `data` record."""
    score, total, healthy = data["score"], data["total"], data["healthy"]
    confirmed, implemented = data["confirmed"], data["implemented"]
    tested, drafts, orphans = data["tested"], data["drafts"], data["orphans"]
    untested, open_intent = data["untested"], data["open_intent"]
    drifted, gate_errors = data["drift"], data["gate_errors"]
    reviewed_score = data.get("reviewed_score")
    reviewed_total = data.get("reviewed_total")
    retired = data.get("deprecated", 0)
    print("Requirement health: {}/100  ({}/{} green on every axis{})".format(
        score, healthy, total - retired,
        ", {} deprecated not scored".format(retired) if retired else ""))
    if headline_only:
        # `next` opens with the score and then lists what to do about it; the component
        # breakdown below would push the actionable part off the first screen. The design
        # score rides along because it is the other half of "how is this repo doing" and
        # folding `health` into `next` had quietly dropped it from every text surface.
        if design is not None:
            print("Design pass-rate:   {}%  ({}/{} source files with no candidate)".format(
                design["score"], design["clean_files"], design["files"]))
        return
    # Say what the headline cannot: a draft caps `score` by construction, so a low
    # reading over a draft-heavy corpus means "not reviewed yet", not "rotting".
    # Printed only when drafts actually pull the two numbers apart.
    if reviewed_score is not None:
        print("  reviewed only:      {}/100  ({}/{} confirmed, {} not confirmed yet)".format(
            reviewed_score, healthy, reviewed_total, total - reviewed_total))
    print("  confirmed:   {}/{}".format(confirmed, total))
    print("  implemented: {}/{}".format(implemented, total))
    print("  tested:      {}/{}".format(tested, total))
    print("  drafts:      {}".format(drafts))
    if orphans:     print("  orphans (confirmed, no code):     {}".format(orphans))
    if untested:    print("  untested (code, no tests):        {}".format(untested))
    if open_intent: print("  open verify-intent:               {}".format(open_intent))
    if drifted:     print("  drift (contract changed vs lock): {}".format(drifted))
    if gate_errors: print("  gate link-sync errors (not clean):{}".format(gate_errors))
    if untagged:    print("  untagged code (no requirement):   {}".format(len(untagged)))
    if lag:         print("  commits since requirements touched:{}".format(lag))
    if design is not None:
        print("  design pass-rate (files w/o candidate): {}%  ({}/{}) — "
             "run `reqmap.py ask --design`".format(
                 design["score"], design["clean_files"], design["files"]))
    if total == 0:
        print("  (no requirements yet — run `reqmap.py init`, or write "
              "requirements/AREA-NAME-NNN.md)")


def cmd_health(ws, as_json=False, as_badge=False, headline_only=False):
    # implements: ARCH-HEALTH-017  # implements: REQ-HEALTH-857
    # implements: REQ-HEALTH-858  # implements: REQ-HEALTH-859
    """Print a corpus coherence snapshot: a headline score plus component counts.
    The score is transparent — the percentage of requirements green on EVERY axis
    (confirmed, has an `implements` member, tested-or-`test_exempt`, no open
    verify-intent, not drifted vs the lock). A `layer: need` is covered by ≥1
    `satisfies:` edge instead of code and its test axis is waived, mirroring how
    `check` treats the need layer. `--json` emits the same numbers as a
    parseable object for a CI badge. Read-only, always exit 0.

    `gate_errors`/`gate_link_sync_clean` (informational, never enters `score`):
    the count of `gate`'s own ERROR-level link-sync problems (dangling tags,
    enforced-status requirements with no `implements:` member), so a 100/100
    reading here can no longer coexist with an unseen `gate` failure — see
    RM-6 (Senate run reqmap-health-gate-cleanliness). This does NOT detect a
    value changed with no tag at all; that class of drift needs a sourced/
    `validated-against:` convention on the changed file, which is out of
    scope for this signal."""
    reqs, members, reqs_dir, code_root = ws.reqs, ws.members, ws.reqs_dir, ws.code_root
    data = _health_record(reqs, members, reqs_dir)
    data, untagged, lag, design = _health_gather_signals(reqs, code_root, reqs_dir, data)
    if as_badge:
        print(json.dumps(_health_badge_payload(data)))
        return 0
    if as_json:
        print(json.dumps(data, indent=2))
        return 0
    _print_health_report(data, design, untagged, lag, headline_only)
    return 0
