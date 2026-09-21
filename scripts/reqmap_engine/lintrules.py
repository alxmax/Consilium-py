"""The lint checks themselves: prose, sections, acceptance, shape, terms, graph, and the thresholds
they read.
"""
import os
import re

from . import config as cfg
from .acceptance import _acc_blocks
from .model import _as_list
from .sections import (
    ACCEPTANCE_LABELS, CONTRACT_LABELS, _atomic_scenario_then_count, _atomic_spans,
    _atomic_story_bullets, _from_any, _has_any, _section_lines
)
from .text import _bullets, _is_label_line, _section_raw


def _oversize(rid, r, threshold=None):
    # implements: ARCH-DECOMPOSE-050  # implements: ARCH-NEXT-013
    """True when a requirement is over the shared AC-count threshold and neither
    scoped out by status nor exempted from the check.

    One predicate, two callers (`cmd_next`'s Granularity bucket and
    `lint_requirement`'s `ac-count-high` check) - they disagreed before: `next`
    iterated every status with no exempt check, `lint` scoped to `LINT_STATUSES`
    and honored `lint_exempt`, so the two commands could and did report different
    sets for the same corpus. Scoped to `LINT_STATUSES` like every other lint
    check (drafts are TODO stubs, not yet-scoped contracts - pinned down
    explicitly per Control's mandatory dissent, not left to fall out of an
    unscoped iteration by accident) and reads `lint_exempt` with the same
    `_as_list` handling `lint_requirement` already uses, so a scalar-string
    exemption behaves identically to a one-item list here too."""
    meta = r.get("meta") or {}
    if meta.get("status") not in LINT_STATUSES:
        return False
    if threshold is None:
        threshold = cfg.LINT_AC_MAX
    if _count_ac(r.get("body", "")) <= threshold:
        return False
    return "ac-count-high" not in set(_as_list(meta.get("lint_exempt")))


# ---------- lint (readability / structure of requirement prose) ----------
# Makes the SKILL.md "Audience & writing level" rules mechanical so requirements
# stay easy to understand. Scoped narrowly to keep false positives near zero: only
# non-draft requirements (drafts are TODO stubs), only the Contract and Acceptance
# sections (Notes may stay dense by design). Jargon-before-definition is deliberately
# NOT checked in v1 — without a term dictionary it is too false-positive-prone on
# prose that carries code references.
LINT_STATUSES = {"baseline", "in-progress", "implemented", "confirmed"}
# Checks promoted from warn→error under `--strict` (structural, not style). One
# constant, because `gate` runs the lint strict and `sync`'s summary counted errors
# without the promotion — a corpus failing `gate` on `over-scoped` had a silent sync.
LINT_STRICT_PROMOTE = frozenset({"ac-count-high", "over-scoped",
                                 "atomic-bullet-then-mismatch", "atomic-story-overlong"})
LINT_ATOMIC_STORY_BULLETS_MAX = 3   # an atomic story quote may enumerate up to this many
                               # is the inverse of a bus ('layer-mismatch', warn). Three, because
                               # this corpus's largest fan-out is three and none of its bus
                               # requirements has zero fan-in — so the check is silent here and
                               # fires on the shape that produced it (0 in / 12 out).
# Closed list of vague QUALITY words that make a normative bullet un-testable
# (IEEE 29148 "Unambiguous"). Deliberately excludes size words (high/low/small/many)
# and weak modals — they are too often legitimately precise in this domain, and a
# false positive trains authors to ignore lint. Only words with no testable meaning.
LINT_VAGUE_TERMS = frozenset({
    "appropriate", "appropriately", "adequate", "adequately", "sufficient",
    "sufficiently", "reasonable", "reasonably", "robust", "robustly", "flexible",
    "efficient", "efficiently", "optimal", "scalable", "performant", "fast", "slow",
    "quick", "quickly", "easy", "easily", "simple", "user-friendly", "seamless",
    "seamlessly", "intuitive", "various", "etc",
    # Temporal terms, added 2026-09-15. Same rule as the quality words above: a
    # deadline with no unit is not testable ("sent promptly", "retried periodically").
    # The obvious candidates `immediately`, `later` and `recent` are deliberately NOT
    # here — measured over this corpus they scored 12 hits and 12 false positives,
    # every one of them positional rather than temporal ("a block starts at a `---`
    # line immediately followed by `id:`", "a later block", "the most recent commit").
    # The eight below scored zero hits: silent here, firing on the shape that produced
    # them, which is the same bargain LINT_FANOUT_BANDS records above.
    "promptly", "timely", "periodically", "regularly", "frequently",
    "soon", "eventually", "shortly",
})
# Redundant normative modals: the Contract section opens with "Every line in this
# section is binding.", so "shall"/"must" on each clause is dead weight — and in a
# non-English requirement corpus "shall" is also a stray anglicism (see Audience &
# writing level, rule 3). Closed list, checked as a whole word, case-insensitive.
LINT_MODAL_WORDS = frozenset({"shall", "must"})
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z-]*")


