"""Every @gate_rule, the drift-rule table and run_gate_rules."""
import json, os

from . import config as cfg
from .acceptance import _automatable_acs, _labeled_acs
from .i18n import _load_translations
from .locks import load_memberlock, lock_path, member_drift, untracked_locks
from .mapcmd import _absent_tracked_artifacts, _stale_artifacts
from .model import (
    ENFORCED, LEVEL_TEST_PAIR, MILESTONE_RE, VALID_LAYER, VALID_LEVEL, VALID_STATUS, _as_list,
    _dependency_cycles, _impl_exempt, gate_rule
)
from .orphans import (
    orphan_code_files, tagged_unscanned_files, undecodable_source_files, untagged_doc_bundles,
    untracked_members
)
from .sections import (
    ACCEPTANCE_LABELS, CONTRACT_LABELS, VALID_FORM, _atomic_spans, _from_any, _has_any,
    _legacy_schema_ids
)
from .similar import EXEMPTION_FIELDS, _exemption_reason_recorded
from .text import _bullets, _distinct_intent, _req_title, _section_raw
from .viewer import check_viewer_data_sync
from .workspace import _test_link_problem


@gate_rule("RM001", "error")
def _dangling_tag_rule(ctx):  # implements: REQ-CHECK-828  # implements: REQ-RULES-947
    for cap in ctx.members:
        if cap not in ctx.cap_ids:
            yield None, f"dangling tag: code references {cap} but no requirement exists"


@gate_rule("RM002", "error")
def _frontmatter_rule(ctx):
    # implements: REQ-ATOMICFORM-053  # implements: ARCH-LEVEL-051
    # implements: REQ-CHECK-828  # implements: REQ-LEVEL-862
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        if m.get("status") not in VALID_STATUS:
            yield rid, f"{rid}: invalid status {m.get('status')!r}"
        _frm = m.get("form")
        if _frm and _frm not in VALID_FORM:
            yield rid, f"{rid}: invalid form {_frm!r} (expected one of {sorted(VALID_FORM)})"
        if _frm == "atomic" and not _atomic_spans(r["body"]):
            yield rid, (f"{rid}: form: atomic but the body has no `>` statement plus "
                        f"`Scenario:` block before the first `## ` heading")
        _lvl = m.get("level")
        if _lvl and _lvl not in VALID_LEVEL:
            yield rid, f"{rid}: invalid level {_lvl!r} (expected one of {sorted(VALID_LEVEL)})"
        if m.get("layer") not in VALID_LAYER:
            yield rid, f"{rid}: invalid layer {m.get('layer')!r}"


@gate_rule("RM031", "warn")
def _uncovered_aggregate_rule(ctx):  # implements: ARCH-TRACE-020  # implements: REQ-TRACE-935
    """An `aggregate` is exempt from the implements and tested-by rules because it is
    covered downward by its `depends_on`. An empty list is therefore not a small
    omission: it claims the exemption and supplies nothing to be covered by."""
    for rid in sorted(ctx.cap_ids):
        r = ctx.req(rid)
        meta = r["meta"]
        if meta.get("layer") != "aggregate" or meta.get("status") not in ENFORCED:
            continue
        if _as_list(meta.get("depends_on")) or not ctx.in_scope(rid):
            continue
        yield rid, ("{}: layer: aggregate with an empty `depends_on` — it is exempt "
                    "from the implements and tested-by rules because its dependencies "
                    "cover it, and it has none".format(rid))


@gate_rule("RM003", "error")
def _depends_on_missing_rule(ctx):  # implements: REQ-CHECK-828
    for rid, r in ctx.reqs.items():
        for dep in _as_list(r["meta"].get("depends_on")):
            if dep not in ctx.cap_ids:
                yield rid, f"{rid}: depends_on missing {dep}"


