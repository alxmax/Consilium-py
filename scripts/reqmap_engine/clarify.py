"""`clarify`: the questions a requirement has not answered."""
import json, re

from . import MAP_ENGINE_VERSION, config as cfg
from .lintrules import _count_ac
from .sections import ACCEPTANCE_LABELS, CONTRACT_LABELS, _from_any
from .text import _bullets, _ellipsis, _req_title, _section_raw


def blocking_question_rules(reqs):  # implements: REQ-CLARIFY-975
    """{rid: sorted [rule]} for EVERY requirement, empty list included.

    The RULE is the fingerprint, not the prose: two runs of the same defect are the
    same question, and rewording a clause does not invent a new one.

    Requirements with no questions are recorded too, on purpose. Otherwise "absent
    from the snapshot" would mean both "never seen" and "seen, and clean", so a
    requirement going from zero questions to one would be mistaken for a brand-new
    file and silenced — which is exactly the case this check exists to catch."""
    domain = _domain_heads(reqs)
    return {rid: sorted({q["rule"] for q in _clarify_questions(rid, r, reqs, domain)
                         if q["severity"] == "blocking"})
            for rid, r in reqs.items()}


# ---------- clarify: the questions a requirement has not answered yet ----------
# Deterministic and read-only, like every other advisory surface here: it names a
# shape that is under-specified, never a defect, and never blocks. The point is the
# moment BEFORE code exists -- an author writes "the gate reports errors quickly",
# nobody asks what quickly means, and the ambiguity is discovered by the reader of
# the failing test three weeks later.
CLARIFY_HEDGES = (
    "appropriate", "appropriately", "properly", "reasonable", "reasonably", "efficient",
    "efficiently", "robust", "user-friendly", "intuitive", "quickly", "fast", "slow",
    "soon", "as needed", "if necessary", "where possible", "and/or", "etc.", "and so on",
    "optimal", "best-effort", "gracefully", "large", "small", "many", "several", "various",
)
# A case mentioning any of these is exercising a failure path. Absence of ALL of them
# across every case is the signal -- a requirement whose acceptance is pure happy path.
CLARIFY_FAILURE_WORDS = (
    "invalid", "missing", "empty", "absent", "error", "fails", "failure", "refuse",
    "refuses", "reject", "rejects", "corrupt", "malformed", "unreadable", "not found",
    "timeout", "conflict", "duplicate", "unknown", "no ", "none", "cannot", "without",
)
CLARIFY_LIMIT_WORDS = ("at most", "up to", "no more than", "maximum", "max ", "limit",
                       "capped", "bounded", "first ", "top ")
CLARIFY_UNIT_RE = re.compile(
    r"^(ms|s|sec|secs|second|seconds|min|mins|minute|minutes|hour|hours|day|days|"
    r"kb|mb|gb|b|%|percent|char|chars|character|characters|line|lines|file|files|"
    r"byte|bytes|request|requests|item|items|entry|entries|pair|pairs|clause|clauses|"
    r"criterion|criteria|px|em|rem|x)$", re.I)
# A bare number in a clause. Excluded by construction: anything glued to a word or a
# dot (`v4.0.0`, `CASE-2`, `utf-8`), because those are identifiers, not quantities.
_CLARIFY_NUM_RE = re.compile(r"(?<![\w.\-#])(\d+(?:\.\d+)?)\s*([A-Za-z%]*)")


# Every case of ARCH-SEARCH-036 described its input as prose to be matched: terms that
# match, terms that do not, terms that tokenize to nothing, more matches than --top. The
# author varied the QUALITY of one kind of input and never its KIND, so nobody asked what
# happens when the query is an id -- and the answer, for two years, was "the wrong
# requirement". A gate cannot catch that: the code did what the contract said. This asks.
CLARIFY_MONOCULTURE_MIN = 3     # cases needed before the shape means anything
CLARIFY_MONOCULTURE_SHARE = 0.75
CLARIFY_DOMAIN_SHARE = 0.10     # a Given-head this common across the corpus IS the domain
CLARIFY_DOMAIN_MIN = 30         # ...but "common across the corpus" needs a corpus to be common in
_GIVEN_RE = re.compile(r"^\s+Given\s+(.*)$", re.M)
_CLARIFY_ARTICLES = frozenset((
    "a", "an", "the", "one", "two", "three", "no", "any", "some", "its", "their",
    "new", "old", "same", "other", "first", "second", "empty", "valid", "invalid",
    "single", "confirmed", "draft", "deprecated", "stale", "fresh", "missing", "real",
))


def _given_head(text):
    """The kind of thing a Given starts from: its first word that is not an article or a
    leading adjective. Crude on purpose -- it only has to be stable across cases."""
    for w in re.findall(r"[A-Za-z_`][\w`.-]*", text.lower()):
        w = w.strip("`")
        if len(w) < 3 or w in _CLARIFY_ARTICLES:
            continue
        return w
    return ""


