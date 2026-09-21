"""`clarify --decompose` along contract groups: plan, render and write the code-rung children.
"""
import os, re

from . import config as cfg
from .acceptance import _AC_LABEL_RE, _acc_blocks
from .model import _as_list
from .sections import ACCEPTANCE_LABELS, CONTRACT_LABELS, _heading_label_is, _section_lines
from .text import _is_label_line


# ---------- decompose on contract groups: the code rung for a tagged corpus ----------
# `init` mints the code rung only for files it extracts, and it extracts only untagged
# files; `clarify --levels` classifies a requirement but never creates one. So a corpus
# that adopted the tool at the architecture rung had no path to `level: code` at all —
# on one consumer, 40 of 42 architecture nodes with zero children and 160 group labels
# sitting in their contracts. This is the path. The seam is one the AUTHOR already drew:
# a bold group label in the Description is a heading the author wrote to say "these
# clauses belong together", and a behaviour group is what the code rung is defined as.
# It is not the engine inventing structure; it is the engine reading structure that is
# already in the file, which is the line ADR-0025 had to refold 573 leaves back behind.

GROUP_CHILD_TEMPLATE = """---
id: {new_id}
status: draft
level: code
level_source: auto
layer: {layer}
owner: {owner}
satisfies: [{parent}]
---

# {title}

<!-- decomposed-from: {parent}#group:{slug} -->

## Description
> Split from {parent} along a contract group the author wrote: **{label}**. Rewrite this
> quote before confirming — say what this behaviour is for and what breaks without it.

Every bullet below is binding.
{bullets}

## Cases
{cases}

## Context
**Notes**
- SCAFFOLD, NOT A DECISION. The seam was the parent's own group label, not a guess, but
  whether this group is ONE behaviour or several is still yours to judge.
- No `implements:` tag was written. The gate checks that a tag exists, never that it
  points at the right code, so an auto-generated child citing the wrong function would
  pass every check. Expected members, found by searching for the group's subject —
  verify each, then tag by hand:
{members}
- {moved} case(s) moved here from {parent}; {unassigned} stayed on the parent because no
  group's subject appeared in their text, or more than one did.
"""


def _contract_groups(body):  # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-994
    """`[(label, [clause, ...]), ...]` — the bold group labels in the Description and the
    bullets under each, in order. A bullet before the first label belongs to no group and
    is not returned: it is the parent's own preamble, and it stays there."""
    out, cur = [], None
    for raw in _section_lines(body, CONTRACT_LABELS, raw=True):
        s = raw.strip()
        if _is_label_line(raw):
            cur = (s.strip("*").strip(), [])
            out.append(cur)
        elif cur is not None and (s == "-" or s.startswith("- ")):
            cur[1].append(s[1:].strip())
        elif cur is not None and cur[1] and s and not s.startswith(("|", ">", "#", "<!--")):
            cur[1][-1] += " " + s          # hanging-indent continuation of the last clause
    return [(label, clauses) for label, clauses in out if clauses]


def _group_subject(label):  # implements: REQ-DECOMPOSE-994
    """The identifier a case or a member would name: `load_json_stdin(script_name)` ->
    `load_json_stdin`; `Falsifiability anchor (Law 8)` -> `Falsifiability anchor`.
    Backticks and a parenthesised tail are presentation, not identity."""
    s = label.replace("`", "").strip()
    s = re.sub(r"\s*\(.*$", "", s).strip()
    return s


def _group_slug(label):  # implements: REQ-DECOMPOSE-994
    return re.sub(r"[^A-Za-z0-9]+", "-", _group_subject(label)).strip("-").upper() or "GROUP"


