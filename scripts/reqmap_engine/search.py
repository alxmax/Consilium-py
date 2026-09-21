"""`ask --search`: free-text requirement lookup, on the model `dupes` compares with."""
import json

from .i18n import _load_translations
from .sections import ACCEPTANCE_LABELS, CONTRACT_LABELS, _from_any
from .similar import _cosine, _sim_text, _sim_tokens, _tfidf
from .text import _req_title, _section_raw

# ---------- search (free-text requirement lookup) ----------
# Ranks requirements against a free-text query with the SAME lexical TF-IDF/cosine
# used by `dupes` — reused, not re-implemented. The floor is NOT the dupes 0.35
# pair-threshold: a short query is a sparse vector, so query-vs-doc cosine runs far
# lower than doc-vs-doc. Calibrated on the 39-requirement corpus, a correct top hit
# scores ~0.13-0.67 while a no-lexical-overlap query tops out ~0.00-0.04, so 0.05
# cleanly separates a real match from noise. Below it, `search` says so rather than
# presenting a spurious top result with the same authority as a real one.
SEARCH_FLOOR = 0.05
SEARCH_TOP = 5


# Searching a requirement browser for `ARCH-CHECK-006` used to return
# REQ-ORPHANCODE-888 and not the requirement itself: the bag of words is title +
# intent + clauses, and an id is in none of them, so "arch" and "check" were matched
# as ordinary prose. An id is the primary key of this corpus; a query that names one
# is not asking to be ranked.
SEARCH_ID_MAX = 3          # substring id hits shown before the lexical ranking


def _id_matches(reqs, query):  # implements: ARCH-SEARCH-036  # implements: REQ-SEARCH-965
    """Requirement ids the query names, best first: an exact id, then ids it prefixes,
    then ids that contain it. An exact hit is alone and unconditional; the looser two
    are capped so a common word like `map` cannot crowd out the lexical ranking."""
    q = (query or "").strip().upper()
    if len(q) < 3:
        return []
    if q in reqs:
        return [q]
    prefix = sorted(rid for rid in reqs if rid.upper().startswith(q))
    inner = sorted(rid for rid in reqs if q in rid.upper() and rid not in prefix)
    return (prefix + inner)[:SEARCH_ID_MAX]


def _text_matches(reqs, query, translations=None, skip=()):  # implements: REQ-SEARCH-965
    """Requirements whose title, description or cases plainly contain the query, plus any
    cached translation of them.

    Scoped to exactly what the reader is asking about: the normative text and the cases
    that prove it. `## Context` is deliberately excluded, for the same reason the ranking
    bag excludes it — a word that appears only in commentary is not what the requirement
    is about, and REQ-SEARCH-912 already decided that.

    This is also the layer that answers a query in the language the reader is being
    shown: the ranking model weights one language's tokens, so a translated requirement
    is invisible to it. Substring, not ranked, and it only fills the slots the model
    left empty."""
    q = (query or "").strip().lower()
    if len(q) < 3:
        return []
    out = []
    for rid in sorted(reqs):
        if rid in skip:
            continue
        body = reqs[rid]["body"]
        hay = "\n".join([
            _req_title(body, rid),
            _from_any(_section_raw, body, CONTRACT_LABELS) or "",
            _from_any(_section_raw, body, ACCEPTANCE_LABELS) or "",
        ]).lower()
        for entry in ((translations or {}).get(rid) or {}).values():
            if isinstance(entry, dict):
                hay += "\n" + "\n".join(str(v).lower() for v in entry.values())
        if q in hay:
            out.append(rid)
    return out


def search_record(reqs, query, top=SEARCH_TOP, floor=SEARCH_FLOOR, reqs_dir=None):
    # implements: ARCH-SEARCH-036  # implements: REQ-SEARCH-912  # implements: REQ-SEARCH-913
    # implements: REQ-SEARCH-914  # implements: REQ-SEARCH-965
    """{query, matches, message}: the matches in the order they are shown — ids, then
    literal text, then the lexical ranking — each with how it matched and, for the
    ranking, its cosine score. `message` explains an empty result and is None otherwise."""
    rec = {"query": query, "matches": [], "message": None}
    ids = _id_matches(reqs, query)
    qtok = _sim_tokens(query or "")
    if not qtok and not ids:
        rec["message"] = ("No searchable terms in {!r} (need a word of 3+ letters that is not "
                          "a stopword). Nothing to rank.".format(query or ""))
        return rec
    docs = {rid: _sim_tokens(_sim_text(r["body"])) for rid, r in reqs.items()}
    docs = {rid: toks for rid, toks in docs.items() if toks}   # skip empty contracts
    if not docs:
        rec["message"] = "No requirements with contract text to search."
        return rec
    top = max(1, top)
    corpus = dict(docs)
    corpus["\x00query"] = qtok        # fold the query into the corpus so idf spans docs+query
    vecs = _tfidf(corpus)
    qv = vecs["\x00query"]
    scored = sorted(((_cosine(qv, vecs[rid]), rid) for rid in docs),
                    key=lambda x: (-x[0], x[1]))
    # Order: id, then literal text, then the ranked model. A document that CONTAINS the
    # query is stronger evidence than a partial token overlap with it -- a phrase that
    # appears verbatim inside a case used to lose to a 0.10 cosine somewhere else.
    translations = _load_translations(reqs, reqs_dir) if reqs_dir else {}
    text = _text_matches(reqs, query, translations, skip=set(ids))[:max(0, top - len(ids))]
    seen = set(ids) | set(text)
    lexical = [(s, rid) for s, rid in scored
               if s >= floor and rid not in seen][:max(0, top - len(seen))]
    if not (ids or lexical or text):
        rec["message"] = ("No match for {!r}: no id, no literal text, and the best lexical "
                          "(cosine) score {:.3f} is below the {:.2f} floor. Try different "
                          "words, or `dupes`/grep.".format(
                              query, scored[0][0] if scored else 0.0, floor))
        return rec
    title = lambda rid: _req_title(reqs[rid]["body"], rid)
    rec["matches"] = ([{"id": rid, "title": title(rid), "match": "id", "score": None}
                       for rid in ids]
                      + [{"id": rid, "title": title(rid), "match": "text", "score": None}
                         for rid in text]
                      + [{"id": rid, "title": title(rid), "match": "lexical",
                          "score": round(s, 3)} for s, rid in lexical])
    return rec


def cmd_search(reqs, query, top=SEARCH_TOP, floor=SEARCH_FLOOR, reqs_dir=None, as_json=False):
    # implements: ARCH-SEARCH-036  # implements: REQ-SEARCH-913  # implements: REQ-SEARCH-915
    """Rank requirements by lexical relevance to `query` (cosine over TF-IDF of the
    same title + intent + Contract text `dupes` compares on). Read-only, always exit
    zero. Prints each hit's cosine score so a weak match is visible as weak, and emits
    an explicit no-strong-match line when the best score is below `floor` — so a
    lexical near-miss is never dressed up as an answer. `as_json` prints the record."""
    rec = search_record(reqs, query, top, floor, reqs_dir)
    if as_json:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0
    if rec["message"]:
        print(rec["message"])
        return 0
    print("{} match(es) for {!r} — id, then literal text, then cosine score (lexical, "
          "not synonym-aware):\n".format(len(rec["matches"]), query))
    for m in rec["matches"]:
        label = m["match"] if m["score"] is None else "{:.3f}".format(m["score"])
        print("  {:>6}  {}  {}".format(label, m["id"], m["title"]))
    return 0
