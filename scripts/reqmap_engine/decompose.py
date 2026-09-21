"""`clarify --decompose` for an ungrouped requirement: one child per over-long clause, and the
numbering both paths share.
"""
import os



DECOMPOSED_TEMPLATE = """---
id: {new_id}
status: draft
layer: {layer}
owner: {owner}
depends_on: [{parent}]
superseded_by:
---

# Split from {parent} clause {n}

<!-- decomposed-from: {parent}#{n} -->

## Description
> Scaffolded by `lint --decompose` from a clause that ran past
> LINT_STATEMENT_WORDS words. Rewrite this quote before confirming: say what this
> capability is and what breaks without it.

Every bullet below is binding.
- {clause}

## Verify intent (open questions for the human)
- Does this clause state one obligation, or several? The split point was chosen by
  word count, so this file may hold a clause that was atomic all along.

## Cases (= tests)
CASE-1
  Given  <precondition>
  When   <action>
  Then   <observable, pass/fail result>

## Context (non-binding)
**Notes**
- SCAFFOLD, NOT A DECISION. `lint --decompose` copied clause {n} of {parent} here
  verbatim. The split point was chosen by WORD COUNT, never by obligation — the engine
  cannot observe how many obligations a clause holds (ARCH-ATOMICITY-049). Read the clause
  and decide for yourself whether it should have been split at all.
- The clause is still over the threshold here, because only a human can divide it. Confirming
  this file unedited re-raises the same `statement-size` finding, which is the intended
  reminder.
- {parent} was not modified. Deleting this file restores the corpus exactly.
"""


def _next_free_number(reqs_dir, reqs=None):
    # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-838
    """Highest NNN across the corpus, plus one. Ids stay in AREA-NAME-NNN shape rather
    than taking a derived suffix such as REQ-AUTH-012-B: the suffix form passes _ID_PAT,
    but _warn_number_collision reads parts[-1] as the number and would compare "B".

    Read from the loaded ids when the caller has them: a module file
    (REQ-MODULEFILE-056) holds many ids under one name, so the file names alone
    reported 110 on a corpus whose highest id was 982 — one `--decompose` away from a
    duplicate id. The directory listing is only the fallback for a caller with no corpus."""
    best = 0
    stems = list(reqs or ())
    try:
        stems += [fn[:-3] for fn in os.listdir(reqs_dir)
                  if fn.endswith(".md") and not fn.startswith("_")]
    except OSError:
        if reqs is None:
            return 1
    for stem in stems:
        parts = stem.split("-")
        if len(parts) >= 3 and parts[-1].isdigit():
            best = max(best, int(parts[-1]))
    return best + 1


def _already_decomposed(reqs_dir, parent_id, n, reqs=None):
    # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-839
    """True when some requirement already carries the `decomposed-from: <parent>#<n>` marker.

    Re-running must be a no-op, and the allocated file NAME cannot detect that: the id comes
    from the next free number, so a second run picks a fresh name and `os.path.exists` never
    fires. Provenance is the only stable key. The marker is an HTML comment rather than a
    frontmatter field so it stays invisible to `binding_hash`, and `decomposed-from` is not
    a member role, so TAG_LIST_RE never reads it as a link. The loaded bodies answer it
    without re-reading the directory; the listing is the fallback for a caller without them."""
    needle = "decomposed-from: {}#{}".format(parent_id, n)
    if reqs is not None and any(needle in r["body"] for r in reqs.values()):
        return True   # else fall through: a draft written earlier in this run is on disk only
    try:
        names = os.listdir(reqs_dir)
    except OSError:
        return False
    for fn in names:
        if not fn.endswith(".md") or fn.startswith("_"):
            continue
        try:
            with open(os.path.join(reqs_dir, fn), encoding="utf-8") as f:
                if needle in f.read():
                    return True
        except (OSError, ValueError):
            continue
    return False


def _decompose_clause(reqs_dir, parent_id, parent, n, clause, reqs=None):
    # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-837
    # implements: REQ-DECOMPOSE-838
    """Scaffold one draft requirement from an over-threshold Contract clause.

    Creates exactly one file and never touches the parent, so a confirmed contract cannot
    drift and deleting the new file undoes the whole operation. Returns the created id, or
    None when this clause was already scaffolded (re-running is a no-op, reported by the
    caller)."""
    if _already_decomposed(reqs_dir, parent_id, n, reqs):
        return None
    parts = parent_id.split("-")
    stem = "-".join(parts[:-1]) if len(parts) >= 3 and parts[-1].isdigit() else parent_id
    new_id = "{}-{:03d}".format(stem, _next_free_number(reqs_dir, reqs))
    dest = os.path.join(reqs_dir, new_id + ".md")
    if os.path.exists(dest) or (reqs is not None and new_id in reqs):
        return None
    meta = parent["meta"]
    text = DECOMPOSED_TEMPLATE.format(
        new_id=new_id, parent=parent_id, n=n, clause=clause,
        layer=meta.get("layer", "feature") or "feature",
        owner=meta.get("owner", "") or "")
    os.makedirs(reqs_dir, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    return new_id