def _given_heads(body):
    return [h for h in (_given_head(g) for g in
                        _GIVEN_RE.findall(_from_any(_section_raw, body, ACCEPTANCE_LABELS) or ""))
            if h]


def _domain_heads(reqs):
    """Words that open Givens across the whole corpus are that corpus's subject, not a
    narrow focus: in this repository every other case starts "a requirement ...". Flagging
    those would fire on 18% of the corpus and say nothing."""
    counts = {}
    total = 0
    for r in (reqs or {}).values():
        for h in _given_heads(r["body"]):
            counts[h] = counts.get(h, 0) + 1
            total += 1
    # Below a real sample every word looks dominant: in a two-requirement corpus the one
    # noun under examination is 75% of all Given heads and would exclude itself.
    if total < CLARIFY_DOMAIN_MIN:
        return frozenset()
    return frozenset(w for w, c in counts.items() if c / float(total) >= CLARIFY_DOMAIN_SHARE)


def _clarify_item(rule, severity, where, quote, question, suggest):
    # implements: ARCH-CLARIFY-062  # implements: REQ-CLARIFY-956
    """One open-question record, in the shape `_clarify_questions` emits."""
    return {"rule": rule, "severity": severity, "where": where,
            "quote": quote, "question": question, "suggest": suggest}


def _clause_questions(clauses):
    # implements: ARCH-CLARIFY-062  # implements: REQ-CLARIFY-956
    """Per-clause advisory questions: vague terms, bare numbers without a unit,
    unbounded quantities, and ambiguous actors."""
    out = []
    for i, c in enumerate(clauses, 1):
        low = c.lower()
        where = "clause {}".format(i)
        for w in CLARIFY_HEDGES:
            if w in low:
                out.append(_clarify_item(
                    "vague-term", "advisory", where, c,
                    'What is the measurable threshold behind "{}"?'.format(w.strip()),
                    "Replace it with a number and a unit, or with the observable "
                    "condition it stands for."))
                break               # one hedge per clause is enough to start the conversation
        m = _CLARIFY_NUM_RE.search(c)
        if m and not CLARIFY_UNIT_RE.match(m.group(2) or ""):
            out.append(_clarify_item(
                "number-without-unit", "advisory", where, c,
                'What unit is "{}" in?'.format(m.group(1)),
                "State the unit beside the number so a test can assert it."))
        if (" all " in " " + low or low.startswith("all ") or " every " in low or " any " in low) \
                and not any(w in low for w in CLARIFY_LIMIT_WORDS):
            out.append(_clarify_item(
                "unbounded-quantity", "advisory", where, c,
                "Is there an upper bound, and what happens when it is reached?",
                "Name the limit, or say explicitly that there is none."))
        if low.startswith("it ") or " the system " in low:
            out.append(_clarify_item(
                "ambiguous-actor", "advisory", where, c,
                "Who performs this -- which command or component?",
                "Name the subject the title names, so the clause reads on its own."))
    return out


def _clause_case_gap_question(clauses, n_cases):
    # implements: ARCH-CLARIFY-062  # implements: REQ-CLARIFY-956
    """ONE question about the gap when clauses outnumber cases, not one per tail
    clause. The count is all this check knows: it compares two numbers and never
    reads a case to see which clause it proves. Accusing clauses n_cases+1.. by
    position was therefore a guess dressed as a finding, and a wrong one whenever
    an early clause is the uncovered one — e.g. a clause that delegates its cases
    to another requirement, which the counter cannot see. It sent the reader to
    rewrite a clause that already had its case."""
    if not (clauses and n_cases and len(clauses) > n_cases):
        return []
    gap = len(clauses) - n_cases
    return [_clarify_item(
        "clause-without-case", "advisory", "Cases", "",
        "{} clause(s) have no case: there are {} clauses and {} cases. This check "
        "counts, it does not read, so it cannot say WHICH — that is the part only "
        "you can do.".format(gap, len(clauses), n_cases),
        "Walk the clauses and find the one no case proves. Add a case for it, fold "
        "it into an existing case, or move it out of the binding list if another "
        "requirement already carries its cases.")]


def _monoculture_question(body, reqs, domain):
    # implements: ARCH-CLARIFY-062  # implements: REQ-CLARIFY-956
    """The one question about every case starting from the same kind of input,
    unless that input IS the corpus's domain (see `_domain_heads`)."""
    heads = _given_heads(body)
    if len(heads) < CLARIFY_MONOCULTURE_MIN:
        return []
    counts = {}
    for h in heads:
        counts[h] = counts.get(h, 0) + 1
    common = max(sorted(counts), key=lambda k: counts[k])
    share = counts[common] / float(len(heads))
    if domain is None:
        domain = _domain_heads(reqs)
    if share >= CLARIFY_MONOCULTURE_SHARE and common not in domain:
        return [_clarify_item(
            "case-monoculture", "advisory", "Cases", "",
            'Every case starts from the same kind of input ("{}"). What is the '
            'other kind a caller would supply?'.format(common),
            "Add one case written from the caller's side, not the implementation's.")]
    return []