def _prose_lint(body, name):  # implements: ARCH-LINT-014  # implements: REQ-LINT-864
    """Yield the prose text lines under the FIRST `## ` heading whose text contains
    `name`, up to the next `## `. A bullet's leading `- ` is stripped so its text is
    linted as a sentence. Non-prose lines — headings, table rows, blockquotes, and
    anything inside a ``` fence — are skipped so the linter never flags code or
    markup as unreadable. Fence state is tracked BEFORE heading detection, so a
    `## ` comment inside a fenced block is treated as code, not a section boundary."""
    out = []
    for s in _section_lines(body, name):
        if not s or s.startswith(("|", ">", "#")):
            continue
        if s == "-" or s.startswith("- "):   # a real bullet marker (not '--strict' / '-5')
            s = s[1:].strip()
        if s:
            out.append(s)
    return out


def _sentences(text):  # implements: ARCH-LINTCHECKS-025  # implements: REQ-LINTCHECKS-865
    """Split a prose line into sentences on '.', '!', '?' boundaries. Crude but
    deterministic — enough to count words per sentence for the length check."""
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]


def _clip(s, n=60):  # implements: ARCH-LINT-014  # implements: REQ-LINT-864
    """Shorten a snippet for one-line finding output."""
    return s if len(s) <= n else s[:n - 1] + "…"


def _clause_words(text):
    # implements: ARCH-ATOMICITY-049  # implements: REQ-ATOMICITY-824
    # implements: REQ-ATOMICITY-825
    """Word count for a Contract clause, counting each backticked span as one word.
    A clause carrying a long code sample is short prose, not a long statement. The span
    collapses to a bare token with no padding spaces: " x " would split trailing punctuation
    (`code`. -> "x" ".") into a second word and inflate every such clause by one."""
    return len(re.sub(r"`[^`]*`", "x", text).split())


def _contract_clauses(body):
    # implements: ARCH-ATOMICITY-049  # implements: REQ-ATOMICITY-824
    # implements: REQ-ATOMICITY-825
    """Yield (n, text) per clause of the Contract section, n 1-based.

    A clause is one bullet at ANY indent — a nested sub-bullet is its own clause because
    it states its own obligation — with its wrapped continuation lines joined back on.
    This is deliberately not `_prose_lint`, which yields physical LINES: these files are
    hard-wrapped near 95 columns, so a 90-word clause reaches `_prose_lint` as six ~15-word
    lines and no per-line ceiling can ever see it. Bold group labels, table rows, block
    quotes, fenced code and HTML comments are not clauses and are skipped."""
    out, cur, in_comment = [], None, False

    def flush():
        if cur is not None:
            out.append(cur)

    for s in _section_lines(body, CONTRACT_LABELS):
        if in_comment:                       # glossary comments are guidance, not clauses
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--"):
            if "-->" not in s:
                in_comment = True
            continue
        if not s or s.startswith(("|", ">", "#")) or (s.startswith("**") and s.endswith("**")):
            flush(); cur = None
            continue
        if s == "-" or s.startswith("- "):
            flush()
            cur = s[1:].strip()
        elif cur is not None:
            cur += " " + s
    flush()
    return list(enumerate([c for c in out if c], 1))


