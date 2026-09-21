"""Body-text readers shared by every command that prints a requirement: title, intent quote,
bullets, verify hints, context groups.
"""
import os, re

from .sections import (
    CONTRACT_LABELS, _BLOCK_SEP_RE, _atomic_spans, _body_lines, _from_any, _heading_label_is,
    _section_lines
)


def _req_title(body, rid):
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return rid


def _req_file(reqs, rid):  # implements: REQ-MODULEFILE-056
    """Where to open `rid`, as `requirements/<file>`. One file may hold many requirements,
    so the id is NOT the filename: `load_requirements` records the real path per block and
    that is the only thing worth printing at a reader."""
    r = reqs.get(rid) or {}
    p = r.get("path")
    return "requirements/" + (os.path.basename(p) if p else str(rid) + ".md")


def _title(body):  # implements: ARCH-MAP-007
    """The human title from the requirement's first `# ` heading."""
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    return ""


def _distinct_intent(body):  # implements: ARCH-MAP-007  # implements: REQ-MAP-873
    """The intent quote, but only when it says something the Contract does not.

    In the atomic form ([[REQ-ATOMICFORM-053]]) the `>` quote IS the obligation —
    `_atomic_spans` makes the same span both the intent and the single contract
    clause. Emitting it under both names makes every surface print one sentence
    twice: the viewer draws a `Why — Intent` blockquote directly above an identical
    `Description` bullet, and `show` prints the line under the title and again under
    `Contract:`. Measured before this existed: 588 of 646 nodes, 91% of the corpus.

    Returns "" when the quote and the joined contract are the same text, so a
    consumer sees no separate intent rather than a duplicate one. The sectioned form,
    where the quote is real rationale distinct from the clauses, is unaffected."""
    intent = _first_quote(body)
    if not intent:
        return ""
    contract = " ".join(_from_any(_bullets, body, CONTRACT_LABELS)).strip()
    return "" if contract and " ".join(intent.split()) == " ".join(contract.split()) else intent


def _first_quote(body):
    # implements: ARCH-MAP-007  # implements: REQ-MAP-873  # implements: REQ-SHOW-917
    """The requirement's intent: the FIRST contiguous blockquote (the WHY), joined into
    one line. A multi-line `>` WHY (a richer plain-language summary) is gathered whole,
    not truncated to its first line. Fenced code is skipped so a `>` inside a fence
    never counts."""
    out, started = [], False
    for _is_heading, line in _body_lines(body):
        s = line.strip()
        if s.startswith(">"):
            content = s.lstrip(">").strip()
            if content:
                out.append(content)
            started = True
        elif started:            # first non-quote line after the block ends it
            break
    return " ".join(out)


def _section(body, name):  # implements: ARCH-MAP-007
    """One section folded to a single line."""
    # strip only a literal one-time "- " bullet marker, not a lstrip() char class -- a
    # class-lstrip also eats real leading "-"/">" content (e.g. "- -1 means error" must
    # keep its "-1", not become "1 means error")
    return " ".join(s[2:] if s.startswith("- ") else s
                    for s in _section_lines(body, name)
                    if s and not s.startswith("<!--"))


def _section_raw(body, name):  # implements: ARCH-MAP-007
    """Like _section but preserves line breaks + indentation — used for the
    multi-line Given/When/Then acceptance blocks so they read as written."""
    return "\n".join(l for l in _section_lines(body, name, raw=True)
                     if not l.strip().startswith("<!--")).strip()


def _is_label_line(line):  # implements: ARCH-MAP-007  # implements: REQ-MAP-872
    """True when `line` is a clause-group label: a bold-only line at column 0.

    The authoring voice groups clauses under bold labels once a contract passes
    five, and those labels are headings, not prose — folding one into the bullet
    above appends the NEXT group's title to the PREVIOUS group's last clause.

    Position, not marker shape, separates a label from a wrapped clause. A label
    is written flush left; a hanging-indent continuation is indented. Shape alone
    cannot tell them apart: a wrapped line may legitimately open and close on bold
    spans, and matching that as a heading silently deleted the containment half of
    a two-part join predicate. Pass the RAW line — a stripped string makes every
    clause look flush left and collapses the section to headings."""
    return not line[:1].isspace() and re.fullmatch(r"\*\*.+\*\*", line.strip()) is not None


