"""TF-IDF over contracts: `dupes` and `search`."""
import argparse, json, math, re

from . import config as cfg
from .model import _as_list
from .sections import CONTRACT_LABELS, _from_any
from .tags import _ID_PAT
from .text import _bullets, _req_title


_SIMILAR_STOP = frozenset((
    "the", "and", "for", "shall", "with", "that", "this", "from", "into", "its",
    "not", "are", "has", "have", "when", "then", "given", "each", "one", "any",
    "per", "via", "use", "used", "must", "code", "requirement", "requirements",
))


def _sim_tokens(text):  # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILAR-921
    """Lowercase alphanumeric tokens of length >= 3, minus stopwords and pure
    numbers — the bag of words a requirement is compared on. Deterministic."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) >= 3 and not t.isdigit() and t not in _SIMILAR_STOP]


def _placeholder_contract(body):  # implements: ARCH-SIMILAR-016
    """True when every Contract bullet is still a `TODO:` scaffold line. Five evidence
    runs scored thousands of freshly-drafted stubs as near-duplicates of each other on
    template text alone (fabric: 6,340 pairs for 638 drafts) — nothing authored, nothing
    to compare."""
    bullets = _from_any(_bullets, body, CONTRACT_LABELS)
    return bool(bullets) and all(b.strip().upper().startswith("TODO") for b in bullets)


def _exemption_reason_recorded(body, check):
    # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-971
    """True when the requirement's own prose mentions the check it exempts itself from.

    Deliberately the crudest possible test: the check's name appearing anywhere in the
    body. It cannot judge whether the reason is a GOOD one — no mechanical test can —
    and it is not trying to. It only makes the exemption cost one sentence a reviewer
    can argue with, instead of one frontmatter token nobody ever reads."""
    return check.lower() in (body or "").lower()


# Every frontmatter field that silences a finding for one requirement. `distinct_from:` is
# one: it names a requirement `dupes` would pair this one with, after a reviewer read both.
EXEMPTION_FIELDS = ("lint_exempt", "gate_exempt", "distinct_from")


def _exemptions_in_force(reqs):  # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-971
    """Every `lint_exempt:`/`gate_exempt:` entry in the corpus, as records carrying the
    requirement, the field, the silenced check and whether a reason is recorded.

    An exemption is a finding somebody decided not to see. Listing them is what keeps
    "silenced" from becoming "invisible": a corpus that exempted forty checks shows
    forty lines here, and the count is the debt."""
    out = []
    for rid in sorted(reqs):
        r = reqs[rid]
        meta, body = r["meta"], r["body"]
        for field in EXEMPTION_FIELDS:
            for check in _as_list(meta.get(field)):
                out.append({"id": rid, "field": field, "check": check,
                            "reason": _exemption_reason_recorded(body, check)})
    return out


def _corpus_shape(reqs):  # implements: ARCH-AUDIT-065  # implements: REQ-AUDIT-972
    """How the corpus sits on the V-model's left arm: how many requirements declare a
    `level:`, how they spread across the rungs, and how many `satisfies:` edges hold the
    pyramid together.

    `level:` is opt-in (the template ships it commented out) so an existing corpus keeps
    its behaviour, and the consequence is that a repo can run the engine for months with
    every requirement on one rung and nothing ever mentioning the other two. This says it
    once, in `audit`, and never in the gate: adopting a level axis is a decision, not a
    defect.

    `auto` counts the rungs the ENGINE wrote (`level_source: auto`, ADR-0030). Since
    `init` drafts a pyramid, a corpus can now be fully levelled and still be nothing but
    the engine's own guesses — every other number here would read as healthy. This is the
    number ADR-0030's revisit trigger asks for: a pyramid still made of proposals is
    untriaged, not done."""
    total = len(reqs)
    levels, edges, auto = {}, 0, 0
    for r in reqs.values():
        meta = r["meta"]
        lv = meta.get("level")
        if lv:
            levels[lv] = levels.get(lv, 0) + 1
            if meta.get("level_source") == "auto":
                auto += 1
        edges += len(_as_list(meta.get("satisfies")))
    levelled = sum(levels.values())
    return {"total": total, "levelled": levelled, "levels": levels,
            "satisfies_edges": edges, "auto": auto,
            "flat": bool(total) and levelled * 10 < total}


def _redundant_groups(reqs):  # implements: REQ-REDUNDANCY-058
    """Requirements whose Description clauses are IDENTICAL once case and whitespace are
    normalised, grouped, each group sorted and the groups ordered by their first id.

    This is the exact-match floor under `dupes`, not a second opinion on it: no threshold,
    no scoring, so a group is a duplicate by construction and never a judgement call. It
    exists because decomposing several architecture requirements can mint the same
    obligation twice — the same clause authored in two parents becomes two detailed-design
    requirements — and nothing else in the engine notices. `dupes` finds the near-matches
    this cannot; neither replaces the other.

    Draft placeholders are skipped: every freshly scaffolded requirement carries the same
    `TODO:` line, so counting those would report the scaffold as a duplicate of itself
    hundreds of times and drown the real finding."""
    groups = {}
    for rid, r in sorted(reqs.items()):
        body = r["body"]
        if _placeholder_contract(body):
            continue
        joined = " ".join(_from_any(_bullets, body, CONTRACT_LABELS))
        key = re.sub(r"\s+", " ", joined).strip().lower()
        if key:
            groups.setdefault(key, []).append(rid)
    return sorted((sorted(v) for v in groups.values() if len(v) > 1), key=lambda g: g[0])


def _sim_text(body):  # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILAR-921
    """The text similarity is computed on: title, intent line, and Contract bullets.
    Notes & limitations is left out — it is dense and would only add noise."""
    parts = [_req_title(body, "")]
    for line in body.splitlines():
        if line.strip().startswith(">"):
            parts.append(line.strip().lstrip(">").strip())
            break
    parts += _from_any(_bullets, body, CONTRACT_LABELS)
    return " ".join(parts)


# A requirement id, the `[[ID]]` link around it, and a `req: ID` field name no behaviour:
# on this corpus the token `req` sat in 80 of 281 bags, one per `[[REQ-...]]` an ARCH clause
# ends with, and an id's stem repeats the topic word the prose already carries.
_DUPES_ID_RE = re.compile(r"\[\[\s*" + _ID_PAT + r"\s*\]\]"
                          r"|(?<![\w-])req\s*:\s*" + _ID_PAT
                          + r"|(?<![\w-])" + _ID_PAT + r"(?![\w-])")


def _dupes_text(body):  # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILARIDS-1025
    """`_sim_text` with requirement ids and their link syntax removed, for `dupes` only.
    `search` keeps the ids: its bag is pinned to the viewer's port by a shared fixture, and
    an id in a query is answered by `_id_matches` before any ranking."""
    return _DUPES_ID_RE.sub(" ", _sim_text(body))


def _tfidf(docs):  # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILAR-922
    """docs: {id: token_list}. Returns {id: {term: weight}} with smoothed idf =
    log((1 + N) / (1 + df)) + 1 — always positive (so a 2-doc corpus does not
    collapse to zero), while still down-weighting terms common across requirements."""
    N = len(docs)
    df = {}
    for toks in docs.values():
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    vecs = {}
    for rid, toks in docs.items():
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        vecs[rid] = {t: c * (math.log((1 + N) / (1 + df[t])) + 1) for t, c in tf.items()}
    return vecs


def _cosine(a, b):  # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILAR-922
    """Cosine similarity of two {term: weight} vectors, in [0, 1]. The result is
    clamped to 1.0 because floating-point rounding can push parallel vectors a hair
    over 1.0 (e.g. 1.0000000000000002), which would break the documented range."""
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in set(a) & set(b))
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return min(1.0, dot / (na * nb)) if na and nb else 0.0


def _threshold_arg(v):  # implements: ARCH-SIMILAR-016
    """argparse type for `--threshold`: a finite number in (0, 1]. Rejects nan/inf
    (which silently swallow or admit every pair under `>=`) and out-of-range cutoffs."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("threshold must be a number")
    if not math.isfinite(f) or not (0.0 < f <= 1.0):
        raise argparse.ArgumentTypeError("threshold must be a finite number in (0, 1]")
    return f