def _group_child_id(parent_id, label, reqs, reqs_dir):  # implements: REQ-DECOMPOSE-994
    """`<parent>-<SLUG>`, with a trailing `-NNN` on the parent dropped first so the child
    reads `SCRIPTS-UTILS-LOAD-JSON-STDIN` rather than `REQ-FOO-012-LOAD-JSON-STDIN`. On
    collision a `-2`, `-3` suffix; the number sits last, where `_next_free_number` and
    `_warn_number_collision` expect one."""
    parts = parent_id.split("-")
    stem = "-".join(parts[:-1]) if len(parts) >= 3 and parts[-1].isdigit() else parent_id
    base = "{}-{}".format(stem, _group_slug(label))
    taken = set(reqs or ())
    try:
        taken |= {fn[:-3] for fn in os.listdir(reqs_dir) if fn.endswith(".md")}
    except OSError:
        pass
    cand, k = base, 2
    while cand in taken:
        cand = "{}-{}".format(base, k); k += 1
    return cand


def _case_raw_blocks(body):  # implements: REQ-DECOMPOSE-994
    """`{label: [line, ...]}` — each labelled case's own lines, indentation kept, so a
    moved case reads in the child exactly as it read in the parent. `_acc_blocks` folds a
    case to one line for counting and search; a Given/When/Then block is worth more than
    that on the page."""
    out, cur = {}, None
    for raw in _section_lines(body, ACCEPTANCE_LABELS, raw=True):
        m = _AC_LABEL_RE.match(raw.strip())
        if m:
            cur = m.group(1)
            out[cur] = [raw.rstrip()]
        elif cur is not None and raw.strip():
            out[cur].append(raw.rstrip())
    return out


def _assign_cases(blocks, groups):  # implements: REQ-DECOMPOSE-994
    """Which child each parent case belongs to: `{case_index: group_index}` for the cases
    whose text names exactly ONE group's subject. Zero matches or two-plus is left on the
    parent — assigning by guess is the failure mode, and reporting the unassigned count is
    the feature."""
    # whole-word: `is_headless` must not claim a case about `is_headless_mode`. A generic
    # label such as **Module** still matches "the module is imported" — that is the rule
    # working, and the reason every move is printed for a human to read.
    subjects = [re.compile(r"(?<![\w])" + re.escape(_group_subject(label).lower()) + r"(?![\w])")
                if _group_subject(label) else None for label, _ in groups]
    owner = {}
    for i, blk in enumerate(blocks):
        text = (blk.get("text", "") + " " + blk.get("label", "")).lower()
        hits = [g for g, rx in enumerate(subjects) if rx and rx.search(text)]
        if len(hits) == 1:
            owner[i] = hits[0]
    return owner


def _first_hit_line(code_root, rel, needle):
    # implements: REQ-DECOMPOSE-994
    """The first `file:line` in `rel` whose text matches `needle` on a def/class/
    function line, or None — one file's worth of `_expected_members`'s search."""
    try:
        with open(os.path.join(code_root, rel), encoding="utf-8", errors="ignore") as f:
            for n, line in enumerate(f, 1):
                if needle.search(line) and re.search(r"\b(def|class|function|func|fn)\b", line):
                    return "{}:{}".format(rel, n)
    except OSError:
        return None
    return None


def _expected_members(code_root, members, label):  # implements: REQ-DECOMPOSE-994
    """`file:line` hits for the group's subject inside the parent's `implements:` files —
    the code a child is EXPECTED to claim. Listed, never tagged."""
    subj = _group_subject(label)
    if not subj or not code_root:
        return []
    needle = re.compile(re.escape(subj))
    hits, seen = [], set()
    for role, rel, _ln in members or []:
        if role != "implements" or rel in seen:
            continue
        seen.add(rel)
        hit = _first_hit_line(code_root, rel, needle)
        if hit:
            hits.append(hit)
    return hits