def _bullets(body, name):
    # implements: ARCH-MAP-007  # implements: REQ-ATOMICFORM-053  # implements: REQ-MAP-872
    if name in CONTRACT_LABELS:
        _sp = _atomic_spans(body)
        if _sp:                                    # the atomic statement is the one clause
            # strip whitespace, then only the literal ">" quote-marker chars (never a
            # "> " char class -- that would also eat a real leading ">" in the content,
            # e.g. ">100 requests/sec" losing its ">100"). Mirrors _first_quote.
            return [" ".join(l.strip().lstrip(">").strip() for l in _sp[0]).strip()]
    out, in_comment = [], False
    for line in _section_lines(body, name, raw=True):
        s = line.strip()
        # A multi-line `<!-- ... -->` is one comment, not a first line to skip and
        # then prose to fold into the previous clause (the linter's _contract_clauses
        # already read it that way; the map, `show` and `dupes` did not).
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith("<!--"):
            in_comment = "-->" not in s
            continue
        if _BLOCK_SEP_RE.match(s):
            continue                          # a `---` rule separates; it is not prose
        if s == "-" or s.startswith("- "):
            # `- ` opens a clause; a bare `-flag` continuation does not (the same test
            # _contract_clauses applies, so the two readers agree)
            out.append(s[1:].strip())
        elif _is_label_line(line):
            # A clause-group label — a heading, not prose. Folding it in would append
            # the NEXT group's title to the previous group's last clause, which then
            # leaks into `show`, the map, and the dupes/search bag of words. The test
            # is positional (see _is_label_line), so an indented wrapped clause that
            # merely opens and closes on bold spans still folds below.
            continue
        elif s and out:
            # hanging-indent continuation of the current bullet — fold it back in
            # so multi-line clauses are not truncated to their first physical line.
            out[-1] = (out[-1] + " " + s).strip()
    return out


# `draft` scaffolds a prose capability with the source file's own headings listed
# under this marker as an authoring hint. Until now it printed them INSIDE
# `## Verify intent`, and they are bullets, so every heading was read back as an
# open question: a 21-draft repository reported 103 findings, 82 of them the
# tool's own hint. The scaffold now writes the hint into `## Context`; this cut
# keeps files that were drafted before that fix honest.
_VERIFY_HINT_RE = re.compile(r"authoring hint,\s*not the contract", re.I)


def _verify_bullets(body):  # implements: ARCH-FINDINGS-010  # implements: REQ-FINDINGS-853
    """The open questions in `## Verify intent` — the section's bullets, minus
    anything below a line that declares itself a non-binding authoring hint.

    The single reader every verify-intent consumer goes through (`findings`, the
    map export, `next`, `health`), so the count in the viewer, the CLI and the
    gate summary cannot disagree."""
    section = _section_raw(body, "verify intent")
    if not section:
        return []
    kept = []
    for line in section.splitlines():
        if _VERIFY_HINT_RE.search(line):
            break
        kept.append(line)
    # re-parse through _bullets so bullet shape, fences, label lines and
    # hanging-indent continuations are handled in exactly one place
    return _bullets("## Verify intent\n" + "\n".join(kept), "verify intent")


def _context_group(body, label):  # implements: ARCH-CONTEXT-048  # implements: REQ-CONTEXT-835
    """Bullets under a bold `**<label>**` sub-group inside the consolidated
    `## Context (non-binding)` section — the form `new`'s template scaffolds since
    ADR-0017, replacing the legacy per-topic `## WHAT — Notes` / `## WHERE — Current
    implementation` headings for newly-authored requirements. Reuses the existing
    bold-label grouping convention (`_is_label_line`, already used by Contract
    clause-groups) rather than inventing a second syntax. Callers try the legacy
    heading via `_bullets()` first — this is the fallback for files that never had
    one, so an old-schema requirement is completely unaffected."""
    out, in_context, in_label, fenced = [], False, False, False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if s.lower().startswith("## "):
            in_context = _heading_label_is(s, "context")
            in_label = False
            continue
        if not in_context:
            continue
        if _is_label_line(line):
            in_label = s.strip("*").strip().lower() == label.lower()
            continue
        if not in_label:
            continue
        if s.startswith("-"):
            out.append(s[1:].strip())
        elif s and not s.startswith("<!--") and out:
            out[-1] = (out[-1] + " " + s).strip()
    return out


def _ellipsis(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "\u2026"
