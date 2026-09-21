"""The requirement template, the id/number checks around it, and frontmatter status."""
import os, re

from .parse import split_requirement_blocks


# The shape a requirement follows, kept after `new` was removed in v8.0.0 (ADR-0045
# decision 2: the template stays documented as the shape to follow). `draft` stamps
# extracted requirements out of it, and a person or an assistant writing one by hand
# reads it here.
# implements: REQ-NEWGONE-1034
REQUIREMENT_TEMPLATE = """\
---
id: AREA-NAME-NNN
status: draft        # draft | baseline | in-progress | implemented | confirmed | deprecated
layer: feature       # bus | feature | need | aggregate
owner: Alex
priority:            # must-have | should-have | could-have | wont-have (optional)
depends_on: []       # ids of bus/other capabilities this builds on
superseded_by:       # <ID>, if replaced
# level:             # optional: system | architecture | code — the V-model left arm.
#                    #   Adopting it turns on the level-fit and rung checks; a corpus
#                    #   that never sets it keeps the pre-V-model behaviour exactly.
# satisfies: []      # optional: the level above this one (system <- architecture <- code)
# area:              # optional: System Map grouping label (else the id prefix is used)
---

# Short name

## Description
> 1–3 plain sentences anyone can follow — what this is, why it exists, and what
> breaks without it. No jargon; this is the angle a non-expert reads first. The
> quote is rationale, not an obligation: it is not hashed and never trips drift.

Every bullet below is binding.
<!-- Audience: a developer new to this project. Six rules:
     1. Name the subject: "`init` creates the folder", never "It creates the folder".
     2. Present tense — no "shall", no "must". The line above already binds every clause.
     3. One binding statement per bullet, in at most three sentences; the extra
        sentences state the first's consequence, never a second obligation.
     4. Define project-specific terms inline on first use; programming terms need none.
     5. Group clauses past five, with bold labels (see below).
     6. Keep a clause to at most 3 sentences and 150 words — `lint` enforces both.
     Scope: one capability = one behavior that fails independently. Many clauses AND
     many acceptance criteria together mean several capabilities — split them
     (`lint` flags this as 'over-scoped'). -->

**What it does**
- `<subject>` does one thing, stated so a test could check it. No function names; true
  regardless of how the code is implemented.
  <!-- Rationale: why this specific behavior, one clause, only when not self-evident -->

**What it produces**
- `<subject>` returns <output shape and allowed values>.
- `<subject>` handles a missing or invalid optional input by <behavior>.

## Verify intent (open questions for the human)
- Observed: <a behavior that may be an AI accident — swallowed error, empty-string
  fallback, magic constant, unreachable branch>. Intended, or a bug to fix?

## Cases (= tests)
<!-- Write at least one case from the CALLER's side, not the implementation's: the
     cases an author reaches for first vary the quality of one kind of input and
     never its kind. `clarify` names that shape (case-monoculture).
     Keep Given/When/Then concrete and self-explanatory; spell out any term the
     Description introduced. -->
CASE-1  <!-- verifiable by: automated test | manual | inspection | load test -->
  Given  <precondition>
  When   <action>
  Then   <observable, pass/fail result>   (one test per case; each maps to tested-by)

## Context (non-binding)
<!-- Everything here is commentary: not hashed, not linted, never trips drift. On
     any conflict with the Description + Cases above, they win. Bold sub-labels
     are the same clause-group convention the Description uses (ADR-0017) — keep
     only the ones you need. -->
**Notes**
- A known fragility/footgun the implementer should know but which is NOT enforced.

**Example**
- e.g. Ana marks AUTH-001 confirmed, later edits its contract text; at commit
  `check` tells her "DRIFT — contract changed since lock" so she re-reviews.

**Current implementation**
- How the code does it today (the volatile narrative — may drift from the contract).

"""