def _plan_group_split(rid, r, reqs, reqs_dir, code_root, members):  # implements: REQ-DECOMPOSE-994
    """Everything a run would do to ONE requirement, computed without writing: the children,
    each child's clauses and cases, the expected members, what stays on the parent, and
    why the run refuses if it does. Dry-run prints this; --apply executes it."""
    body = r["body"]
    groups = _contract_groups(body)
    plan = {"id": rid, "groups": groups, "children": [], "refuse": None}
    if len(groups) < 2:
        plan["refuse"] = "fewer than two contract groups — nothing to split along"
        return plan
    if len(groups) > cfg.LINT_AC_MAX:
        plan["refuse"] = ("{} groups is {} children for one capability, which is the shape "
                          "ADR-0025 had to refold. Merge the labels down to {} or fewer, "
                          "then re-run.".format(len(groups), len(groups), cfg.LINT_AC_MAX))
        return plan
    blocks = _acc_blocks(body)
    raw_by_label = _case_raw_blocks(body)
    owner = _assign_cases(blocks, groups)
    used = set()
    for g, (label, clauses) in enumerate(groups):
        cases = [{"label": blocks[i]["label"],
                  "lines": raw_by_label.get(blocks[i]["label"], [blocks[i]["text"]])}
                 for i, og in sorted(owner.items()) if og == g]
        cid = _group_child_id(rid, label, set(reqs) | used, reqs_dir)
        used.add(cid)
        plan["children"].append({
            "id": cid, "label": label, "subject": _group_subject(label),
            "clauses": clauses, "cases": cases,
            "members": _expected_members(code_root, members, label),
        })
    plan["moved_cases"] = len(owner)
    plan["kept_cases"] = len(blocks) - len(owner)
    plan["kept_case_labels"] = [b.get("label", "") for i, b in enumerate(blocks) if i not in owner]
    return plan


def _render_group_child(plan_child, parent_id, meta, moved_total, unassigned):
    # implements: REQ-DECOMPOSE-994
    c = plan_child
    bullets = "\n".join("- " + cl for cl in c["clauses"])
    if c["cases"]:
        parts = []
        for n, blk in enumerate(c["cases"], 1):
            lines = list(blk["lines"])
            first = lines[0].strip() if lines else ""
            m = _AC_LABEL_RE.match(first)
            title = first[m.end():].strip(" —-–:") if m else ""
            head = "CASE-{}".format(n) + (" — " + title if title else "")
            body_lines = [l for l in lines[1:]]
            parts.append("\n".join([head] + body_lines))
        cases = "\n\n".join(parts)
    else:
        cases = ("CASE-1\n  Given  <precondition>\n  When   <action>\n"
                 "  Then   <observable, pass/fail result>")
    members = "\n".join("  - `{}`".format(m) for m in c["members"]) or (
        "  - (none found — search the parent's members for `{}` yourself)".format(c["subject"]))
    return GROUP_CHILD_TEMPLATE.format(
        new_id=c["id"], parent=parent_id, slug=_group_slug(c["label"]), label=c["label"],
        title=c["subject"] or c["label"], bullets=bullets, cases=cases, members=members,
        layer=meta.get("layer", "feature") or "feature", owner=meta.get("owner", "") or "",
        moved=len(c["cases"]), unassigned=unassigned)


def _rewrite_case_line(s, raw, out, moved_case_labels, skipping_case, counts):
    # implements: REQ-DECOMPOSE-994
    """One line of the parent's Cases section during rewrite: drop a moved case's
    lines (appending nothing), keep the rest, and never leave two blank lines where
    a moved case's block used to end. Mutates `out` in place; returns the updated
    (skipping_case, counts), counts being (cases_removed, cases_kept)."""
    cases_removed, cases_kept = counts
    m = _AC_LABEL_RE.match(s)
    if m:
        skipping_case = m.group(1) in moved_case_labels
        if skipping_case:
            return skipping_case, (cases_removed + 1, cases_kept)
        cases_kept += 1
    elif skipping_case and not s:
        skipping_case = False        # a blank ends the moved case's block
        if out and not out[-1].strip():
            # must not stack a second blank on the one already there
            return skipping_case, (cases_removed, cases_kept)
    if skipping_case:
        return skipping_case, (cases_removed, cases_kept)
    out.append(raw)
    return skipping_case, (cases_removed, cases_kept)


