"""`lint`: run the checks over one requirement, the oversize predicate, cmd_lint."""

from .decompose import _decompose_clause
from .lintrules import (
    LINT_STATUSES, LINT_STRICT_PROMOTE, _acceptance_lint, _graph_lint, _readability_lint,
    _sections_lint, _shape_lint, _terms_lint
)
from .model import _as_list
from .text import _req_file


def lint_requirement(rid, r, member_list=None, fanin=None, children=None):
    # implements: ARCH-LINT-014  # implements: ARCH-LINTCHECKS-025
    # implements: ARCH-FANOUT-052  # implements: REQ-LINT-863
    # implements: REQ-LINTCHECKS-865  # implements: REQ-LINTCHECKS-866
    # implements: REQ-LINTCHECKS-867  # implements: REQ-LINTCHECKS-868
    # implements: REQ-LINTCHECKS-869
    """Return a list of {severity, check, detail} findings for one requirement;
    an empty list means clean. Checks the Contract + Acceptance sections only.
    `member_list` (optional [(role, file, line), ...]) enables the member-based
    file-spread check; when omitted, that check is skipped.
    `fanin` (optional int — how many requirements depend on this one) enables the
    layer-mismatch check; when omitted, that check is skipped.
    `children` (optional int — how many requirements declare `satisfies:` this one) enables
    the fan-out check; when omitted, or when it is zero, that check is skipped.
    Checks named in the requirement's `lint_exempt:` frontmatter list are silently
    skipped and not counted against the requirement."""
    exempt = set(_as_list(r["meta"].get("lint_exempt")))
    body = r["body"]
    findings = []
    findings += _sections_lint(body)
    findings += _readability_lint(body)
    findings += _acceptance_lint(body, r, rid)
    findings += _shape_lint(rid, r, body, children)
    findings += _terms_lint(body)
    findings += _graph_lint(r, member_list, fanin)
    if exempt:
        findings = [f for f in findings if f["check"] not in exempt]
    return findings


# NOTE: `--decompose` deliberately covers `statement-size` ONLY. An `ac-count-high`
# triage-stub path was written and then removed before it ever shipped: `_oversize`
# fires on 0 of this corpus's 72 lintable requirements (all six over LINT_AC_MAX
# carry `lint_exempt: [ac-count-high]`), so the path was unreachable, and ADR-0022 —
# adopted in the same change — forbids shipping on a signal with no published fire
# rate AND no human-confirmation sample. `ac-count-high` had a 0.0% post-exempt rate
# and no independent sample, which is the profile ADR-0022 used to REJECT its sibling
# proposal. Re-adding it needs that ADR's bar met first, not a code review.


def _fanin_and_kids(reqs):
    # implements: ARCH-LINT-014  # implements: ARCH-LINTCHECKS-025
    # implements: ARCH-FANOUT-052
    """(fanin, kids) over every requirement id: fanin[x] = how many requirements
    depend_on x, kids[x] = how many declare satisfies: x. Feeds the layer-mismatch
    and fan-out lint checks."""
    fanin = {rid: 0 for rid in reqs}
    kids = {rid: 0 for rid in reqs}
    for _rid, _r in reqs.items():                          # satisfies edges, child side
        for _up in _as_list(_r["meta"].get("satisfies")):
            if _up in kids:
                kids[_up] += 1
    for _rid, _r in reqs.items():
        for _dep in _as_list(_r["meta"].get("depends_on")):
            if _dep in fanin:
                fanin[_dep] += 1
    return fanin, kids


def _apply_decompose(fs, reqs_dir, rid, r, reqs, created):
    # implements: ARCH-LINT-014  # implements: ARCH-DECOMPOSE-050
    # implements: REQ-LINT-863
    """Scaffold one draft per `statement-size` finding in `fs` via `_decompose_clause`;
    appends the new ids to `created` in place."""
    for f in fs:
        if f["check"] != "statement-size":
            continue
        made = _decompose_clause(reqs_dir, rid, r, f["clause_n"], f["clause_text"], reqs)
        if made:
            created.append(made)
            print("  created  requirements/{}.md  (draft, seeded from clause {})".format(
                made, f["clause_n"]))
        else:
            print("  skipped  clause {} \u2014 already scaffolded".format(f["clause_n"]))