def _set_frontmatter_status(text, value):
    # implements: ARCH-PROMOTE-011  # implements: REQ-PROMOTE-894
    """Replace the value of the first `status:` line inside the leading frontmatter
    block, preserving its indentation and any trailing inline comment. Returns
    (new_text, n_replaced); n=0 when there is no frontmatter or no status line."""
    body = text.lstrip("﻿")            # drop a BOM if present (rewritten without it)
    if not body.startswith("---"):
        return text, 0
    end = body.find("\n---", 3)
    if end == -1:
        return text, 0
    head, rest = body[:end], body[end:]     # only the frontmatter block, never the body
    # Replace only the VALUE, keeping any trailing inline comment (and its spacing).
    # The value group excludes '#' so a blank `status:  # hint` line is filled in
    # place instead of swallowing the '#' as the value (which glued the leftover
    # comment text onto the status, corrupting the YAML).
    def _repl(m):
        comment = m.group(3)
        if comment:
            return m.group(1) + " " + value + (m.group(2) or "  ") + comment
        return m.group(1) + " " + value
    new_head, n = re.subn(
        r"(?m)^([ \t]*status[ \t]*:)[ \t]*[^#\r\n]*?([ \t]*)(#[^\r\n]*)?$",
        _repl, head, count=1)
    return new_head + rest, n


def _write_frontmatter_status(r, new_status):  # implements: ARCH-PROMOTE-011
    """Set one requirement's `status:` in its own file, in place. Returns True on a
    write, False when the block has no `status:` line to change.

    newline="" on both ends: read/write the file's own line endings verbatim so a
    CRLF-committed requirement file isn't silently flipped to LF on a POSIX host
    (universal-newline translation on read + os.linesep on write would do exactly
    that). Per-line EOL, so a file with MIXED line endings keeps every untouched
    bare-LF line bare-LF — only the substituted VALUE changes."""
    with open(r["path"], encoding="utf-8-sig", newline="") as f:
        raw = f.read()
    orig_lines = raw.splitlines(keepends=True)
    line_eols = [ln[len(ln.rstrip("\r\n")):] for ln in orig_lines]
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n") if eol == "\r\n" else raw
    # A module file holds several requirements; flip the status of THIS one, not of
    # the first block in the file.  # implements: REQ-MODULEFILE-056
    blocks = split_requirement_blocks(text)
    if len(blocks) > 1:
        idx = r.get("block", 0)
        blocks[idx], n = _set_frontmatter_status(blocks[idx], new_status)
        new_text = "".join(blocks)
    else:
        new_text, n = _set_frontmatter_status(text, new_status)
    if n == 0:
        return False
    new_lines = new_text.splitlines()
    if len(new_lines) == len(line_eols):
        new_text = "".join(nl + le for nl, le in zip(new_lines, line_eols))
    elif eol == "\r\n":
        new_text = new_text.replace("\n", "\r\n")
    with open(r["path"], "w", encoding="utf-8", newline="") as f:
        f.write(new_text)
    return True


def _parse_todos_from_text(text):
    """Parse TODO.md content → list of {name, lane, milestone, done} dicts. Pure.
    Items before the first ## vX.Y heading are silently ignored (milestone is required)."""
    todos, current_ms = [], None
    for line in text.splitlines():
        # match the version token at the heading start; a trailing annotation
        # like `## v2.8 (deferred — demand-gated)` is harmless (the capture group
        # isolates the version) and must not drop the milestone's items.
        ms_m = re.match(r"^##\s+(v\d[\d.]*)\b", line.strip())
        if ms_m:
            current_ms = ms_m.group(1)
            continue
        item_m = re.match(r"^-\s+\[([ xX])\]\s+(.+)$", line.strip())
        if item_m and current_ms:
            done = item_m.group(1).lower() == "x"
            rest = item_m.group(2)
            if "|" in rest:
                name_part, meta = rest.rsplit("|", 1)
                name = name_part.strip()
                # one word: bug|feature (bus|ops still parse; the roadmap files them as features)
                lane_m = re.search(r"lane:\s*(\w+)", meta)
                lane = lane_m.group(1) if lane_m else "feature"
            else:
                name, lane = rest.strip(), "feature"
            todos.append({"name": name, "lane": lane, "milestone": current_ms, "done": done})
    return todos


def _parse_todos(root):  # implements: REQ-MAP-871
    """Read TODO.md; tries root first, then one level up (covers plugin/ dogfood layout).
    Returns list of todo dicts; empty list if absent in both locations."""
    for base in dict.fromkeys([root, os.path.dirname(os.path.abspath(root))]):
        path = os.path.join(base, "TODO.md")
        try:
            with open(path, encoding="utf-8") as f:
                return _parse_todos_from_text(f.read())
        except OSError:
            continue
    return []