def _rewrite_parent_after_split(text, plan):  # implements: REQ-DECOMPOSE-994
    """The parent with each split group replaced by one obligation line ending in the
    child's id — the ARCH shape this corpus documents: intent, then one sentence per child
    with the detail living only in the child. Moved cases are removed; the cases that
    stayed keep their labels, because a label is an identifier a `verifies:` tag points at
    and renumbering would break every tag that does. Everything outside those two
    sections is byte-identical.

    A parent left with NO case gets one placeholder. The per-function cases went to the
    children; what this rung still owes is the one case that shows the children work
    TOGETHER, and the engine cannot write that — it can only say the hole is there."""
    PLACEHOLDER = [
        "CASE-1",
        "  Given  every child requirement listed above is confirmed on its own",
        "  When   this capability is exercised end to end",
        "  Then   <the ONE observable result that shows the children work TOGETHER — the",
        "         per-behaviour cases moved to the children; this rung asserts their composition>",
        "",
    ]
    lines = text.split("\n")
    out = []
    child_by_label = {c["label"]: c for c in plan["children"]}
    moved_case_labels = {b["label"] for c in plan["children"] for b in c["cases"]}
    in_contract = in_cases = False
    skipping_group = skipping_case = False
    cases_kept = cases_removed = 0

    def close_cases():
        # leaving the Cases section: if every case left, say what the rung still owes
        if in_cases and cases_removed and not cases_kept:
            while out and not out[-1].strip():
                out.pop()
            out.append("")
            out.extend(PLACEHOLDER)

    for raw in lines:
        s = raw.strip()
        if s.startswith("## "):
            if skipping_group and out and out[-1].strip():
                out.append("")               # the blank the skipped group used to end on
            close_cases()
            in_contract = any(_heading_label_is(s, n) for n in CONTRACT_LABELS)
            in_cases = any(_heading_label_is(s, n) for n in ACCEPTANCE_LABELS)
            skipping_group = skipping_case = False
            out.append(raw); continue
        if in_contract:
            if _is_label_line(raw):
                label = s.strip("*").strip()
                if label in child_by_label:
                    c = child_by_label[label]
                    out.append("- {} — see [[{}]].".format(c["subject"] or c["label"], c["id"]))
                    skipping_group = True
                    continue
                if skipping_group and out and out[-1].strip():
                    out.append("")           # an unsplit group follows a split one
                skipping_group = False
            if skipping_group:
                continue                     # the group's bullets now live in the child
            out.append(raw); continue
        if in_cases:
            skipping_case, (cases_removed, cases_kept) = _rewrite_case_line(
                s, raw, out, moved_case_labels, skipping_case, (cases_removed, cases_kept))
            continue
        out.append(raw)
    close_cases()
    return "\n".join(out)


def _plan_and_report(targets, reqs, reqs_dir, code_root, members):
    # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-994
    """Plan every target's split and print each one's summary as it is computed.
    Returns (plans, total_children, total_moved, total_kept)."""
    total_children = total_moved = total_kept = 0
    plans = []
    for rid in targets:
        plan = _plan_group_split(rid, reqs[rid], reqs, reqs_dir, code_root, members.get(rid))
        plans.append(plan)
        print("{}  ({} contract groups, {} cases)".format(
            rid, len(plan["groups"]), len(_acc_blocks(reqs[rid]["body"]))))
        if plan["refuse"]:
            print("  refused: {}".format(plan["refuse"]))
            for label, clauses in plan["groups"]:
                print("    **{}**  {} clause(s)".format(label, len(clauses)))
            continue
        for c in plan["children"]:
            print("  -> {:<40} {} clause(s), {} case(s), {} expected member(s)".format(
                c["id"], len(c["clauses"]), len(c["cases"]), len(c["members"])))
        print("  parent keeps {} case(s){}".format(
            plan["kept_cases"],
            ": " + ", ".join(l for l in plan["kept_case_labels"] if l)
            if plan["kept_cases"] else ""))
        total_children += len(plan["children"])
        total_moved += plan["moved_cases"]
        total_kept += plan["kept_cases"]
        m = reqs[rid]["meta"]
        exempt_stale = ("ac-count-high" in (_as_list(m.get("lint_exempt")) or [])
                        and plan["kept_cases"] <= cfg.LINT_AC_MAX)
        if exempt_stale:
            print("  note: `lint_exempt: [ac-count-high]` will silence nothing once the parent "
                  "holds {} case(s) — drop it.".format(plan["kept_cases"]))
    return plans, total_children, total_moved, total_kept


