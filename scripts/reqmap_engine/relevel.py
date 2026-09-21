"""Half-done re-level residue: five read-only signals surfaced in `sync`'s tail report
when the corpus has adopted the `level:` axis (ADR-0019) but a promotion/demotion along
it left a footprint behind. This is advice, never a check: no signal here is a
`@gate_rule`, none affects the gate's exit code, and none writes anything — the axis
stays a decision the author makes by hand (ADR-0031, ADR-0036). Silent on a corpus that
declares no `level:` at all, because every detector below is itself scoped to a
`level:`-declaring requirement — there is no separate "corpus adopted the axis" guard to
bolt on; the emptiness falls out of each detector's own condition.
"""
from collections import Counter

from .axis import _parent_gap
from .model import _as_list
from .sections import CONTRACT_LABELS, _section_lines
from .tags import _ID_RE


def _satisfied_by_map(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    """parent id -> the ids of every requirement that declares `satisfies: [parent]`."""
    out = {}
    for rid, r in reqs.items():
        for up in _as_list(r["meta"].get("satisfies")):
            out.setdefault(up, []).append(rid)
    return out


def _file_convention_residue(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    """A `level:`-declaring parent whose children (via `satisfies:`) are split across
    more than one file path, where at least one child still shares a file with a
    sibling or with the parent itself — i.e. the group has NOT settled into one file
    per requirement, so the odd-file-out child(ren) look like a move that only
    finished for part of the group. A group cleanly split one-file-per-requirement,
    or one that never split at all, is not residue."""
    children = _satisfied_by_map(reqs)
    out = []
    for parent_id, kids in children.items():
        parent = reqs.get(parent_id)
        if not parent or parent["meta"].get("level") is None:
            continue
        kid_reqs = [(k, reqs[k]) for k in kids if k in reqs]
        if len(kid_reqs) < 2:
            continue
        parent_path = parent.get("path", "")
        paths = [parent_path] + [kr.get("path", "") for _, kr in kid_reqs]
        if len(set(paths)) <= 1:
            continue                       # the whole group shares one file: no residue
        counts = Counter(paths)
        common_path, common_n = max(
            counts.items(), key=lambda kv: (kv[1], kv[0] == parent_path))
        if common_n < 2:
            continue                       # every path distinct: a pure one-file-per-req corpus
        odd = sorted(k for k, kr in kid_reqs if kr.get("path", "") != common_path)
        if odd:
            out.append({"parent": parent_id, "common_path": common_path,
                       "odd_children": odd,
                       "odd_paths": sorted({reqs[k].get("path", "") for k in odd})})
    return out


def _missing_obligation_residue(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    """A `level: architecture` parent with `level: code` children (via `satisfies:`)
    whose Description/Contract body never wikilinks a child's id — the
    `- ... — see [[ID]].` sentence `clarify --decompose` writes for every child it
    splits out. A child with no such sentence is one the parent's prose never
    learned about, or was written out of when the prose was later edited.

    A `deprecated` child is skipped: retiring one capability out of a live parent is
    exactly the case where the obligation sentence SHOULD be gone, and reporting it
    would ask the author to re-add the clause they just deleted on purpose."""
    children = _satisfied_by_map(reqs)
    out = []
    for parent_id, kids in children.items():
        parent = reqs.get(parent_id)
        if not parent or parent["meta"].get("level") != "architecture":
            continue
        code_kids = sorted(k for k in kids
                           if k in reqs and reqs[k]["meta"].get("level") == "code"
                           and reqs[k]["meta"].get("status") != "deprecated")
        if not code_kids:
            continue
        section_text = "\n".join(_section_lines(parent["body"], CONTRACT_LABELS))
        missing = [k for k in code_kids if "[[{}]]".format(k) not in section_text]
        if missing:
            out.append({"parent": parent_id, "missing_children": missing})
    return out


def _stale_sys_mention_residue(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    """A `level: system` requirement whose body still mentions (`[[ID]]` or `` `ID` ``,
    the same id-token grammar `tags.py` uses everywhere else) an id whose own
    `satisfies:` list no longer names this system — prose that outlived the edge it
    once described."""
    out = []
    for rid, r in reqs.items():
        if r["meta"].get("level") != "system":
            continue
        mentioned = sorted(set(_ID_RE.findall(r["body"])) - {rid})
        stale = [mid for mid in mentioned
                if mid in reqs and rid not in _as_list(reqs[mid]["meta"].get("satisfies"))]
        if stale:
            out.append({"id": rid, "stale_mentions": stale})
    return out


def _redundant_depends_on_residue(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    """A `level:`-declaring requirement whose `satisfies:` and `depends_on:` lists
    share an id — the level axis (`satisfies:`) and the composition axis
    (`depends_on:`) drew the same edge twice, most likely because a promotion left
    the old `depends_on:` entry behind."""
    out = []
    for rid, r in reqs.items():
        if r["meta"].get("level") is None:
            continue
        redundant = sorted(set(_as_list(r["meta"].get("satisfies")))
                          & set(_as_list(r["meta"].get("depends_on"))))
        if redundant:
            out.append({"id": rid, "redundant_ids": redundant})
    return out


class _RungCtx(object):
    """The minimal duck-typed context `axis._parent_gap` needs (`.reqs` only) — not
    `workspace.GateContext`, which `relevel.py` may not import (it sits before
    `workspace`/`rules`/`gate` on the bus)."""
    __slots__ = ("reqs",)

    def __init__(self, reqs):
        self.reqs = reqs


def _wrong_rung_residue(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    """Reuses RM032's own adjacency check (`axis._parent_gap`) rather than
    reimplementing it: a `level: architecture`/`code` requirement whose `satisfies:`
    resolves to an id that itself declares a level, and that level is not one rung
    up. A requirement that satisfies nothing at all is RM032's own finding already
    and is not repeated here — this signal is specifically the wrong-rung case."""
    ctx = _RungCtx(reqs)
    out = []
    for rid, r in reqs.items():
        meta = r["meta"]
        level = meta.get("level")
        if level not in ("architecture", "code"):
            continue
        ups = _as_list(meta.get("satisfies"))
        if not ups:
            continue
        if _parent_gap(ctx, rid, level, meta):
            out.append({"id": rid, "level": level, "satisfies": sorted(ups)})
    return out


def _file_convention_line(records):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    detail = "; ".join("{} (shared {}): {}".format(
        r["parent"], r["common_path"], ", ".join(r["odd_children"])) for r in records)
    n = sum(len(r["odd_children"]) for r in records)
    return ("{} requirement(s) split off their group's shared file path - {}"
           .format(n, detail))


def _missing_obligation_line(records):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    detail = "; ".join("{} misses {}".format(r["parent"], ", ".join(r["missing_children"]))
                       for r in records)
    n = sum(len(r["missing_children"]) for r in records)
    return ("{} architecture->code obligation(s) not wikilinked in the parent's "
           "Description - {}".format(n, detail))


def _stale_sys_mention_line(records):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    detail = "; ".join("{} still mentions {}".format(r["id"], ", ".join(r["stale_mentions"]))
                       for r in records)
    n = sum(len(r["stale_mentions"]) for r in records)
    return ("{} system-level mention(s) of an id that no longer satisfies it - {}"
           .format(n, detail))


def _redundant_depends_on_line(records):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    detail = "; ".join("{}: {}".format(r["id"], ", ".join(r["redundant_ids"]))
                       for r in records)
    n = sum(len(r["redundant_ids"]) for r in records)
    return ("{} redundant satisfies/depends_on edge(s) naming the same id twice - {}"
           .format(n, detail))


def _wrong_rung_line(records):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    detail = "; ".join("{} satisfies {} at another rung".format(
        r["id"], ", ".join(r["satisfies"])) for r in records)
    return ("{} requirement(s) satisfy a `level:` target at the wrong rung - {}"
           .format(len(records), detail))


_DETECTORS = (
    (_file_convention_residue, _file_convention_line),
    (_missing_obligation_residue, _missing_obligation_line),
    (_stale_sys_mention_residue, _stale_sys_mention_line),
    (_redundant_depends_on_residue, _redundant_depends_on_line),
    (_wrong_rung_residue, _wrong_rung_line),
)


def relevel_residue_lines(reqs):
    # implements: ARCH-AUDIT-065  # implements: REQ-RELEVEL-997
    """One phrased line per non-empty residue signal, in the order above; `[]` when
    every detector comes back empty — which includes a corpus that declares no
    `level:` at all, since each detector above is itself scoped to a
    `level:`-declaring requirement and never fires without one."""
    lines = []
    for detect, phrase in _DETECTORS:
        records = detect(reqs)
        if records:
            lines.append(phrase(records))
    return lines
