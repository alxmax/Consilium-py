"""`RM035`: a number a prose document states about the corpus, re-measured.

A document that says "236 requirements in total" is asserting something the engine can
count, and nothing was counting it. This repository's own `CLAUDE.md` drifted to four
wrong counts while every check passed — the failure the whole tool exists to prevent,
reproduced in the file every contributor reads first.

Opt-in by construction, in two independent ways: a repository whose documents carry no
`<!--reqmap:...-->` marker gets no finding, and `DOC_CLAIM_FILES` names which documents
are read at all. So a consumer repo that wants nothing here pays one `os.path.join` and
one failed `open`, and a consumer that wants it writes one marker. Warn, never error: a
stale sentence is a documentation defect, not a broken link.
"""
import io
import os
import re

from . import config as cfg
from .model import gate_rule

# `<!--reqmap:total-->263 requirements in total` — the marker names the KIND of claim and
# the first integer after it is the claimed value. The marker LEADS rather than trails so
# the sentence still reads as prose and the number stays where an author would write it.
CLAIM_RE = re.compile(r"<!--\s*reqmap:([a-z]+(?::[a-z-]+)?)\s*-->[^\d<]{0,24}?(\d+)")

_AXES = ("level", "layer")


def corpus_counts(reqs):
    """Every number a marker may claim, keyed by its marker kind.

    `total` and `files` are absolute; `level:code` / `layer:bus` and their siblings are
    one key per value actually present. `files` counts DISTINCT REQUIREMENT FILES through
    the parser, never a directory glob: `requirements/` also holds `_map.md`, `_findings.md`
    and `_ai_review.md`, so a glob over-counts by three and the wrong number is the kind
    this rule exists to catch.
    """
    named = (r.get("path") for r in reqs.values())
    counts = {"total": len(reqs),
              "files": len({os.path.basename(q) for q in named if q})}
    for axis in _AXES:
        for r in reqs.values():
            value = r["meta"].get(axis)
            if value:
                key = "{}:{}".format(axis, value)
                counts[key] = counts.get(key, 0) + 1
    return counts


def doc_claims(text):
    """The `(kind, claimed, line_no)` of every marked claim in `text`, in source order."""
    return [(m.group(1), int(m.group(2)), text.count("\n", 0, m.start()) + 1)
            for m in CLAIM_RE.finditer(text)]


def _measured(counts, kind):
    """The measured value for a marker kind, or None when the engine cannot count it.

    A known axis with no members answers 0 rather than None: `level:system` on a corpus
    that declares no system rung is a claim of zero, not an unknown kind.
    """
    if kind in counts:
        return counts[kind]
    return 0 if kind.split(":")[0] in _AXES else None


@gate_rule("RM035", "warn")
def _doc_claim_rule(ctx):  # implements: ARCH-DOCCLAIMS-071
    # implements: REQ-DOCCLAIMS-1012
    """A marked corpus count in a prose document that no longer matches the corpus."""
    counts = None
    for rel in cfg.DOC_CLAIM_FILES:
        try:
            with io.open(os.path.join(ctx.code_root, rel), encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue          # fail-open: a document this run cannot reach is not a defect
        claims = doc_claims(text)
        if claims and counts is None:
            counts = corpus_counts(ctx.reqs)   # once, and only if a document asks
        for kind, claimed, line in claims:
            measured = _measured(counts, kind)
            if measured is None:
                yield None, ("{}:{} marks an unknown claim kind {!r} — the engine counts: "
                             "{}".format(rel, line, kind, ", ".join(sorted(counts))))
            elif measured != claimed:
                yield None, ("{}:{} states {} for {}; the corpus has {} — correct the "
                             "sentence, or drop the marker if the number is historical"
                             .format(rel, line, claimed, kind, measured))