def _count_ac(body):
    """Count acceptance criteria in the HOW — Acceptance section.
    Handles both bullet-list ACs (- ...) and labeled AC blocks (AC-N ...).
    Delegates to `_acc_blocks`, the single parser of that section, so the count
    `lint` and `next` reason about cannot drift from the criteria the map emits."""
    return len(_acc_blocks(body))


def _sections_lint(body):  # implements: ARCH-LINTCHECKS-025  # implements: REQ-LINT-863
    """The two load-bearing sections: present at all, and carrying anything."""
    findings = []
    # structural (error): a non-draft must carry both load-bearing sections
    if not _has_any(body, CONTRACT_LABELS):
        findings.append({"severity": "error", "check": "missing-section",
                         "detail": "no '## Description' section"})
    if not _has_any(body, ACCEPTANCE_LABELS):
        findings.append({"severity": "error", "check": "missing-section",
                         "detail": "no '## Cases' section"})
    # empty-section (warn): the heading is present but carries no clauses/criteria — it
    # passes `missing-section` yet documents nothing (and `ac-count-low` skips the zero
    # case). Precise zero/non-zero test, so near-zero false positive.
    if _has_any(body, CONTRACT_LABELS) and not _from_any(_bullets, body, CONTRACT_LABELS):
        findings.append({"severity": "warn", "check": "empty-section",
                         "detail": "'## Description' section present but has no clauses"})
    if _has_any(body, ACCEPTANCE_LABELS) and _count_ac(body) == 0:
        findings.append({"severity": "warn", "check": "empty-section",
                         "detail": "'## Cases' section present but has no criteria"})
    return findings

def _readability_lint(body):  # implements: ARCH-LINTCHECKS-025  # implements: REQ-LINT-863
    """Readability of the normative prose: joins per line, anonymous subjects,
    sentence and clause length, and one obligation per clause."""
    findings = []
    # prose readability (warn): only on the Contract + Acceptance sections
    for name in CONTRACT_LABELS + ACCEPTANCE_LABELS:
        for ln in _prose_lint(body, name):
            low = ln.lower()
            # Every line in a Contract/Acceptance section is normative by virtue of the
            # section it sits in, so the join count applies to all of them. This used to be
            # gated on `"shall" in low or "must" in low`, which made the check silent for the
            # plain present-tense voice — a clarity rule keyed on a magic word misses clauses.
            joins = len(re.findall(r"\b(?:and|or)\b", low))
            if joins >= cfg.LINT_STACKED_CONNECTORS:
                findings.append({
                    "severity": "warn", "check": "stacked-conditions",
                    "detail": "{} 'and'/'or' joins in one normative line: {}".format(
                        joins, _clip(ln))})
            # Contract only: a clause whose subject is a bare "It" forces the reader to hold
            # the requirement's title in their head to know what is being promised. Name it.
            # Acceptance prose is exempt — a Then clause saying "it returns …" reads fine.
            if name in CONTRACT_LABELS and re.match(r"^It\s+[a-z]", ln):
                findings.append({
                    "severity": "warn", "check": "anonymous-subject",
                    "detail": "clause opens with an unnamed 'It' — name the subject: {}".format(
                        _clip(ln))})
    # statement atomicity (warn): a Contract bullet spanning more than
    # LINT_CLAUSE_SENTENCES sentences packs several statements into one clause (split it).
    # Sentence COUNT is the only dimension here — `long-sentence` owns words per sentence
    # and `statement-size` owns words per clause — so the three checks never flag the same
    # line for the same reason, and a correct two- or three-sentence clause stays silent.
    # Read whole CLAUSES, not the physical lines `_prose_lint` yields. These files wrap
    # near 95 columns, so a line-based count can never see a clause that spans several
    # lines — which is why this check reported 0 corpus-wide while measuring the wrong
    # unit. Measured before the switch: 0 of 625 non-draft clauses hold more than three
    # sentences, so widening the unit changes nothing the check says today.
    clauses = _contract_clauses(body)
    for _cn, ln in clauses:
        sents = _sentences(ln)
        if len(sents) > cfg.LINT_CLAUSE_SENTENCES:
            findings.append({
                "severity": "warn", "check": "statement-too-long",
                "detail": "statement spans {} sentences (>{}): {}".format(
                    len(sents), cfg.LINT_CLAUSE_SENTENCES, _clip(ln))})
    # statement-size (warn, advisory): a Contract clause well past the length a single
    # obligation normally needs. Measured per CLAUSE, not per line — see _contract_clauses.
    # Advisory by contract: exceeding the threshold never makes a clause invalid and never
    # asserts that it holds two obligations, which the engine cannot observe
    # (ARCH-ATOMICITY-049). The finding carries clause_n/clause_text so `--decompose` can
    # scaffold from the same clause without re-parsing.
    for _n, _clause in clauses:
        _cw = _clause_words(_clause)
        if _cw > cfg.LINT_STATEMENT_WORDS:
            findings.append({
                "severity": "warn", "check": "statement-size",
                "clause_n": _n, "clause_text": _clause,
                "detail": "clause {} is {} words (>{}) \u2014 re-read it for "
                          "decomposition: {}".format(
                              _n, _cw, cfg.LINT_STATEMENT_WORDS, _clip(_clause))})
    return findings