@gate_rule("RM004", "warn")
def _milestone_shape_rule(ctx):
    # an optional, roadmap-only field: a malformed value silently fails to sort in the
    # Roadmap rather than breaking the build, so it warns, only when present and not deprecated.
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        ms = m.get("milestone")
        if ms and m.get("status") != "deprecated" and not MILESTONE_RE.match(str(ms).strip()):
            yield rid, (f"{rid}: milestone {ms!r} is malformed (expected "
                       f"v<digits>[.<digits>…], e.g. v1.14)")


@gate_rule("RM005", "warn")
def _satisfies_dangling_rule(ctx):  # implements: ARCH-TRACE-020  # implements: REQ-TRACE-934
    # a dangling upstream id is a WARN not an ERROR — the need may be authored later
    # or live in an external tracker.
    for rid, r in ctx.reqs.items():
        for up in _as_list(r["meta"].get("satisfies")):
            if up not in ctx.cap_ids:
                yield rid, (f"{rid}: satisfies {up} but no such requirement "
                           f"(upstream trace dangling)")


@gate_rule("RM006", "error")
def _no_implements_rule(ctx):
    # implements: ARCH-TRACE-020  # implements: REQ-CHECK-828  # implements: REQ-RULES-947
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        if m.get("status") in ENFORCED and not _impl_exempt(m) \
                and "implements" not in ctx.roles(rid) and ctx.in_scope(rid):
            yield rid, f"{rid}: status {m['status']} but no implements: tag found in code"


@gate_rule("RM007", "warn")
def _no_tested_by_rule(ctx):  # implements: REQ-CHECK-829
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        if m.get("status") == "confirmed" and "tested-by" not in ctx.roles(rid) \
                and not m.get("test_exempt") and not _impl_exempt(m) and ctx.in_scope(rid):
            yield rid, f"{rid}: confirmed but no tested-by: tag — acceptance tests not linked"


@gate_rule("RM008", "warn")
def _need_not_validated_rule(ctx):  # implements: ARCH-VLEVEL-037  # implements: REQ-CHECK-831
    # a need is validated, not tested; opt-in via any `validated-against` tag in the repo.
    if not ctx.any_validation:
        return
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        if m.get("layer") == "need" and m.get("status") == "confirmed" \
                and "validated-against" not in ctx.roles(rid) and ctx.in_scope(rid):
            yield rid, (f"{rid}: confirmed need with no `validated-against:` tag — "
                        "nothing shows the need was actually met")


@gate_rule("RM009", "warn")
def _bus_only_system_level_rule(ctx):  # implements: ARCH-VLEVEL-037  # implements: REQ-CHECK-831
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        if m.get("status") == "confirmed" and m.get("layer") == "bus" \
                and set(ctx.level_cover.get(rid, {})) == {"system"}:
            yield rid, (f"{rid}: bus capability verified only at @system level — "
                        "add a @unit or @integration `tested-by:` link")


@gate_rule("RM010", "warn")
def _level_rung_rule(ctx):  # implements: REQ-VRUNGS-054
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        _want = LEVEL_TEST_PAIR.get(m.get("level"))
        if m.get("status") == "confirmed" and _want:
            _have = set(ctx.level_cover.get(rid, {}))
            if _have and _want not in _have:
                yield rid, (f"{rid}: level: {m['level']} is verified at "
                            f"{'/'.join('@' + x for x in sorted(_have))} but not @{_want} — "
                            f"add a @{_want} `tested-by:` link, or change the level")


@gate_rule("RM011", "warn")
def _owner_auto_rule(ctx):
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        if m.get("status") == "confirmed" and m.get("owner", "auto") in ("auto", "", None):
            yield rid, f"{rid}: confirmed requirement has owner: auto — assign a named owner"


