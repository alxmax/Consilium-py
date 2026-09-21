"""`gate --audit`: the corpus-shape report."""
import contextlib, datetime, io, json

from . import MAP_ENGINE_VERSION, config as cfg
from .design_report import _design_summary, cmd_design
from .gate import cmd_check, run_gate_rules
from .groups import decomposable
from .health import _health_record, cmd_coverage
from .i18n import _translation_gaps
from .lint import lint_requirement
from .lintrules import LINT_STATUSES, LINT_STRICT_PROMOTE
from .mapdata import (
    _read_roadmap, _roadmap_behind, _roadmap_plan_problems, _roadmap_signals
)
from .plandrift import (
    bar_date_lines, bar_date_suggestions, plan_drift, plan_drift_lines, unplanned_line
)
from .targets import load_targets
from .versions import stale_plan_milestones, version_alignment_lines
from .model import _as_list
from .orphans import _scan_untagged
from .relevel import relevel_residue_lines
from .risk import cmd_next
from .similar import _corpus_shape, _exemptions_in_force, _redundant_groups, cmd_similar
from .workspace import GateContext


# ---------- health (corpus coherence snapshot) ----------
def _audit_section(title, remedy, fn, fail_rc=0):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """Run one discovery pass with its output captured, so the summary can be printed
    before the detail it summarises. Returns (title, remedy, text, rc).

    A crashing section is swallowed because advice must not fail a build — but the Gate
    section is not advice, it IS the exit code, and swallowing its crash to rc 0 printed
    `Gate  clean` for a run that never reached a verdict. `fail_rc` is how a section says
    what its own failure means; only the gate passes 1."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = fn()
    except Exception as e:                      # a section is advice, never a crash
        return (title, remedy, "  (section failed: {})".format(e), fail_rc)
    return (title, remedy, buf.getvalue().rstrip(), rc or 0)


def _exemption_line(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming exemptions with no reason recorded, or None."""
    exemptions = _exemptions_in_force(reqs)
    unexplained = [e for e in exemptions if not e["reason"]]
    if not unexplained:
        return None
    return "{} exemption(s) silence a check with no reason recorded".format(len(unexplained))


def _lint_error_line(reqs, members):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming lint ERRORs across the non-draft corpus, or None.

    Readability, reported where it is cheapest to act on. `gate` is what ENFORCES it
    (and the pre-commit hook runs `gate`), so this changes no exit code — it moves the
    moment a finding is seen to the one where the author still has the clause in mind.

    Errors only. A style warning is not a reason to break this summary's silence on an
    otherwise-clean corpus: this repo carries two long-standing ones, so a line keyed on
    warnings would fire on every sync forever, which is the habit ADR-0016 rejected. An
    ERROR is a confirmed requirement missing a load-bearing section — worth the line."""
    lint_errors = lint_warns = 0
    for rid, r in reqs.items():
        if r["meta"].get("status") not in LINT_STATUSES:
            continue
        for f in lint_requirement(rid, r, members.get(rid)):
            if f["severity"] == "error" or f["check"] in LINT_STRICT_PROMOTE:
                lint_errors += 1     # the same promotion `gate` applies (it lints strict)
            else:
                lint_warns += 1
    if not lint_errors:
        return None
    return ("readability: {} error(s) across the non-draft corpus ({} warning(s) "
           "too) - run `reqmap.py gate` for the lines".format(lint_errors, lint_warns))


def _level_gap_line(shape):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming requirements with no declared `level:`, or None.

    Reported at ANY ratio, not only under `flat`. `flat` is `levelled * 10 < total`,
    so a corpus 85% of the way through a retrofit said nothing at all — and a
    partly-levelled corpus is precisely what a retrofit leaves behind, so the one
    state this tail could not see was the one it exists to report. The remedy is
    named here rather than left in `audit`: a signal whose command the reader has to
    go and find is a signal most readers will not act on."""
    unlevelled = shape["total"] - shape["levelled"]
    if not unlevelled:
        return None
    return ("{} of {} requirements declare no `level:`{} - "
           "`reqmap.py clarify --levels` proposes a rung for each and writes "
           "nothing without --apply".format(
               unlevelled, shape["total"],
               " - the corpus is flat" if shape["flat"] else ""))