def _clarify_questions(rid, r, reqs=None, domain=None):
    # implements: ARCH-CLARIFY-062  # implements: REQ-CLARIFY-956
    """The open questions one requirement has not answered, as records:
    {rule, severity, where, quote, question, suggest}. Deterministic -- the same
    requirement always yields the same list, in the same order. `blocking` means the
    requirement cannot be implemented as written; everything else is advice.
    `domain` is `_domain_heads(reqs)`, passed in by the corpus-wide callers so it is
    read once rather than recomputed per requirement (it was 90% of a `sync`'s
    question pass, and quadratic in the corpus)."""
    body = r["body"]
    clauses = _from_any(_bullets, body, CONTRACT_LABELS)
    cases_raw = _from_any(_section_raw, body, ACCEPTANCE_LABELS) or ""
    cases_low = cases_raw.lower()
    n_cases = _count_ac(body)
    out = []

    if not clauses:
        out.append(_clarify_item(
            "no-contract", "blocking", "Description", "",
            "What is this requirement's binding obligation? The Description carries no clause.",
            "Write one statement per obligation, present tense, naming the subject."))
    if n_cases == 0:
        out.append(_clarify_item(
            "no-cases", "blocking", "Cases", "",
            "What observable behaviour proves this requirement holds? No labelled case is present.",
            "Add `CASE-1` with Given / When / Then, one per clause."))

    out.extend(_clause_questions(clauses))
    out.extend(_clause_case_gap_question(clauses, n_cases))

    if n_cases and not any(w in cases_low for w in CLARIFY_FAILURE_WORDS):
        out.append(_clarify_item(
            "no-failure-case", "advisory", "Cases", "",
            "What happens on the failure path -- missing input, invalid value, nothing to do?",
            "Add one case for the way this can go wrong; it is the case implementations skip."))

    out.extend(_monoculture_question(body, reqs, domain))

    if len(clauses) > cfg.LINT_AC_MAX:
        out.append(_clarify_item(
            "over-scoped", "advisory", "Description", "",
            "This requirement carries {} clauses (advisory limit {}). Which of "
            "them is a separate requirement?".format(len(clauses), cfg.LINT_AC_MAX),
            "Split the ones that could change for a different reason."))
    return out


def cmd_clarify(reqs, cap_id, as_json=False):
    # implements: ARCH-CLARIFY-062  # implements: REQ-CLARIFY-957
    """Print the open questions for one requirement (or the whole corpus's blocking
    ones when no id is given). Advisory: always exit 0, writes nothing, and is never
    a gate rule -- an unanswered question is a conversation, not a build failure."""
    if cap_id and cap_id not in reqs:
        print("no requirement with id {} (expected requirements/{}.md)".format(cap_id, cap_id))
        return 1
    ids = [cap_id] if cap_id else sorted(reqs)
    items = []
    domain = _domain_heads(reqs)
    for rid in ids:
        qs = _clarify_questions(rid, reqs[rid], reqs, domain)
        if not cap_id:
            qs = [q for q in qs if q["severity"] == "blocking"]
        if qs:
            items.append({"id": rid, "title": _req_title(reqs[rid]["body"], rid), "questions": qs})
    if as_json:
        print(json.dumps({"engine_version": MAP_ENGINE_VERSION,
                          "advisory": ("Deterministic open questions. Answer them in "
                                       "the requirement, not in code; nothing here is "
                                       "a gate rule."),
                          "requirements": items}, indent=2, ensure_ascii=False))
        return 0
    if not items:
        print("{}: nothing unclear that this check can see.".format(cap_id or "corpus"))
        print("  next: reqmap.py gate --show {}".format(cap_id or "<ID>"))
        return 0
    for it in items:
        blocking = [q for q in it["questions"] if q["severity"] == "blocking"]
        print("{} · {}".format(it["id"], it["title"]))
        print("{} open question(s){}".format(
            len(it["questions"]), " — {} blocking".format(len(blocking)) if blocking else ""))
        n = 0
        for sev in ("blocking", "advisory"):
            group = [q for q in it["questions"] if q["severity"] == sev]
            if not group:
                continue
            print("\n{}".format(sev.upper()))
            for q in group:
                n += 1
                print(" {:>2}. [{}] {}".format(n, q["rule"], q["where"]))
                if q["quote"]:
                    print("     \"{}\"".format(_ellipsis(q["quote"], 92)))
                print("     {}".format(q["question"]))
                print("     -> {}".format(q["suggest"]))
        print("")
    if cap_id:
        print("Answer them in {}.md, then: reqmap.py gate --show {}".format(cap_id, cap_id))
    return 0