@gate_rule("RM012", "warn", strict=True)
def _test_link_rule(ctx):  # implements: ARCH-TESTLINK-018  # implements: REQ-TESTLINK-933
    # checked at EVERY status; only a confirmed requirement's broken link is strict-promoted
    # (see cmd_check: a non-confirmed hit is downgraded to a plain warn there).
    # one read per test file, not one per requirement naming it: a suite every
    # requirement points at (this repo's test_reqmap.py) was opened 206 times per gate
    problems = {}
    for rid, r in ctx.reqs.items():
        tests = [x for x in ctx.full_members.get(rid, []) if x[0] == "tested-by"]
        for fp in sorted({t[1] for t in tests}):
            if fp not in problems:
                problems[fp] = _test_link_problem(os.path.join(ctx.code_root, fp))
            if problems[fp]:
                yield rid, f"{rid}: tested-by {fp} {problems[fp]}"


@gate_rule("RM013", "warn")
def _case_coverage_rule(ctx):  # implements: ARCH-ACVERIFY-019
    # ONE aggregated line per requirement, only once it has adopted per-case tagging.
    for rid, r in ctx.reqs.items():
        if r["meta"].get("status") != "confirmed":
            continue
        labels = _automatable_acs(r["body"])
        covered = ctx.ac_cover.get(rid, {})
        if labels and covered:
            missing = [ac for ac in labels if ac not in covered]
            if missing:
                yield rid, (f"{rid}: {len(labels) - len(missing)}/{len(labels)} "
                           f"automatable criteria carry a `# verifies:` tag — missing "
                           + ", ".join(missing))


@gate_rule("RM034", "warn")
def _dangling_verifies_rule(ctx):
    # implements: ARCH-ACVERIFY-019  # implements: REQ-DANGLINGVERIFY-1009
    """RM013 read one direction only — a labelled case with no tag. The other direction
    was unguarded: a `# verifies: <id>#CASE-N` naming a case that does not exist was
    accepted in silence, AND it is what flips RM013 on (`covered` becomes non-empty), so
    a typo produced `0/2 criteria carry a tag` for a file that plainly carries one. The
    label is an identifier; an identifier with no referent is a broken link."""
    for rid in sorted(ctx.ac_cover):
        r = ctx.reqs.get(rid)
        if r is None:
            # RM001 does NOT cover this: it reads `members` (implements/tested-by tags) and
            # never `ac_cover`, so a `verifies:` naming a requirement that does not exist
            # was silent in both rules. Same broken link, so it is reported here.
            locs = [l for ac in sorted(ctx.ac_cover[rid]) for l in ctx.ac_cover[rid][ac]]
            where = ", ".join(f"{fp}:{ln}" for fp, ln in locs[:3])
            yield None, (f"`# verifies: {rid}#…` names no such requirement ({where}"
                         + (", …" if len(locs) > 3 else "") + ")")
            continue
        labels = set(_labeled_acs(r["body"]))
        if not labels:
            continue          # unlabelled acceptance: nothing to dangle against
        for ac in sorted(ctx.ac_cover[rid]):
            if ac in labels:
                continue
            locs = ctx.ac_cover[rid][ac]
            where = ", ".join(f"{fp}:{ln}" for fp, ln in locs[:3])
            yield rid, (f"{rid}: `# verifies: {rid}#{ac}` names no such case ({where}"
                        + (", …" if len(locs) > 3 else "")
                        + f") — the requirement labels {', '.join(sorted(labels))}. "
                        "Fix the label, or the case it meant to name is missing.")


@gate_rule("RM014", "warn")
def _confirmed_sections_rule(ctx):  # implements: REQ-CHECK-829
    for rid, r in ctx.reqs.items():
        if r["meta"].get("status") != "confirmed":
            continue
        if not _has_any(r["body"], CONTRACT_LABELS):
            yield rid, (f"{rid}: confirmed but missing '## Description' section — "
                        "add the normative contract or drop status back to in-progress")
        if not _has_any(r["body"], ACCEPTANCE_LABELS):
            yield rid, (f"{rid}: confirmed but missing '## Cases' section — "
                        "add acceptance criteria or drop status back to in-progress")