def _acceptance_lint(body, r, rid):  # implements: ARCH-LINTCHECKS-025  # implements: REQ-LINT-863
    """The acceptance criteria: how many there are, and whether the atomic form
    proves every fact its story claims."""
    findings = []
    # ac count (warn): too few = under-specified; too many = over-scoped
    if _has_any(body, ACCEPTANCE_LABELS):
        ac_n = _count_ac(body)
        # An atomic requirement holds ONE obligation, so one criterion is the correct
        # number, not an under-specified one. LINT_AC_MIN guards a dossier.
        if 0 < ac_n < cfg.LINT_AC_MIN and not _atomic_spans(body):
            findings.append({
                "severity": "warn", "check": "ac-count-low",
                "detail": "{} AC (< {}): requirement may be under-specified".format(
                    ac_n, cfg.LINT_AC_MIN)})
        elif _oversize(rid, r):
            findings.append({
                "severity": "warn", "check": "ac-count-high",
                # Name a remedy that EXISTS. The finding used to say only "consider
                # splitting", while `lint_exempt:` was documented as the one-line escape
                # hatch — so the cheapest visible action was to silence it, and that is
                # what readers (and assistants) reached for. Naming `--decompose` was the
                # fix for that, and it named the wrong thing: `--decompose` acts on
                # `statement-size` findings only (see the NOTE above `cmd_lint`), so an
                # author running it on an over-scoped requirement got `All clean` and no
                # files, from a command the gate had just called an error. A remedy that
                # no-ops is worse than no remedy: it sends the reader back to
                # `lint_exempt:`, which the skill says must never be the reflex.
                "detail": "{} AC (> {}): several capabilities in one requirement \u2014 move "
                          "criteria onto the child requirements that own them until {} or "
                          "fewer remain (`--decompose` does not cover this check)".format(
                              ac_n, cfg.LINT_AC_MAX, cfg.LINT_AC_MAX)})
    # atomic bullet/Then parity (warn, --strict-promotable): the atomic form's `>` story
    # quote may enumerate up to LINT_ATOMIC_STORY_BULLETS_MAX facts, but every existing
    # signal is blind to whether each one is actually proven — `_count_ac` counts the ONE
    # Scenario regardless of how many facts the story bundles into it, and `ac-count-low`
    # explicitly exempts the atomic form. A 3-bullet story with a single `Then` passed every
    # check that existed before this one (the REQ-FANOUT-391/392 shape: a leaf asserted
    # behavior its parent forbade, and nothing caught it).
    _sp = _atomic_spans(body)
    if _sp:
        _story_lines, _scen_lines = _sp
        _bn = _atomic_story_bullets(_story_lines)
        _tn = _atomic_scenario_then_count(_scen_lines)
        if _bn > LINT_ATOMIC_STORY_BULLETS_MAX:
            findings.append({
                "severity": "warn", "check": "atomic-story-overlong",
                "detail": "{} bullets in the story quote (> {}): no longer a single "
                          "obligation — split it into its own requirements".format(
                              _bn, LINT_ATOMIC_STORY_BULLETS_MAX)})
        elif _bn > 1 and _bn != _tn:
            findings.append({
                "severity": "warn", "check": "atomic-bullet-then-mismatch",
                "detail": "{} bullets in the story quote but {} 'Then' line(s) in the "
                          "Scenario — each enumerated fact needs its own Then".format(
                              _bn, _tn)})
    return findings