def _add_test_suite_links(rid, f, impl_of, linked):
    # implements: REQ-SIMILAR-921
    """Link `rid` with every requirement `f` implements, other than itself."""
    for other in impl_of.get(f, ()):
        if other != rid:
            linked.add(frozenset((rid, other)))


def _test_suite_pairs(members):  # implements: REQ-SIMILAR-921
    """Pairs (A, B) where a `tested-by` member file of A is an `implements` member of B —
    i.e. B is the requirement that IS A's test suite. Such a pair shares vocabulary by
    construction and is a known link, not a duplicate. Empty when no member map is given."""
    impl_of = {}   # file -> set of requirement ids implemented in it
    for rid, mem in (members or {}).items():
        for role, f, _ in mem:
            if role == "implements":
                impl_of.setdefault(f, set()).add(rid)
    linked = set()
    for rid, mem in (members or {}).items():
        for role, f, _ in mem:
            if role == "tested-by":
                _add_test_suite_links(rid, f, impl_of, linked)
    return linked


def _hierarchy_pairs(reqs):
    # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILAR-921
    """Pairs the level axis already explains: a child with its parent (the parent's
    summary clause names it) and two children of one parent (both restate that parent's
    clauses). 25 of the 40 pairs `dupes` reported on this corpus were siblings; a known
    link is not a duplicate finding."""
    linked, kids_of = set(), {}
    for rid, r in reqs.items():
        for up in _as_list((r.get("meta") or {}).get("satisfies")):
            linked.add(frozenset((rid, up)))
            kids_of.setdefault(up, []).append(rid)
    for kids in kids_of.values():
        for i in range(len(kids)):
            for j in range(i + 1, len(kids)):
                linked.add(frozenset((kids[i], kids[j])))
    return linked