@gate_rule("RM015", "warn")
def _need_unsatisfied_rule(ctx):  # implements: ARCH-TRACE-020  # implements: REQ-TRACE-934
    for rid, r in ctx.reqs.items():
        m = r["meta"]
        if (m.get("layer") == "need" and m.get("status") in ENFORCED
                and not ctx.satisfied_by.get(rid)):
            yield rid, (f"{rid}: need has no requirement that satisfies it "
                       f"(upstream trace unaddressed)")


@gate_rule("RM016", "warn")
def _corrupt_lock_rule(ctx):
    # load_lock fails open ({}) on an absent OR corrupt lock; surface the corrupt case so a
    # silently-disabled drift signal is visible.
    lp = lock_path(ctx.reqs_dir)
    if os.path.exists(lp):
        try:
            with open(lp, encoding="utf-8") as f:
                if not isinstance(json.load(f), dict):
                    raise ValueError("not a JSON object")   # `[]`/`null`: load_lock swallows it too
        except (ValueError, OSError):
            yield None, ("_reqlock.json present but unreadable (corrupt/merge-conflicted) "
                         "— drift detection skipped this run; re-run with --update-lock")


@gate_rule("RM017", "warn", only_source_repo=True)
def _viewer_fixture_rule(ctx):  # implements: ARCH-VIEWER-007
    # the viewer's fallback fixture vs the live registry — this repository only.
    candidate = os.path.join(ctx.code_root, "app", "src", "lib", "baked.json")
    if not os.path.exists(candidate):
        return
    nodes = [{"id": rid, "contract": _from_any(_bullets, r["body"], CONTRACT_LABELS)}
             for rid, r in ctx.reqs.items()]
    drifted = check_viewer_data_sync(candidate, nodes)
    if drifted:
        yield None, ("app/src/lib/baked.json out of sync with {} requirement(s): {} — "
                     "update the viewer's fallback fixture or accept the drift is intentional "
                     "for this demo data."
                     .format(len(drifted), ", ".join(drifted)))


@gate_rule("RM029", "warn")
def _translation_parity_rule(ctx):
    # implements: ARCH-TRANSLATE-044  # implements: REQ-TRANSLATE-967
    """A cached translation carrying a field the requirement itself does not emit.

    `translate` and the map both derive from the same requirement, and each was correct
    against it: the map emits no intent when the quote IS the obligation, while the
    translator had been handed the raw quote. Nothing compared the two, so a translated
    document showed a section the untranslated one hides — invisible until a corpus had
    both features populated at once. Fields the requirement has and the translation
    lacks are NOT reported: a partial translation is a normal intermediate state."""
    translations = _load_translations(ctx.reqs, ctx.reqs_dir)
    if not translations:
        return
    for rid in sorted(translations):
        r = ctx.reqs.get(rid)
        if not r:
            continue
        body = r["body"]
        source = {
            "title": _req_title(body, rid),
            "intent": _distinct_intent(body),
            "contract": _from_any(_section_raw, body, CONTRACT_LABELS) or "",
            "acceptance": _from_any(_section_raw, body, ACCEPTANCE_LABELS) or "",
        }
        for locale in sorted(translations[rid]):
            entry = translations[rid][locale] or {}
            extra = sorted(f for f, v in source.items()
                           if not str(v).strip() and str(entry.get(f, "")).strip())
            if extra:
                yield rid, ("{}: translation `{}` carries {} the requirement does not emit — "
                            "re-run `translate` so the two agree, or clear the field"
                            .format(rid, locale, ", ".join("`" + f + "`" for f in extra)))


@gate_rule("RM030", "warn")  # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-971
def _exemption_without_reason_rule(ctx):
    """An exemption whose check is never mentioned in the requirement's own prose.

    Warn-only, and never promoted under `--strict`: the point is to make silencing a
    finding cost a sentence, not to make it impossible. A shape that is genuinely
    deliberate is one line away from clean; a shape that was silenced to make a run
    green has nobody willing to write that line."""
    for rid in sorted(ctx.reqs):
        r = ctx.reqs[rid]
        for field in EXEMPTION_FIELDS:
            for check in _as_list(r["meta"].get(field)):
                if not _exemption_reason_recorded(r["body"], check):
                    yield rid, ("{}: `{}: [{}]` silences a finding with no reason recorded "
                                "\u2014 say why in the requirement's prose, or drop the "
                                "exemption and fix what it hides".format(rid, field, check))


