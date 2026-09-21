"""Normative sections of a requirement body: heading lookup, the atomic form, and the binding hash
the drift baseline compares.
"""
import hashlib, re



# ---------- hashing / drift ----------
# The binding-clause section, current name first. `## Description` merged the standalone
# `> WHY:` blockquote and `## WHAT — Contract (normative)` into one section: a reader met
# the same capability described twice, once as rationale and once as obligation, under two
# headings that both said WHAT. The legacy name keeps working forever — a consumer repo's
# existing files are not a migration this tool gets to demand.
CONTRACT_LABELS = ("description", "contract")   # implements: REQ-DESCRIPTION-057

# The acceptance-criteria section, current name first. `## Cases` and its `CASE-N` labels
# replaced `## HOW — Acceptance (= tests)` and `AC-N`: a criterion IS a test case, and the
# old name made the section sound like a sign-off step rather than the cases a reader can
# run. Both names are honoured, and `# verifies: <ID>#AC-N` keeps working — the label is an
# identifier a tag points at, so dropping the old spelling would break every consumer tag
# already written against it.
ACCEPTANCE_LABELS = ("cases", "acceptan")       # implements: REQ-DESCRIPTION-057

# A normative section heading: the canonical `## Description` / `## Cases`, the older
# `## WHAT — Contract …` / `## HOW — Acceptance …`, or a legacy bare
# `## Contract`/`## Acceptance`/`## Input`/`## Output`. Anchored so the keyword must be
# the label (right after `## ` or after a WHAT/HOW — prefix), NOT anywhere in the
# heading — otherwise a commentary heading like `## Notes — contract caveats` would leak
# into the drift hash.
# Built FROM CONTRACT_LABELS/ACCEPTANCE_LABELS (plus the legacy input/output pair those
# tuples never carry) rather than a hand-listed keyword set, so a label added to either
# tuple is automatically recognised here too — a hand-maintained second copy is exactly
# what let `## Cases` (the current spelling, most of this repo's own requirements) go
# unrecognised as a normative heading and silently exclude its criteria from the drift hash.
# prefix set MUST stay in lockstep with _heading_label_is so the drift hash and
# section detection agree on which heading is a normative section (see its docstring)
_NORMATIVE_HEADING_RE = re.compile(
    r"^##\s+(?:(?:what|why|where|how)\s*[—–-]?\s*)?"
    r"(?:" + "|".join(re.escape(n) for n in CONTRACT_LABELS + ACCEPTANCE_LABELS
                       + ("input", "output")) + ")", re.I)


def _body_lines(body):  # implements: ARCH-SECTIONS-068  # implements: REQ-SECTIONS-994
    """Yield `(is_heading, line)` for every line of a requirement body outside a ``` fence.

    The fence is checked BEFORE the heading test, so a `## ` written inside a fenced
    example is code, not a section boundary. Eight readers of these files carried a copy
    of this two-line state machine and `_has_section` carried none — which is why a
    heading inside a fence satisfied the presence check while every reader of that
    section came back empty.
    """
    fenced = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        yield s.startswith("## "), line


def _section_headings(body):  # implements: ARCH-SECTIONS-068  # implements: REQ-SECTIONS-994
    """Every `## ` heading in the body, stripped, in order."""
    return (line.strip() for is_heading, line in _body_lines(body) if is_heading)


def _section_lines(body, names, raw=False):
    # implements: ARCH-SECTIONS-068  # implements: REQ-SECTIONS-994
    """Yield the lines of the FIRST section whose heading label matches any of `names`,
    up to the next `## `.

    `names` is one label or a tuple of them (`CONTRACT_LABELS`, `ACCEPTANCE_LABELS`) —
    current spelling first, legacy spellings after, so a section that was renamed still
    reads. The match is anchored to the label (`_heading_label_is`), so a commentary
    heading that merely mentions the word does not capture the section.

    `raw=True` keeps the physical line, indentation and blank lines included, for the
    Given/When/Then blocks the viewer renders as written; otherwise lines come back
    stripped. What each caller does with those lines — bullets, clauses, prose, criteria —
    is the caller's business; where the section starts and stops is not.
    """
    if isinstance(names, str):
        names = (names,)
    grab = seen = False
    for is_heading, line in _body_lines(body):
        if is_heading:
            if seen:
                return                    # the section ended at the next heading
            seen = grab = any(_heading_label_is(line.strip(), n) for n in names)
            continue
        if grab:
            yield line.rstrip() if raw else line.strip()