def _decompose_candidates_line(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming requirements with contract groups and no code children, or None.

    The code rung a tagged corpus could not reach (REQ-DECOMPOSE-994): requirements whose
    Description already draws the seams — bold group labels — and that have no child
    satisfying them. Reported here, never written here: `sync` runs inside the consumer's
    pre-commit hook, and a write that creates files the commit does not contain and
    drifts confirmed parents is what ADR-0031's "Why not on sync" refuses. The command is
    named so the fix is one step away from the place the signal appears."""
    kids = set()
    for _r in reqs.values():
        kids.update(_as_list(_r["meta"].get("satisfies")))
    splittable = [rid for rid, _r in reqs.items() if rid not in kids and decomposable(_r)]
    if not splittable:
        return None
    return ("{} requirement(s) carry contract groups and no code children - "
           "`reqmap.py clarify --decompose` plans the split along those groups, "
           "--apply writes it".format(len(splittable)))


def _i18n_gap_line(reqs, reqs_dir):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming requirements with no fresh translation, or None.

    Translation coverage, only when the repo asked for a second language. Under `en`
    nothing is expected and nothing is said; under `ro`/`both` a requirement with no
    fresh Romanian entry is a gap, named with the command that hands over the text."""
    gaps = _translation_gaps(reqs, reqs_dir)
    if not gaps:
        return None
    missing = sum(1 for g in gaps if g["reason"] == "missing")
    return ("{} requirement(s) have no fresh translation for LANGUAGE `{}` ({} missing, "
           "{} stale) - `reqmap.py ask --i18n --json` emits the entries to fill"
           .format(len(gaps), cfg.LANGUAGE, missing, len(gaps) - missing))


def _auto_level_line(shape):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming requirements still carrying the engine's proposed level, or None.

    A corpus can be fully levelled and still be nothing but the engine's guesses,
    in which case every other number here reads as healthy. ADR-0030's revisit
    trigger is exactly this ratio. Reported beside the line above rather than
    instead of it: "some rungs are missing" and "some rungs are guesses" are two
    facts, and a corpus mid-retrofit is usually both."""
    if not shape.get("auto"):
        return None
    return ("{} of {} levelled requirement(s) still carry the rung the engine "
           "proposed (`level_source: auto`) - rename, merge or accept them"
           .format(shape["auto"], shape["levelled"]))


def _design_candidate_line(code_root, reqs_dir):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming source files that carry a design candidate, or None."""
    design = _design_summary(code_root, reqs_dir) if code_root else None
    if design is None or design["clean_files"] >= design["files"]:
        return None
    return "design pass-rate {}% - {} of {} source files carry a candidate".format(
        design["score"], design["files"] - design["clean_files"], design["files"])


def _untagged_files_line(code_root, reqs_dir):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """One line naming code files traced to no requirement, or None."""
    untagged = _scan_untagged(code_root, reqs_dir) if code_root else None
    if not untagged:
        return None
    return "{} code file(s) traced to no requirement".format(len(untagged))


def _plan_stale_line(code_root, reqs_dir):
    # implements: ARCH-AUDIT-065  # implements: REQ-PLANSTALE-1013
    """One line naming planned milestones already declared, or None."""
    stale = stale_plan_milestones(reqs_dir, code_root) if reqs_dir else None
    if not stale:
        return None
    return ("_planning.json schedules {} at or below {} ({}) - the plan names a version "
            "already declared".format(", ".join(stale["milestones"]), stale["baseline"],
                                      stale["source"]))


def _version_lines(code_root, reqs_dir):
    # implements: ARCH-AUDIT-065  # implements: REQ-VERSIONALIGN-1016
    """The plan-versus-release line plus every place the version sources disagree."""
    if not reqs_dir:
        return []
    stale = _plan_stale_line(code_root, reqs_dir)
    return ([stale] if stale else []) + version_alignment_lines(reqs_dir, code_root)


def _bar_date_lines(bars, reqs, members, code_root):
    # implements: ARCH-AUDIT-065  # implements: REQ-PLANDATES-1022
    """The dates `sync` suggests changing on bars whose work finished, or ran over."""
    if not (bars and code_root):
        return []
    return bar_date_lines(bar_date_suggestions(bars, reqs, members, code_root,
                                               datetime.date.today().isoformat()))


def _roadmap_lag_lines(reqs, code_root):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """Zero or more lines describing how TODO.md's roadmap and the requirements
    disagree about how far along the work is."""
    lines = _roadmap_plan_problems(code_root, reqs) if code_root else []
    roadmap = _roadmap_signals(code_root) if code_root else None
    if not roadmap:
        return lines
    # implements: REQ-ROADMAP-983
    # Each line ends with the edit that clears it: a finding with no next step is one a
    # reader has to go and research, and this one was left standing for three minors.
    behind, newest_req, unmapped = _roadmap_behind(reqs, roadmap)
    if behind:
        lines.append("TODO.md stops at {} while the requirements reach {} - add a `## {}` "
                     "heading for that work".format(roadmap["newest_milestone"], newest_req,
                                                    newest_req))
    if unmapped:
        lines.append("the requirements stop at {} while TODO.md marks work shipped "
                     "through {} - add `milestone:` to the requirements that shipped after {}"
                     .format(newest_req, roadmap["newest_shipped"], newest_req))
    if roadmap["unversioned_headings"]:
        lines.append("{} TODO.md heading(s) are not milestones, so their items never reach "
                     "the roadmap - start each with its version, `## vX.Y` (first: {})"
                     .format(len(roadmap["unversioned_headings"]),
                             roadmap["unversioned_headings"][0]))
    return lines


def _print_audit_roadmap(reqs, code_root, reqs_dir=None):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """Print the roadmap-lag block, the audit's third section with no verb of its own.

    These lines existed since REQ-AUDIT-973 but were reachable only from `sync`'s tail,
    so the report actually NAMED "audit" was structurally blind to them. That matters
    most for the unversioned-headings line, which does not describe a defect in the
    corpus: it says the roadmap feature is INERT for this repo, because its headings are
    not milestones. A consumer reported reading the engine's source to find that out.

    Deliberately here and not in the bare `gate`: the commit hook runs `gate` on every
    commit and ADR-0020 draws that line for corpus-shape signals. `--audit` is a question
    a reader asks on purpose."""
    lines = _version_lines(code_root, reqs_dir)
    lines += _roadmap_lag_lines(reqs, code_root)
    # Only here, never in `sync`'s tail: this one walks the tree a second time and shells
    # to git once per cited file. `--audit` is asked for on purpose; `sync` runs on every
    # edit and must not grow a second walk.
    drift = plan_drift(_read_roadmap(code_root) or [], code_root, reqs_dir) if code_root else None
    lines = lines + (plan_drift_lines(drift) if drift else [])
    if not lines:
        return
    print("-" * 72)
    print("Roadmap - how the plan and the requirements disagree")
    print("-" * 72)
    for text in lines:
        print("  " + text)
    if drift:
        for rec in drift["sure"][:5]:
            what = ", ".join(rec["paths"] + rec["symbols"])
            print("    gone: {}  <- {}".format(what, rec["name"][:60]))
        for rec in drift["rederive"][:5]:
            print("    since {}: {}  <- {}".format(
                rec["since"], ", ".join(f["path"] for f in rec["files"][:2]), rec["name"][:60]))
    print("")


def _audit_summary(reqs, members, reqs_dir, code_root):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-973
    """The one-line-per-signal tail `sync` prints: what `audit` would report, without
    running the passes that cost a second walk of the tree. Silent about anything that
    is clean, so a healthy repo sees nothing and the lines that do appear are news."""
    shape = _corpus_shape(reqs)
    lines = [text for text in (
        _exemption_line(reqs),
        _lint_error_line(reqs, members),
        _level_gap_line(shape),
        _decompose_candidates_line(reqs),
        _i18n_gap_line(reqs, reqs_dir),
        _auto_level_line(shape),
        _design_candidate_line(code_root, reqs_dir),
        _untagged_files_line(code_root, reqs_dir),
    ) if text]
    lines.extend(_version_lines(code_root, reqs_dir))
    bars = load_targets(reqs_dir).get("bars", []) if reqs_dir else []
    lines.extend(_bar_date_lines(bars, reqs, members, code_root))
    unplanned = unplanned_line(_read_roadmap(code_root), bars) if code_root else None
    if unplanned:
        lines.append(unplanned)
    lines.extend(_roadmap_lag_lines(reqs, code_root))
    lines.extend(relevel_residue_lines(reqs))
    if not lines:
        return
    print("")
    for ln in lines:
        print("info  {}".format(ln))
    print("info  run `reqmap.py gate --audit` for the full report")


def _json_audit_report(ws, signals, strict):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """Build and print the `--json` audit report; return the gate's exit code.

    `signals` bundles the already-computed shape/health/design/untagged/exemptions
    (and their unexplained subset) `cmd_audit` gathers once for both report forms —
    an object in place of the parameter list those five separate values would be."""
    reqs, members = ws.reqs, ws.members
    health, shape = signals["health"], signals["shape"]
    design, untagged = signals["design"], signals["untagged"]
    out = {"health": health, "shape": shape, "exemptions": signals["exemptions"],
           "redundant_groups": [sorted(g) for g in _redundant_groups(reqs)]}
    if design is not None:
        out["design"] = design
    if untagged is not None:
        out["untagged"] = len(untagged)
    # Same lines the console report prints under "Roadmap" — a JSON consumer that could
    # not see them would be back in the position REQ-AUDIT-973's reporter was in.
    roadmap = _version_lines(ws.code_root, ws.reqs_dir)
    roadmap += _roadmap_lag_lines(reqs, ws.code_root)
    if roadmap:
        out["roadmap"] = roadmap
    errs, warns = run_gate_rules(
        GateContext(ws, full_members=members, update_lock=False),
        strict=strict)
    out["gate"] = {"errors": len(errs), "warnings": len(warns),
                   "findings": [dict(f) for f in list(errs) + list(warns)]}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1 if errs else 0


def _summary_table_rows(gate_rc, signals, dups):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """The audit's summary table: one row per signal, in report order.

    `signals` is the same bundle `_json_audit_report` reads — see its docstring."""
    health, design, untagged = signals["health"], signals["design"], signals["untagged"]
    exemptions, unexplained, shape = (signals["exemptions"], signals["unexplained"],
                                      signals["shape"])
    verdict = "FAIL" if gate_rc else "clean"
    rows = [("Gate", verdict, "reqmap.py gate"),
            ("Health", "{}/100 ({}/{} green on every axis)".format(
                health["score"], health["healthy"], health.get("scored", health["total"])),
             "reqmap.py gate --risk")]
    if design is not None:
        rows.append(("Design pass-rate", "{}% ({}/{} files with no candidate)".format(
            design["score"], design["clean_files"], design["files"]), "reqmap.py ask --design"))
    if untagged is not None:
        rows.append(("Untagged code", "{} file(s) traced to no requirement".format(len(untagged)),
                     "reqmap.py gate --risk --untagged"))
    if dups:
        rows.append(("Redundancy", "{} group(s) share an identical contract".format(len(dups)),
                     "reqmap.py ask --dupes"))
    rows.append(("Exemptions", "{} in force, {} with no recorded reason".format(
        len(exemptions), len(unexplained)), "see below"))
    rows.append(("Corpus shape", "{}/{} carry a `level:`{}".format(
        shape["levelled"], shape["total"], " - the corpus is flat" if shape["flat"] else ""),
        "see below"))
    return rows


def _print_audit_sections(sections):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """Print each discovery section's captured output under its own banner."""
    for title, remedy, text, _rc in sections:
        print("-" * 72)
        print("{}   ({})".format(title, remedy))
        print("-" * 72)
        print(text if text else "  nothing to report")
        print("")


def _print_audit_exemptions(exemptions):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """Print the exemptions-in-force block, one of the audit's two sections with no
    verb of its own."""
    print("-" * 72)
    print("Exemptions in force")
    print("-" * 72)
    if not exemptions:
        print("  none - no requirement silences a check.")
    else:
        for e in exemptions:
            mark = " " if e["reason"] else "!"
            print("  {} {:<22} {}: [{}]{}".format(
                mark, e["id"], e["field"], e["check"],
                "" if e["reason"] else "   <- no reason recorded"))
        print("")
        print("  An exemption is a finding somebody decided not to see. It is legitimate")
        print("  when the shape is deliberate and the reason is written down; it is not a")
        print("  way to make a run green. For an over-scoped requirement the fix is")
        print("  `reqmap.py clarify <ID> --decompose`, which scaffolds the extra clause out.")
    print("")


def _print_audit_corpus_shape(shape):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """Print the corpus-shape block, the audit's other section with no verb of its own."""
    print("-" * 72)
    print("Corpus shape - the V-model's left arm")
    print("-" * 72)
    if shape["levelled"]:
        for lv in ("system", "architecture", "code"):
            if lv in shape["levels"]:
                print("  {:<14} {}".format(lv, shape["levels"][lv]))
        for lv in sorted(k for k in shape["levels"] if k not in ("system", "architecture", "code")):
            print("  {:<14} {}   (not one of the three rungs)".format(lv, shape["levels"][lv]))
        print("  satisfies:     {} edge(s)".format(shape["satisfies_edges"]))
    if shape["flat"]:
        print("  {} of {} requirements declare no `level:`, so every one of them reads as".format(
            shape["total"] - shape["levelled"], shape["total"]))
        print("  the same rung. `level:` is opt-in - the template ships it commented out - so")
        print("  a corpus never gains the axis by itself. The three rungs are:")
        print("    system        a stakeholder need, satisfied by architecture, not by code")
        print("    architecture  one capability: a command, or a shared engine facility")
        print("    code          one behaviour group, 3-7 labelled cases, tested per case")
        print("  The edge that builds the pyramid is `satisfies:` (the level axis), not")
        print("  `depends_on:` (the composition axis). Adopting it is a decision, not a")
        print("  defect: nothing here fails because a corpus is flat.")
        # A detection that names no next step leaves a reader knowing they are flat
        # and not knowing what to do about it. Now that a retrofit exists, say so.
        print("  If you decide to adopt it: `reqmap.py clarify --levels` proposes a rung")
        print("  for each requirement and writes nothing without --apply.")
    print("")


def cmd_audit(ws, strict=False, as_json=False):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-970
    """Run every pass that discovers a problem, and print one report.

    The engine grew one verb per question — is it linked, is it drifted, is it
    duplicated, is it tagged, is the design rotting — and answering "how is this repo
    doing" meant remembering all of them. This runs them together and prints a summary
    of what each found, then each section's own output underneath.

    Read-only. The exit code comes from the gate alone: everything else here is advice,
    and advice must not be able to fail a build. Two sections have no verb of their own
    because they only make sense in this report: the exemptions in force, and the shape
    of the corpus on the V-model's left arm."""
    reqs, members, reqs_dir, code_root = ws.reqs, ws.members, ws.reqs_dir, ws.code_root
    exemptions = _exemptions_in_force(reqs)
    unexplained = [e for e in exemptions if not e["reason"]]
    shape = _corpus_shape(reqs)
    health = _health_record(reqs, members, reqs_dir)
    design = _design_summary(code_root, reqs_dir) if code_root else None
    untagged = _scan_untagged(code_root, reqs_dir) if code_root else None
    # Bundled once, in place of the long parameter list this report's two shapes
    # (`--json` and the console table) would otherwise both need repeated.
    signals = {"shape": shape, "health": health, "design": design, "untagged": untagged,
               "exemptions": exemptions, "unexplained": unexplained}

    if as_json:
        return _json_audit_report(ws, signals, strict)

    sections = [
        _audit_section("Gate", "reqmap.py gate",
                       lambda: cmd_check(ws, False, strict=strict), fail_rc=1),
        _audit_section("Risk", "reqmap.py gate --risk", lambda: cmd_next(ws, False)),
        _audit_section("Duplicates", "reqmap.py ask --dupes",
                       lambda: cmd_similar(reqs, cfg.SIMILAR_THRESHOLD, members)),
        _audit_section("Design", "reqmap.py ask --design",
                       lambda: cmd_design(code_root, reqs_dir)),
        _audit_section("Tag coverage", "reqmap.py gate --risk --untagged",
                       lambda: cmd_coverage(ws, False)),
    ]
    gate_rc = sections[0][3]
    dups = _redundant_groups(reqs)

    print("AUDIT  {} requirement(s) - engine {}".format(len(reqs), MAP_ENGINE_VERSION))
    print("")
    rows = _summary_table_rows(gate_rc, signals, dups)
    width = max(len(r[0]) for r in rows)
    vwidth = max(len(r[1]) for r in rows)
    for name, value, remedy in rows:
        print("  {}  {}  {}".format(name.ljust(width), value.ljust(vwidth), remedy))
    print("")

    _print_audit_sections(sections)
    _print_audit_exemptions(exemptions)
    _print_audit_corpus_shape(shape)
    _print_audit_roadmap(reqs, code_root, reqs_dir)
    return gate_rc