# The two rules that say "the spec and the code no longer agree". They warn by default
# and promote under `--strict`; a repo may also promote them for itself with
# `DRIFT_SEVERITY: "error"` in `_config.json`. The default stays `warn` because the
# evidence for that is recorded and unchanged (ADR-0002): a spec-first edit legitimately
# drifts the contract ahead of the code, and a check that fails on correct work is a
# check someone bolts `continue-on-error` onto and never reads again. Which side of that
# trade a repo wants is the repo's call, not the tool's.
DRIFT_RULES = ("RM018", "RM019")


@gate_rule("RM018", "warn", strict=True)
def _drift_rule(ctx):
    # implements: ARCH-DRIFT-003  # implements: ARCH-DRIFTIMPACT-035
    # implements: REQ-CHECK-829  # implements: REQ-DRIFTIMPACT-843
    for rid, r in ctx.reqs.items():
        h, old = ctx.new_lock[rid], ctx.lock.get(rid)
        if old and old != h and r["meta"].get("status") == "confirmed":
            locs = [f"{fp}:{ln}" for (_role, fp, ln) in ctx.members.get(rid, [])]
            where = ", ".join(locs) if locs else "no members tagged — add an implements: tag"
            deps_of = sorted(ctx.dependents.get(rid, ()))
            fanout = "; review dependent(s): " + ", ".join(deps_of) if deps_of else ""
            yield rid, (f"{rid}: DRIFT — contract changed since lock; "
                        f"re-check {len(locs)} member(s): {where}{fanout}")


@gate_rule("RM019", "warn", strict=True)
def _member_drift_rule(ctx):  # implements: ARCH-MEMBERDRIFT-027
    memberlock = load_memberlock(ctx.reqs_dir)
    for rid, rel in member_drift(ctx.reqs, ctx.members, ctx.lock, memberlock, ctx.code_root,
                                 current=ctx.full_member_hashes):
        yield rid, (f"{rid}: MEMBER DRIFT — {rel} changed since lock but the contract "
                    "was not re-touched; re-check the requirement, or run sync to re-baseline")


@gate_rule("RM020", "warn")
def _untracked_lock_rule(ctx):
    for lp_rel in untracked_locks(ctx.reqs_dir):
        yield None, (f"{lp_rel} exists on disk but is not git-tracked — `git add {lp_rel}` so "
                     "drift detection works in CI (an uncommitted lock is invisible to a "
                     "fresh checkout)")


@gate_rule("RM021", "warn")
def _doc_bundle_rule(ctx):  # implements: ARCH-DOCBUNDLE-026
    for rel in untagged_doc_bundles(ctx.code_root, ctx.full_members, ctx.reqs_dir):
        yield None, (f"{rel}: large docs/ HTML bundle ({cfg.DOC_BUNDLE_MIN_BYTES // 1000}KB+) "
                     "has no generated-from: tag — link it to the requirement(s) it derives from "
                     "(`<!-- generated-from: A, B -->`), or add it to .reqmapignore")


@gate_rule("RM022", "warn")
def _untracked_members_rule(ctx):  # implements: ARCH-TRACKED-042
    _untracked = untracked_members(ctx.code_root, ctx.full_members)
    if _untracked:
        yield None, (
            "{} member(s) are not tracked by git: {} — the committed map records them, but a "
            "fresh checkout has no such file, so it cannot be regenerated there. Commit them, "
            "or exclude them in .reqmapignore.".format(
                len(_untracked), ", ".join(_untracked[:5])
                + ("" if len(_untracked) <= 5 else ", …")))