def cmd_lint(ws, strict=False, decompose=False, only=None):
    # implements: ARCH-LINT-014  # implements: ARCH-DECOMPOSE-050  # implements: REQ-LINT-863
    """Report readability/structure violations on non-draft requirements so they
    stay easy to understand — the SKILL.md 'Audience & writing level' rules made
    mechanical. Checks: missing-section (error),
    stacked-conditions (warn), statement-too-long (warn), ac-count-low (warn),
    ac-count-high (warn), vague-term (warn), redundant-modal (warn). Read-only.
    Exit-neutral by default; with --strict it exits non-zero on any error-severity
    finding AND promotes structural checks (ac-count-high) to error severity.
    Requirements with `lint_exempt: [check-name]` frontmatter silently skip those checks;
    active exemptions are printed after the requirement header.
    The default run writes nothing. With `decompose` (the opt-in `--decompose` flag) each
    `statement-size` finding scaffolds one draft requirement from its clause. It covers
    that check ONLY - see the note above `cmd_lint` for why `ac-count-high` does not get
    the same treatment. The gate, the pre-commit hook and CI never pass it: `gate` runs
    the lint and the map-freshness check in one verdict, so a file written during the
    lint step would fail the freshness check of the same run (ARCH-DECOMPOSE-050).
    `only` narrows the run to one id — `clarify <ID> --decompose` promises to scaffold
    for that requirement, not for every over-long clause in the corpus. A run that
    scaffolds nothing says which findings the flag acts on: the two checks that are
    ERRORS under `--strict` are not among them, and a reader who has just been told to
    split something must not read `All clean` as agreement."""
    reqs, members, reqs_dir = ws.reqs, ws.members, ws.reqs_dir
    targets = [(rid, r) for rid, r in sorted(reqs.items())
               if r["meta"].get("status") in LINT_STATUSES
               and (only is None or rid == only)]
    fanin, kids = _fanin_and_kids(reqs)
    errors = warns = 0
    created = []
    for rid, r in targets:
        fs = lint_requirement(rid, r, (members or {}).get(rid), fanin.get(rid), kids.get(rid))
        exempt = set(_as_list(r["meta"].get("lint_exempt")))
        if not fs and not exempt:
            continue
        print("{}   {}".format(rid, _req_file(reqs, rid)))
        if exempt:
            print("  (exempt: {})".format(", ".join(sorted(exempt))))
        for f in fs:
            effective = f["severity"]
            if strict and f["check"] in LINT_STRICT_PROMOTE:
                effective = "error"
            if effective == "error":
                errors += 1; mark = "ERROR"
            else:
                warns += 1; mark = "warn "
            print("  {} {:18} {}".format(mark, f["check"], f["detail"]))
        if decompose and reqs_dir:
            _apply_decompose(fs, reqs_dir, rid, r, reqs, created)
    print("\nreadability: {} non-draft requirement(s) linted · {} error(s) · {} warning(s)".format(
        len(targets), errors, warns))
    if created:
        print("{} draft(s) scaffolded: {}".format(len(created), ", ".join(created)))
        print("note: each split point was chosen by word count, not by obligation \u2014 "
              "read each draft before confirming it.")
    elif decompose:
        # Silence here read as "nothing to split", which is the opposite of the truth when
        # the same run has just printed an over-scoped ERROR. Say which findings the flag
        # acts on, so a no-op is legible as a no-op rather than as a clean bill of health.
        print("nothing scaffolded: `--decompose` acts on `statement-size` findings, and "
              "{} none.".format("this requirement has" if only else "the corpus has"))
    if errors == 0 and warns == 0:
        print("All clean — every linted requirement is well-formed and readable.")
    if strict and errors:
        print("FAIL (--strict): {} structural error(s) (includes promoted structural "
              "warns).".format(errors))
        return 1
    return 0