def _distinct_pairs(reqs):
    # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILARDISTINCT-1026
    """Pairs a reviewer read and recorded as different obligations with `distinct_from:`,
    from either side. Lexical overlap cannot tell a shared topic from a shared obligation:
    on this corpus a real duplicate scored 0.54 and a pair checking different things 0.51,
    so no threshold separates them and only a recorded reading can."""
    return {frozenset((rid, other)) for rid, r in reqs.items()
            for other in _as_list((r.get("meta") or {}).get("distinct_from")) if other != rid}


def _similar_skips(skipped):
    # implements: REQ-SIMILAR-921  # implements: REQ-SIMILARDISTINCT-1026
    """Print the counts of what `dupes` left out, one line each, only when non-zero."""
    if skipped["deprecated"]:
        print("skipped {} deprecated requirement(s): a retired contract is not a duplicate "
              "of a live one.\n".format(skipped["deprecated"]))
    if skipped["linked"]:
        print(("skipped {} pair(s) linked by tested-by or satisfies, or siblings under one "
               "parent (a requirement and its own test suite, a parent and its child, and two "
               "children of one parent share vocabulary by construction).\n")
              .format(skipped["linked"]))
    if skipped["distinct"]:
        print("skipped {} pair(s) a reviewer recorded as distinct with `distinct_from:`.\n"
              .format(skipped["distinct"]))


