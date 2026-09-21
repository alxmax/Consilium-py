"""The pyramid's upper rungs and edges, written by the same command that writes the
rungs (ADR-0038) — in the shape `init` already produces for a fresh repo:

    SYS-NEEDS-A-NAME-001            one system hole, named by the author
      └─ ARCH-<FAMILY>-001          one capability placeholder per id-prefix family
           └─ <the requirements>    the code rung: one behaviour group each

`clarify --levels --apply` used to write `level:` alone and leave every `satisfies:` edge
to the author — and RM032 then warned twice per requirement, by construction, on any
corpus the retrofit had just touched (0 -> 304 warnings on the first real corpus). The
rungs and the edges are one decision, so they are one write:

- every **code**-rung requirement (declared or proposed) that declares no `satisfies:`
  points at `ARCH-<FAMILY>-001`, where `FAMILY` is its own id prefix — `JS-TIMELINE-001`
  belongs to `JS`. The prefix is a grouping the author typed into every id; it is not
  `depends_on`, so ADR-0036 still holds: composition is never read as the level axis.
  A prefix with fewer than `LEVEL_FAMILY_MIN` members shares `ARCH-NEEDS-A-NAME-001`
  instead of minting a "capability" per stray prefix (the first real corpus had 45 such
  prefixes, 33 of them with one member);
- every new `ARCH-*` placeholder, and every **architecture**-rung requirement that declares
  no `satisfies:`, points at `SYS-NEEDS-A-NAME-001` — `init`'s own named hole, written by
  `draft._write_sys_placeholder` so the two paths cannot drift;
- auto-extracted `draft` stubs are skipped: the gate never judges them and `DRAFT` is a
  status, not a family. A requirement that already points somewhere is left alone.

Everything written is `status: draft`, `level_source: auto`, and reversible: delete the
`ARCH-*`/`SYS-*` files and the `satisfies:` lines and the corpus reads exactly as before.
"""
import os
from collections import OrderedDict

from . import config as cfg
from .draft import SYS_PLACEHOLDER_ID, _write_sys_placeholder
from .model import _as_list
from .parse import split_requirement_blocks

ARCH_PREFIX = "ARCH"
ARCH_SHARED_ID = "ARCH-NEEDS-A-NAME-001"
_RESERVED = (ARCH_PREFIX, "SYS")     # prefixes that name rungs, never a family


# ---- frontmatter editing, shared with the rung writer in levels.py -----------------