def _write_group_split(plans, reqs, reqs_dir):
    # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-994
    """Write every plan's children and rewrite its parent; returns files written."""
    written = 0
    for plan in plans:
        if plan["refuse"]:
            continue
        rid = plan["id"]; r = reqs[rid]
        unassigned = plan["kept_cases"]
        for c in plan["children"]:
            dest = os.path.join(reqs_dir, c["id"] + ".md")
            if os.path.exists(dest):
                print("  SKIP  {} exists".format(dest)); continue
            with open(dest, "w", encoding="utf-8") as f:
                f.write(_render_group_child(c, rid, r["meta"], plan["moved_cases"], unassigned))
            print("  wrote  requirements/{}.md".format(c["id"]))
            written += 1
        src = r.get("path") or os.path.join(reqs_dir, rid + ".md")
        try:
            with open(src, encoding="utf-8", newline="") as f:
                raw = f.read()
        except OSError:
            print("  SKIP  cannot read {} to rewrite it".format(src)); continue
        crlf = "\r\n" in raw
        new = _rewrite_parent_after_split(raw.replace("\r\n", "\n"), plan)
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(new.replace("\n", "\r\n") if crlf else new)
        print("  rewrote requirements/{} (each split group is now one "
              "line naming its child)".format(os.path.basename(src)))
    return written


def decomposable(r):  # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-994
    """True when a requirement's own group labels can be split into code-rung children:
    two or more groups, and not already at `level: code`. A code requirement's children
    would sit below the lowest rung there is, so its groups are its own structure, not
    seams to split along."""
    return (r["meta"].get("level") != "code"
            and len(_contract_groups(r["body"])) >= 2)


def cmd_decompose_groups(ws, only=None, apply_it=False, code_root=None):
    # implements: ARCH-DECOMPOSE-050  # implements: REQ-DECOMPOSE-994
    """Split a requirement into code-rung children along its own contract group labels.

    Returns None when nothing in scope carries a group, so the caller can fall through to
    the older clause-level path. Otherwise prints the plan and — with `apply_it` — writes
    the children and rewrites the parent, returning 0.

    The parent IS edited on apply. That is the point: the finding clears only when its
    case count drops, and a child that duplicates its parent's clauses byte-for-byte is
    a redundancy the engine would then report. So a confirmed parent drifts, visibly, and
    `sync --accept-drift` is the acknowledgement. `git checkout` of the parent plus
    deleting the children restores the corpus exactly."""
    reqs, reqs_dir = ws.reqs, ws.reqs_dir
    members = ws.members or {}
    if only and reqs[only]["meta"].get("level") == "code":
        print("{} is at `level: code`: its groups are its own structure, and a child would "
              "sit below the code rung. Nothing to split.".format(only))
        return 0
    targets = [only] if only else [rid for rid in sorted(reqs) if decomposable(reqs[rid])]
    if only and len(_contract_groups(reqs[only]["body"])) < 2:
        return None
    if not targets:
        return None
    plans, total_children, total_moved, total_kept = _plan_and_report(
        targets, reqs, reqs_dir, code_root, members)
    n_refused = sum(1 for p in plans if not p["refuse"])
    print("\n{} child requirement(s) from {} parent(s); {} case(s) move, {} stay on their parents."
          .format(total_children, n_refused, total_moved, total_kept))
    print("Children carry `level: code`, `level_source: auto`, `satisfies: <parent>`, "
          "`status: draft`.")
    print("No member tags are written — each child lists the members it is expected to claim.")
    if not apply_it:
        print("\nNothing written. Re-run with --apply. The parent IS rewritten on apply "
              "(moved groups")
        print("become one line each naming the child, moved cases leave), so a confirmed parent")
        print("drifts and `sync --accept-drift` is how you accept it. `git checkout` the "
              "parent and")
        print("delete the children to undo.")
        return 0
    written = _write_group_split(plans, reqs, reqs_dir)
    print("\n{} file(s) written. Next: review each child, tag its members, then `reqmap.py sync "
          "--accept-drift \"<why>\"`.".format(written))
    return 0