def similar_record(reqs, threshold=cfg.SIMILAR_THRESHOLD, members=None):
    # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILAR-920  # implements: REQ-SIMILAR-923
    """{threshold, compared, skipped, pairs}: every pair at or above `threshold`, most
    similar first, each with its score and up to five shared terms, and the counts of
    what was left out. `compared` is None when fewer than two contracts exist."""
    linked = set(_test_suite_pairs(members)) | _hierarchy_pairs(reqs)
    distinct = _distinct_pairs(reqs)
    placeholder = sorted(rid for rid, r in reqs.items() if _placeholder_contract(r["body"]))
    retired = {rid for rid, r in reqs.items()
               if (r.get("meta") or {}).get("status") == "deprecated"}
    docs = {rid: _sim_tokens(_dupes_text(r["body"])) for rid, r in reqs.items()
            if rid not in placeholder and rid not in retired}
    docs = {rid: toks for rid, toks in docs.items() if toks}   # skip empty contracts
    skipped = {"placeholder": len(placeholder), "deprecated": len(retired),
               "linked": 0, "distinct": 0}
    rec = {"threshold": threshold, "compared": None, "skipped": skipped, "pairs": []}
    if len(docs) < 2:
        return rec
    vecs = _tfidf(docs)
    ids = sorted(vecs)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            s = _cosine(vecs[ids[i]], vecs[ids[j]])
            if s < threshold:
                continue
            pair = frozenset((ids[i], ids[j]))
            if pair in linked or pair in distinct:
                skipped["linked" if pair in linked else "distinct"] += 1
                continue
            shared = sorted(set(vecs[ids[i]]) & set(vecs[ids[j]]),
                            key=lambda t: (-(vecs[ids[i]][t] + vecs[ids[j]][t]), t))[:5]
            rec["pairs"].append({"a": ids[i], "b": ids[j], "score": round(s, 4),
                                 "shared": shared})
    rec["pairs"].sort(key=lambda p: (-p["score"], p["a"], p["b"]))
    rec["compared"] = len(docs)
    return rec


def cmd_similar(reqs, threshold=cfg.SIMILAR_THRESHOLD, members=None, top=None, as_json=False):
    # implements: ARCH-SIMILAR-016  # implements: REQ-SIMILAR-920  # implements: REQ-SIMILAR-923
    """Report requirement pairs whose contracts overlap at or above `threshold`
    (cosine over TF-IDF of title + intent + Contract), most-similar-first, so a human
    can spot a probable duplicate or a capability that should be merged. Read-only and
    always exit 0 (advisory). Smoothed idf down-weights shared boilerplate so it
    does not inflate the score. Callers pass a validated threshold in (0, 1].
    With `members`, a pair linked by `tested-by` (one requirement is the other's test
    suite) is skipped and counted instead of reported. `as_json` prints the record,
    every pair included: `top` shortens only the text."""
    rec = similar_record(reqs, threshold, members)
    if as_json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0
    if rec["skipped"]["placeholder"]:
        print("skipped {} requirement(s) whose Contract is still the draft placeholder — "
              "dupes compares authored contracts only.\n".format(rec["skipped"]["placeholder"]))
    if rec["compared"] is None:
        print("Need at least two requirements with contract text to compare.")
        return 0
    _similar_skips(rec["skipped"])
    pairs = rec["pairs"]
    if not pairs:
        print("No overlapping requirement pairs at or above {:.2f}. {} requirement(s) compared."
              .format(threshold, rec["compared"]))
        return 0
    print("{} probable-duplicate pair(s) at or above {:.2f} (of {} requirement(s)):\n".format(
        len(pairs), threshold, rec["compared"]))
    shown = pairs if top is None else pairs[:top]
    for p in shown:
        print("  {:.2f}  {}  <->  {}".format(p["score"], p["a"], p["b"]))
        print("        shared terms: {}".format(", ".join(p["shared"]) or "(none)"))
    if len(shown) < len(pairs):
        print("  ... {} more pair(s) — raise --top to see them".format(len(pairs) - len(shown)))
    print("\nThese contracts overlap — check they are not the same capability "
          "implemented twice. Merge or differentiate, then re-run.")
    return 0