def _insert_frontmatter_key(text, key, value, after=("level_source", "level", "status")):
    # implements: ARCH-LEVELRETROFIT-066  # implements: REQ-LEVELRETROFIT-986
    """Add `key: value` to one block's frontmatter, right after the first of `after` that
    is present (after the opening `---` when none is). Returns (text, n), with n=0 when
    there is no frontmatter to edit or the key is already declared, so the caller reports
    a miss instead of writing a duplicate."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text, 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return text, 0
    fm = lines[1:end]
    if any(ln.startswith(key + ":") for ln in fm):
        return text, 0
    at = -1
    for anchor in after:
        at = next((i for i, ln in enumerate(fm) if ln.startswith(anchor + ":")), -1)
        if at >= 0:
            break
    fm[at + 1:at + 1] = ["{}: {}".format(key, value)]
    return "\n".join(lines[:1] + fm + lines[end:]), 1


def _apply_frontmatter_edit(r, editor):
    # implements: ARCH-LEVELRETROFIT-066  # implements: REQ-LEVELRETROFIT-986
    """Run `editor(block_text) -> (text, n)` on one requirement's own block, preserving the
    file's line endings and every sibling block in a module file. Returns n; 0 means the
    file was not touched. The mechanics mirror `_apply_status` deliberately: a module file
    holds several requirements, and a repo's files may be CRLF."""
    with open(r["path"], encoding="utf-8-sig", newline="") as f:
        raw = f.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n") if eol == "\r\n" else raw
    blocks = split_requirement_blocks(text)
    if len(blocks) > 1:
        idx = r.get("block", 0)
        blocks[idx], n = editor(blocks[idx])
        new_text = "".join(blocks)
    else:
        new_text, n = editor(text)
    if n == 0:
        return 0
    if eol == "\r\n":
        new_text = new_text.replace("\n", "\r\n")
    with open(r["path"], "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return n


# ---- the plan ---------------------------------------------------------------------

def _family_of(rid):  # implements: REQ-LEVELRETROFIT-987
    """`JS-TIMELINE-001` -> `JS`: the grouping the author already typed into the id."""
    return rid.split("-", 1)[0]


def _arch_id(family):  # implements: REQ-LEVELRETROFIT-987
    return "{}-{}-001".format(ARCH_PREFIX, family)


def _rung_of(rid, r, proposals):  # implements: REQ-LEVELRETROFIT-987
    """The declared rung, or the one this run proposes; None for neither."""
    return r["meta"].get("level") or proposals.get(rid, (None,))[0]


def plan_edges(reqs, proposals):  # implements: REQ-LEVELRETROFIT-987
    """The upper rungs and edges `--apply` would write.

    Returns `{"arch": OrderedDict(aid -> {family, members, exists}), "sys": {id, members,
    exists, needed}}`: the code-rung requirements grouped by id prefix into one
    `ARCH-<FAMILY>-001` per family of at least `LEVEL_FAMILY_MIN` (the rest under
    `ARCH-NEEDS-A-NAME-001`, biggest families first), and the architecture-rung
    requirements that will point at `SYS-NEEDS-A-NAME-001`. A requirement that already
    declares `satisfies:` keeps it and is not listed; a `draft` stub is skipped; an
    `ARCH-*`/`SYS-*` id names a rung and is never treated as a family."""
    by_family, small, arch_members = {}, [], []
    for rid, r in sorted(reqs.items()):
        meta = r["meta"]
        if meta.get("status") == "draft" or _as_list(meta.get("satisfies")):
            continue
        rung = _rung_of(rid, r, proposals)
        if rung == "code":
            family = _family_of(rid)
            (small if family in _RESERVED else by_family.setdefault(family, [])).append(rid)
        elif rung == "architecture":
            arch_members.append(rid)
    arch = OrderedDict()
    for family, members in sorted(by_family.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(members) >= cfg.LEVEL_FAMILY_MIN:
            aid = _arch_id(family)
            arch[aid] = {"family": family, "members": members, "exists": aid in reqs}
        else:
            small.extend(members)
    if small:
        arch[ARCH_SHARED_ID] = {"family": None, "members": sorted(small),
                                "exists": ARCH_SHARED_ID in reqs}
    new_arch = [a for a, e in arch.items() if not e["exists"]]
    return {"arch": arch,
            "sys": {"id": SYS_PLACEHOLDER_ID, "members": arch_members,
                    "exists": SYS_PLACEHOLDER_ID in reqs,
                    "needed": bool(new_arch) or bool(arch_members)}}


def plan_is_empty(plan):  # implements: REQ-LEVELRETROFIT-987
    """True when `--apply` would write no file and no edge."""
    arch_work = any(not e["exists"] or e["members"] for e in plan["arch"].values())
    sys_work = plan["sys"]["members"] or (plan["sys"]["needed"] and not plan["sys"]["exists"])
    return not arch_work and not sys_work


# ---- the writes -------------------------------------------------------------------

def _arch_text(aid, family, members):  # implements: REQ-LEVELRETROFIT-987
    """One capability placeholder, in the shape `init` writes for a directory
    (`draft._write_arch_drafts`): a proposed grouping that says it is one."""
    n = len(members)
    if family is None:
        title = ("NAME THIS CAPABILITY — {} behaviour group(s) whose id prefix "
                 "has fewer than {} members".format(n, cfg.LEVEL_FAMILY_MIN))
        signal = ("no id prefix shared by {} or more of them, so the engine parked them under "
                  "one placeholder rather than mint a \"capability\" per stray prefix"
                  .format(cfg.LEVEL_FAMILY_MIN))
    else:
        title = "NAME THIS CAPABILITY — {} ({} behaviour groups)".format(family, n)
        signal = ("the id prefix `{}-` the author typed into each of these "
                  "{} requirements".format(family, n))
    lines = [
        "---", "id: " + aid, "status: draft", "level: architecture", "layer: feature",
        "owner: auto", "level_source: auto", "satisfies: [{}]".format(SYS_PLACEHOLDER_ID),
        "---", "",
        "# " + title, "",
        "> PROPOSED grouping, not a capability. The engine had one structural signal — {} — "
        "and a prefix is not a capability. Rename this to the thing these behaviour groups "
        "together let a user do, merge it with a sibling, or delete it and re-point its "
        "children's `satisfies:` lines.".format(signal), "",
        "## Description", "Every bullet below is binding.",
        "- TODO: what these {} behaviour groups together let a user do, "
        "as one capability.".format(n), "",
        "## Cases", "CASE-1", "  Given  TODO", "  When   TODO", "  Then   TODO", "",
        "## Context (non-binding)", "**Current implementation**",
        "Grouped here by `clarify --levels --apply`:",
    ]
    lines += ["- " + m for m in members]
    return "\n".join(lines) + "\n"


def _write_arch(reqs_dir, aid, family, members):  # implements: REQ-LEVELRETROFIT-987
    """Write one placeholder; False when the file already exists (never overwritten)."""
    dest = os.path.join(reqs_dir, aid + ".md")
    if os.path.exists(dest):
        return False
    with open(dest, "w", encoding="utf-8") as f:
        f.write(_arch_text(aid, family, members))
    return True


def _apply_satisfies(r, target):  # implements: REQ-LEVELRETROFIT-987
    """Add `satisfies: [target]` to one requirement; 0 when it already declares the key."""
    return _apply_frontmatter_edit(
        r, lambda t: _insert_frontmatter_key(t, "satisfies", "[{}]".format(target)))


def report_edges(plan):  # implements: REQ-LEVELRETROFIT-987
    """Print what `--apply` would write above the code rung, in the same read-only pass
    that prints the rung proposals."""
    arch, sys_ = plan["arch"], plan["sys"]
    if plan_is_empty(plan):
        print("\n  Upper rungs: every requirement already satisfies the rung above it —")
        print("  no placeholder and no `satisfies:` edge to write.")
        return
    n_new = sum(1 for e in arch.values() if not e["exists"])
    n_edges = sum(len(e["members"]) for e in arch.values())
    print("\n  Architecture rung (ADR-0038): {} capability placeholder(s), one per id-prefix "
          "family of".format(n_new))
    print("  {}+ members, and a `satisfies:` edge on {} code requirement(s) that declare none:"
          .format(cfg.LEVEL_FAMILY_MIN, n_edges))
    for aid, e in arch.items():
        print("    {:<26} {:>4} requirement(s)  {}".format(
            aid, len(e["members"]), "exists — reused" if e["exists"] else "new, draft"))
    print("  System rung: {} ({}), satisfied by every placeholder above{}."
          .format(sys_["id"],
                  "exists — reused" if sys_["exists"] else "new, draft — init's own hole",
                  " and by {} architecture requirement(s) that declare none"
                  .format(len(sys_["members"])) if sys_["members"] else ""))
    print("  The family is the id prefix the author typed; `depends_on` is never read for this.")
    print("  `draft` stubs are skipped — the gate never judges them. Every placeholder "
          "is a named")
    print("  hole (`NAME THIS …`) for the author to fill, merge or delete.")


def apply_edges(reqs, reqs_dir, plan):  # implements: REQ-LEVELRETROFIT-987
    """Write the placeholders and the edges; returns (arch_written, sys_written, edges)."""
    arch_written = edges = 0
    for aid, e in plan["arch"].items():
        if _write_arch(reqs_dir, aid, e["family"], e["members"]):
            print("  wrote  {} (capability placeholder, draft)".format(aid))
            arch_written += 1
        for rid in e["members"]:
            if _apply_satisfies(reqs[rid], aid):
                print("  wrote  {}: satisfies: [{}]".format(rid, aid))
                edges += 1
    sys_ = plan["sys"]
    sys_written = 0
    if sys_["needed"]:
        sys_written = _write_sys_placeholder(reqs_dir, list(plan["arch"]) + sys_["members"])
        if sys_written:
            print("  wrote  {} (system placeholder, draft)".format(sys_["id"]))
    for rid in sys_["members"]:
        if _apply_satisfies(reqs[rid], sys_["id"]):
            print("  wrote  {}: satisfies: [{}]".format(rid, sys_["id"]))
            edges += 1
    return arch_written, sys_written, edges