def _heading_label_is(heading, name):  # implements: ARCH-CHECK-006
    """True if a `## ` heading's LABEL is `name` (case-insensitive), allowing an
    optional `WHAT`/`HOW` prefix whose dash is optional — so `## WHAT — Contract`,
    `## WHAT Contract`, and bare `## Contract` all match name='contract'. Anchored
    to the label start so a commentary heading like `## Notes — contract caveats`
    does NOT match name='contract'. Keeps section detection (the gate, the linter)
    in agreement with the drift hash (_NORMATIVE_HEADING_RE) — see the silent-drift
    inconsistency this guards against."""
    return bool(re.match(
        r"##\s+(?:(?:what|why|where|how)\s*[—–-]?\s*)?" + re.escape(name.lower()),
        heading.strip().lower()))


_ATOMIC_SCENARIO_RE = re.compile(r"^\s*Scenario\s*:", re.I)
VALID_FORM = {"atomic"}                            # implements: REQ-ATOMICFORM-053


def _atomic_spans(body):  # implements: REQ-ATOMICFORM-053
    """`(statement_lines, scenario_lines)` for a body in the atomic form, else None.

    The atomic form carries no normative `## ` heading at all: a `>` blockquote states the
    single obligation and an unlabelled `Scenario:` block states its acceptance, both sitting
    between the `# ` title and the first `## ` (which begins the auto sections). Both parts
    are required, so a classic body — whose `>` WHY sits above `## WHAT — Contract` and whose
    Given/When/Then lives under a heading — returns None and every existing code path is
    unchanged.

    Detected from the BODY, not from `form: atomic` in the frontmatter, because every
    consumer of these spans (binding_hash, _has_section, _acc_blocks, _bullets) is handed a
    body and no meta. The frontmatter key is validated separately, as documentation."""
    story, scen, in_scen = [], [], False
    for line in body.splitlines():
        st = line.strip()
        if st.startswith("## "):
            break                                  # auto sections end the normative span
        if st.startswith("# "):
            continue                               # the title is not normative
        if _ATOMIC_SCENARIO_RE.match(line):
            in_scen = True
            scen.append(line.rstrip())
            continue
        if in_scen:
            if st:
                scen.append(line.rstrip())
            continue
        if st.startswith(">"):
            story.append(line.rstrip())
    if not story or not scen:
        return None
    return story, scen


_ATOMIC_THEN_RE = re.compile(r"^then\b", re.I)


def _atomic_story_bullets(story_lines):  # implements: REQ-ATOMICFORM-053
    """Count of `- ` facts enumerated inside an atomic story's `>` blockquote.

    Mirrors `_bullets`' `>`-marker normalization (strip, then only the leading
    literal `>` chars, never a `"> "` char class — see the
    `bullets-lstrip-char-class` regression test) so the two never disagree on
    where the marker ends and the content begins. `_bullets` itself JOINS every
    story line into one clause and cannot see these; this is the one reader
    that counts them."""
    n = 0
    for line in story_lines:
        s = line.strip().lstrip(">").strip()
        if s.startswith("- "):
            n += 1
    return n


def _atomic_scenario_then_count(scen_lines):  # implements: REQ-ATOMICFORM-053
    """Count of `Then`-led lines in an atomic Scenario block — one per proven fact.
    A wrapped continuation line of the same step does not open with the
    keyword and is not counted separately."""
    return sum(1 for line in scen_lines if _ATOMIC_THEN_RE.match(line.strip()))


_BLOCK_SEP_RE = re.compile(r"^-{3,}$")