def _shape_lint(rid, r, body, children):
    # implements: ARCH-LINTCHECKS-025  # implements: REQ-LINT-863
    """Corpus shape: a requirement over both ceilings at once, and a parent whose
    fan-out sits outside the band for its level."""
    findings = []
    # cohesion (warn): over BOTH the contract and acceptance ceilings at once is a strong
    # "several capabilities bundled into one" signal — each contract clause is a separate
    # binding, each AC an independent failure mode. Requiring BOTH axes (a composite) keeps
    # false positives near zero: a large-but-cohesive capability rarely maxes both. Advisory
    # only — it surfaces split candidates; the split decision stays with the human.
    if _has_any(body, CONTRACT_LABELS) and _has_any(body, ACCEPTANCE_LABELS):
        # Scope units, not sentences. A contract that groups its clauses under bold labels
        # states one facet per group, so the group count is what says how much the
        # requirement promises; the clause count only says how finely the prose was split.
        # Counting clauses alone punished the atomic voice — one obligation per bullet
        # multiplies bullets without widening scope at all. Ungrouped contracts fall back
        # to the clause count, which is what this check has always used.
        # Counted off _section_raw, not _prose_lint: _prose_lint strips each line, and a
        # label is defined by sitting at column 0 (see _is_label_line). Given stripped
        # input every wrapped clause that opens and closes on bold spans counts as a
        # group, inflating contract_n — and `over-scoped` is an ERROR under --strict, so
        # that miscount fails CI on a requirement that is not over-scoped.
        groups = sum(1 for ln in _from_any(_section_raw, body, CONTRACT_LABELS).split("\n")
                     if _is_label_line(ln))
        contract_n = groups or len(_from_any(_bullets, body, CONTRACT_LABELS))
        ac_count = _count_ac(body)
        if contract_n > cfg.LINT_CONTRACT_MAX and ac_count > cfg.LINT_AC_MAX:
            findings.append({
                "severity": "warn", "check": "over-scoped",
                # The trigger is an AND, so clearing EITHER number clears the finding —
                # which is genuinely useful to an author and was nowhere in the output.
                # Same correction as `ac-count-high`: `--decompose` cannot act on this.
                "detail": "{} contract {} + {} AC (both over {}/{}): likely several "
                          "capabilities \u2014 bring either number under its ceiling and this "
                          "clears (`--decompose` does not cover this check)".format(
                              contract_n, "groups" if groups else "clauses",
                              ac_count, cfg.LINT_CONTRACT_MAX, cfg.LINT_AC_MAX)})
    # fan-out (warn): a parent in the `satisfies:` hierarchy normally carries 5-20 children.
    # Too few and the level buys no grouping; too many and it is a bucket, not a level.
    # Counted on the satisfies graph, NOT on `depends_on` — the two are different axes, and
    # `depends_on` depth here maxes out at 3, so a band of 5-20 read against it would flag
    # every requirement in the corpus. A leaf (zero children) is skipped: it is not a
    # malformed parent, it is not a parent at all.
    # The band depends on which level the parent sits at — see LINT_FANOUT_BANDS. A parent
    # declaring no level keeps the uniform band it always had.
    _lo, _hi = cfg.LINT_FANOUT_BANDS.get(r["meta"].get("level"),
                                         (cfg.LINT_FANOUT_MIN, cfg.LINT_FANOUT_MAX))
    if children:
        if _lo is not None and children < _lo:
            findings.append({
                "severity": "warn", "check": "fan-out",
                "detail": "{} requirement(s) satisfy this one (below {}): too few to be "
                          "a level".format(children, _lo)})
        elif children > _hi:
            findings.append({
                "severity": "warn", "check": "fan-out",
                "detail": "{} requirement(s) satisfy this one (over {}): too many — "
                          "split it".format(children, _hi)})
    return findings