@gate_rule("RM023", "warn")
def _unscanned_tags_rule(ctx):  # implements: ARCH-UNSCANNEDTAG-045
    _unscanned = tagged_unscanned_files(ctx.code_root, ctx.reqs_dir)
    if _unscanned:
        yield None, (
            "{} tag(s) in file type(s) the scan never reads: {} — those files are not members. "
            "Move the tag into a scannable file, or ask for the type to be added to the scan."
            .format(
                len(_unscanned), ", ".join(_unscanned[:5])
                + ("" if len(_unscanned) <= 5 else ", …")))


@gate_rule("RM033", "warn")
def _undecodable_source_rule(ctx):  # implements: ARCH-UNREADABLE-070
    # implements: REQ-UNREADABLE-1004
    _bad = undecodable_source_files(ctx.code_root, ctx.reqs_dir)
    for rel, reason in _bad:
        yield None, (f"{rel}: {reason} — the scan cannot read it, so any tag in it is "
                     "invisible and it counts as untagged. Re-save it as UTF-8, or add it "
                     "to .reqmapignore.")


@gate_rule("RM024", "warn")
def _orphan_code_rule(ctx):  # implements: ARCH-ORPHANCODE-034
    covered = {fp for hits in ctx.full_members.values() for (_role, fp, _ln) in hits}
    covered.update(fp for acs in ctx.ac_cover.values()
                   for locs in acs.values() for (fp, _ln) in locs)
    for rel in orphan_code_files(ctx.code_root, covered, ctx.reqs_dir):
        yield None, (f"{rel}: {cfg.ORPHAN_CODE_MIN_LOC}+-line code file has no membership tag — "
                     "link it (`# implements: <ID>`), draft a requirement for it "
                     "(`reqmap.py init`), or add it to .reqmapignore")


@gate_rule("RM025", "warn")
def _legacy_schema_rule(ctx):  # implements: REQ-CHECK-831
    legacy = _legacy_schema_ids(ctx.reqs)
    if legacy:
        yield None, ("{}/{} requirement(s) use the legacy schema (the Input/Description/"
                     "Output triad) — `findings` is inactive for them: {}"
                     .format(len(legacy), len(ctx.reqs), ", ".join(legacy)))


@gate_rule("RM026", "warn")
def _depends_on_cycle_rule(ctx):  # implements: ARCH-CHECK-006  # implements: REQ-CHECK-831
    # warn, not error: a cycle is a modelling call across several requirements (ADR-0002).
    for _cyc in _dependency_cycles(ctx.reqs):
        # The second sentence is the SYMPTOM, not the defect, and it is here because a
        # consumer hit the symptom and could not get from it to this message: the map
        # layout ranks by longest path, which does not converge on a cyclic graph, so a
        # few nodes get pushed hundreds of columns out and every edge into them renders
        # as a near-horizontal line. "The map looks like stripes" does not read as
        # "the graph has a cycle" to anyone who has not been told.
        yield None, ("depends_on cycle: " + " -> ".join(_cyc)
                     + " — no requirement in a cycle can be built before the others; "
                       "drop the edge that closes it. This also flattens the map: the "
                       "layout ranks by longest path, so a cycle stretches the canvas "
                       "and its edges render as near-horizontal lines")


@gate_rule("RM027", "warn")
def _map_stale_rule(ctx):  # implements: ARCH-MAP-007
    # skipped under update_lock: `sync` regenerates the map moments later.
    if ctx.update_lock:
        return
    try:
        absent_map = _absent_tracked_artifacts(ctx.reqs_dir, ctx.code_root)
        stale_map = _stale_artifacts(
            ctx.ws.map_data(ctx.code_root, ctx.full_members), ctx.ws, ctx.code_root)
    except Exception:
        absent_map, stale_map = [], []  # fail-open — a freshness probe never blocks the gate
    if absent_map:
        yield None, ("committed map is missing from the working tree: "
                     + ", ".join(absent_map)
                     + " — git tracks it; restore it or run `reqmap.py sync`")
    if stale_map:
        yield None, ("committed map is stale: " + ", ".join(stale_map)
                     + " — run `reqmap.py sync` (or `map`) and commit the result")