def binding_hash(body):
    # implements: ARCH-DRIFT-003  # implements: REQ-ATOMICFORM-053  # implements: REQ-DRIFT-841
    """Hash only the NORMATIVE sections — the Contract and the Acceptance criteria.
    Everything else (Verify-intent, Notes, Current-implementation, links) is
    commentary and may drift freely without tripping the gate. (Legacy docs used
    Input/Output/Acceptance; those headers are still honored for back-compat.)"""
    keep, grab = [], False
    # `_body_lines`, so a `## Description` written inside a ```-fenced EXAMPLE neither
    # opens a normative span nor closes one. It was the last reader of these files that
    # could not see a fence, and it is the one whose answer is a contract's identity.
    for _is_heading, line in _body_lines(body):
        h = line.strip().lower()
        if h.startswith("## "):
            new_grab = bool(_NORMATIVE_HEADING_RE.match(h))
            if new_grab:
                # section boundary sentinel: keeps Contract and Acceptance distinct so
                # relocating a clause between them is not invisible to the drift hash.
                keep.append("\x1e")
            grab = new_grab
            continue
        if grab and line.strip():
            if line.strip().startswith(">"):
                # `## Description` opens with the intent blockquote — rationale, not an
                # obligation. Hashing it would report DRIFT on a confirmed contract every
                # time someone improved the explanation, which is the opposite of what
                # drift is for. The atomic form draws the same line, keeping `rationale:`
                # in the frontmatter and out of the span. No requirement carried a
                # blockquote inside a normative section when this was added, so no
                # existing hash changes.
                continue
            if _BLOCK_SEP_RE.match(line.strip()):
                # The `--------------------` that separates two requirements in a module
                # file rides along on the block BEFORE it, so it landed inside that
                # block's normative span. Adding a requirement to a module file then
                # changed the PREVIOUS one's hash — a phantom edit that now costs its
                # confirmation (REQ-PROMOTE-974). A separator is structure, never an
                # obligation.
                continue
            # rstrip (not strip): leading indent is structure — unnesting a sub-clause
            # is a real change and must drift.
            keep.append(line.rstrip())
    if not keep:
        # No normative heading: either the atomic form, whose obligation and Scenario ARE the
        # normative span, or a malformed body. Hashing the atomic span is what keeps drift
        # alive — without it every heading-less requirement hashes the empty string and
        # collides with every other, so no content change could ever be detected.
        _sp = _atomic_spans(body)
        if _sp:
            keep = _sp[0] + ["\x1e"] + _sp[1]
    return hashlib.sha256("\n".join(keep).encode()).hexdigest()[:12]


# ---------- commands ----------
def _has_section(body, name):  # implements: ARCH-CHECK-006
    """True if the body has a normative `## ` heading whose LABEL is `name`
    (case-insensitive), e.g. `## WHAT — Verify intent` for name='verify intent'.
    Anchored to the label (see `_heading_label_is`) so a commentary heading that
    merely mentions the word — `## Notes — contract caveats` — does not count as a
    Contract section, and a dash-less `## WHAT Contract` does. This keeps the gate's
    section-presence check in agreement with the drift hash, closing the
    silent-drift gap where a heading passed the gate but produced an empty hash.
    The atomic form (REQ-ATOMICFORM-053) has no normative headings by design; its statement
    and Scenario stand in for both, so it answers True for those two names."""
    if name in CONTRACT_LABELS + ACCEPTANCE_LABELS and _atomic_spans(body):
        return True
    return any(_heading_label_is(h, name) for h in _section_headings(body))


def _has_any(body, names):  # implements: REQ-DESCRIPTION-057
    """True if the body carries any of `names` as a section. One requirement never uses two
    spellings of the same section at once, so 'any' is not a merge — it is 'whichever name
    this file happens to use'."""
    return any(_has_section(body, n) for n in names)


def _from_any(fn, body, names):  # implements: REQ-DESCRIPTION-057
    """`fn(body, name)` for the first of `names` that yields content, else the empty value
    `fn` returns for the first name — so the caller's type (list, str) is preserved."""
    for n in names:
        got = fn(body, n)
        if got:
            return got
    return fn(body, names[0])


def _legacy_schema_ids(reqs):  # implements: REQ-ATOMICFORM-053
    """"Legacy" is the Input/Description/Output triad only. It used to be "no `## Verify
    intent` section", which made the lean form read as legacy and produced one warning
    naming every requirement in the corpus."""
    return [rid for rid in sorted(reqs) if _has_any(reqs[rid]["body"], ("input", "output"))]