def _terms_lint(body):  # implements: ARCH-LINTCHECKS-025  # implements: REQ-LINT-863
    """Words that make a clause untestable: vague quality terms, and a modal the
    section header already supplies."""
    findings = []
    # vague terms (warn): a Contract bullet using a non-testable quality word is
    # ambiguous (IEEE 29148). Code spans (`backticked`) are stripped first so a
    # backticked identifier is never flagged. One finding per distinct term.
    # Iterates CONTRACT_LABELS (current `## Description` first, legacy `## Contract`
    # still honoured) rather than the literal string "contract" — a hardcoded legacy
    # label here left this check dead on every requirement using the current heading.
    seen_vague = set()
    for name in CONTRACT_LABELS:
        for ln in _prose_lint(body, name):
            bare = re.sub(r"`[^`]*`", " ", ln)
            for w in _WORD_RE.findall(bare):
                lw = w.lower()
                if lw in LINT_VAGUE_TERMS and lw not in seen_vague:
                    seen_vague.add(lw)
                    findings.append({
                        "severity": "warn", "check": "vague-term",
                        "detail": "vague word '{}' (no testable meaning): {}".format(
                                w, _clip(ln))})
    # redundant modal (warn): "shall"/"must" on a Contract clause is either dead weight
    # (the section header already binds every line) or a stray English modal dropped into
    # a non-English clause. Same one-finding-per-distinct-term shape as vague-term, above.
    # Same CONTRACT_LABELS iteration as vague-term, above, for the same reason.
    seen_modal = set()
    for name in CONTRACT_LABELS:
        for ln in _prose_lint(body, name):
            bare = re.sub(r"`[^`]*`", " ", ln)
            for w in _WORD_RE.findall(bare):
                lw = w.lower()
                if lw in LINT_MODAL_WORDS and lw not in seen_modal:
                    seen_modal.add(lw)
                    findings.append({
                        "severity": "warn", "check": "redundant-modal",
                        "detail": "redundant modal '{}' (the Contract header already binds "
                                  "every line — use plain present tense): {}".format(
                                      w, _clip(ln))})
    return findings

def _graph_lint(r, member_list, fanin):
    # implements: ARCH-LINTCHECKS-025  # implements: REQ-LINT-863
    """What the requirement looks like from outside: how far its members are spread,
    and whether its declared layer matches its fan-in."""
    findings = []
    # file-spread (warn): a requirement whose implements members span many distinct
    # DIRECTORIES is architecturally diffuse — a cohesion axis the intent-axis checks
    # (over-scoped, ac-count) cannot see. It counted files while the engine was one file; once
    # it became one module per capability (ADR-0035), a behaviour computed in one module,
    # reported by `audit` and exported by `mapjson` spanned three files by design, and 38 of
    # this corpus's warnings said nothing else. Directories are the unit a reader navigates
    # (ADR-0042). Needs member_list; skipped when not supplied.
    if member_list:
        impl_dirs = {os.path.dirname(m[1].replace("\\", "/"))
                     for m in member_list if m and m[0] == "implements"}
        if len(impl_dirs) >= cfg.LINT_FILE_SPREAD_MAX:
            findings.append({
                "severity": "warn", "check": "file-spread",
                "detail": "implements span {} directories (>= {}): capability may be diffuse — "
                          "confirm cohesion or split".format(
                              len(impl_dirs), cfg.LINT_FILE_SPREAD_MAX)})
    # layer-mismatch (warn): `bus` is DEFINED by fan-in ("foundation, high fan-in"),
    # and nothing checked it. A requirement with no dependents and many dependencies is
    # the exact inverse — a roof labelled a foundation. It reads as bus in the map, in
    # `next`, and in every diagnostic built on the layer, so the mislabel misleads
    # precisely where the layer is supposed to help. `layer: aggregate` is the label
    # such a requirement wants.
    if (fanin is not None and r["meta"].get("layer") == "bus"
            and fanin == 0
            and len(_as_list(r["meta"].get("depends_on"))) >= cfg.LINT_BUS_FANOUT_MIN):
        findings.append({
            "severity": "warn", "check": "layer-mismatch",
            "detail": "layer: bus but nothing depends on it and it depends on {} "
                      "requirement(s) — that is a roof, not a foundation; consider "
                      "`layer: aggregate` or `feature`".format(
                          len(_as_list(r["meta"].get("depends_on"))))})
    return findings
