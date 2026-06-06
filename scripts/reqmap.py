#!/usr/bin/env python3
"""reqmap — requirement manager engine (stdlib only).

Subcommands:
  init              first-use bootstrap: scaffold requirements/ + .reqmapignore, draft
                    requirements from existing code, build the lock + map, print next steps
  new AREA-NAME-NNN   scaffold a requirement from the built-in template
  scan              list code members (implements/generated-from/... tags) per capability
  check             the gate: link sync + drift; exit non-zero on error (use in pre-commit/CI)
  map               generate requirements/_map.md (Mermaid) + _map.json (graph)
  export            emit the registry graph as requirements/_map.json (for a front-end)
  next              terminal 'what should I do next': counted, actionable risk buckets
  extract           draft requirements from legacy code (status: draft, risk-scored)

Layout on disk (relative to repo root, override with --root / --reqs / --code):
  requirements/*.md     the source of truth (markdown + YAML-ish frontmatter)
  <code>/**            scanned for tags like:  # implements: <ID>
"""
import argparse, ast, fnmatch, hashlib, json, os, re, subprocess, sys

ROLES = ("implements", "generated-from", "validated-against", "tested-by")
# the (?<![\w-]) left boundary stops substring matches like `reimplements:` or
# `x-implements:` from being picked up as a real `implements:` tag
TAG_RE = re.compile(r"(?<![\w-])(implements|generated-from|validated-against|tested-by)\s*:\s*([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)")
CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".cpp", ".h", ".hpp",
             ".cc", ".java", ".go", ".rs", ".html", ".css", ".sql", ".yaml", ".yml",
             ".md")  # .md scanned for tags so prose capabilities (prompts/specs) can be members

# ---- prose auto-draft classification (cmd_extract) ----
# These buckets govern AUTO behavior (drafting) ONLY. scan_members still honors an
# explicit tag on ANY file, regardless of bucket — buckets never suppress a real tag.
PROSE_EXTS = (".md", ".html")
# Bucket 1 — meta/boilerplate: never auto-drafted, never sync-checked. Basename match.
META_IGNORE_NAMES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md", "CONTRIBUTING.md",
                     "SKILL.md", "TODO.md", "CHANGELOG.md"}

VALID_STATUS = {"draft", "baseline", "in-progress", "implemented", "confirmed", "deprecated"}
VALID_LAYER = {"bus", "feature"}
ENFORCED = {"in-progress", "implemented", "confirmed"}
# System Map declutter: hide depends_on edges into a node this many capabilities
# depend on (a hub) — the bus is hidden regardless of count. Full graph stays in
# the Dependency Map tab.
SYSTEM_HUB_FANIN = 8

# Scripted, deterministic guidance per risk signal — surfaced in the Risk tab,
# the detail panel, and the _map.md risk table so a flagged requirement comes
# with a concrete next action, not just a color.
RISK_ADVICE = {
    "unimplemented": "Confirmed but no code linked: tag the implementing code "
                     "`# implements: <ID>`, or drop status back to in-progress/draft "
                     "until it is built. A confirmed requirement must point to code.",
    "unreviewed": "Draft/baseline, not yet validated: review the contract, wire its "
                  "`tested-by` tests, then promote to `confirmed`. Until then it is "
                  "tracked, not enforced.",
    "untested": "Implemented but no `tested-by` member: write an acceptance test and tag "
                "it `# tested-by: <ID>`, or set `test_exempt: <reason>` in the frontmatter "
                "to acknowledge it intentionally and silence this signal.",
    "unverified-intent": "Has open `## WHAT — Verify intent` question(s): run "
                         "`reqmap.py findings`, resolve each in `requirements/_findings.md`, "
                         "then fold the answer into the Contract or delete the bullet.",
}

# Bumped on any change to this engine. `check` warns a seeded repo when its
# vendored copy is older than the installed plugin's. ISO date with an optional
# `.N` same-day revision suffix (YYYY-MM-DD[.N]): lexicographic order ==
# chronological order, so a plain string compare is enough.
MAP_ENGINE_VERSION = "2026-06-05.2"


# ---------- parsing ----------
def _as_list(v):  # implements: CORE-PARSE-001
    """Coerce a frontmatter value to a list: lists pass through, a bare scalar
    becomes a one-element list, empty/None becomes []. Guards callers that
    iterate list-valued keys (e.g. depends_on) against a string written without
    brackets being walked character-by-character."""
    if isinstance(v, list):
        return v
    return [v] if v else []


def _clean_item(s):  # implements: CORE-PARSE-001
    """One list element: drop a trailing `# comment`, trim, strip matching quotes."""
    return s.split("#", 1)[0].strip().strip("\"'")


def parse_frontmatter(text):  # implements: CORE-PARSE-001
    """Return (meta_dict, body). Minimal YAML: scalars, inline [a, b] lists, and the
    block form (`key:` then indented `- item` lines). An inline list missing its
    closing `]` is parsed leniently rather than silently kept as a literal string."""
    meta, body = {}, text.lstrip("﻿")  # tolerate a stray UTF-8 BOM
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            block = body[3:end]
            body = body[end + 4:].lstrip("\n")
            lines = block.splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]; i += 1
                s = line.strip()
                if not s or s.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k, v = k.strip(), v.strip()
                if v.startswith("["):
                    # inline list; tolerate a missing `]` (lenient) — a '#' inside
                    # the brackets is data, a '#' after the close is a comment
                    inner = v[1:v.index("]")] if "]" in v else v[1:]
                    meta[k] = [x for x in (_clean_item(x) for x in inner.split(",")) if x]
                elif not v:
                    # block-style list: consume following indented `- item` lines.
                    # No items -> keep the empty scalar (e.g. an unset superseded_by).
                    items = []
                    while i < len(lines) and lines[i].lstrip().startswith("- "):
                        items.append(_clean_item(lines[i].lstrip()[2:]))
                        i += 1
                    meta[k] = [x for x in items if x] if items else ""
                else:
                    v = v.split("#", 1)[0].rstrip()      # inline comment
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]                       # strip matching quotes
                    meta[k] = v
    return meta, body


def load_requirements(reqs_dir):  # implements: CORE-PARSE-001
    reqs = {}
    if not os.path.isdir(reqs_dir):
        return reqs
    for name in sorted(os.listdir(reqs_dir)):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        path = os.path.join(reqs_dir, name)
        with open(path, encoding="utf-8-sig") as f:  # tolerate a UTF-8 BOM
            text = f.read()
        meta, body = parse_frontmatter(text)
        rid = meta.get("id") or os.path.splitext(name)[0]
        reqs[rid] = {"meta": meta, "body": body, "path": path}
    return reqs


def _prune_dirs(dirpath, dirs, reqs_dir):  # implements: CORE-SCAN-002
    """Drop noise dirs and the SSOT output dir from an os.walk in place.

    Excludes ONLY the actual requirements dir (by realpath), not every folder
    that happens to be named 'requirements' — a source package named
    requirements/ must still be scanned."""
    reqs_real = os.path.realpath(reqs_dir) if reqs_dir else None
    keep = []
    for d in dirs:
        if d in (".git", "node_modules", "__pycache__"):
            continue
        if reqs_real and os.path.realpath(os.path.join(dirpath, d)) == reqs_real:
            continue
        keep.append(d)
    dirs[:] = keep


def load_ignore(code_root, reqs_dir=None):  # implements: CORE-SCAN-002
    """Read optional `.reqmapignore` (fnmatch globs over POSIX rel paths, one per
    line, blanks and # comments skipped). Looked up in `requirements/` first (the
    consolidated home for reqmap files) then at the scan root; first found wins.
    Patterns are still matched against repo-root-relative paths regardless of where
    the file lives. Fail-open: a missing/unreadable file yields no patterns."""
    pats = []
    for base in ([reqs_dir] if reqs_dir else []) + [code_root]:
        try:
            with open(os.path.join(base, ".reqmapignore"), encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith("#"):
                        pats.append(s)
            break   # first .reqmapignore found wins
        except OSError:
            continue
    return pats


def scan_members(code_root, reqs_dir=None):  # implements: CORE-SCAN-002
    members = {}  # cap_id -> list[(role, file, line)]
    ignore = load_ignore(code_root, reqs_dir)
    for dirpath, dirs, files in os.walk(code_root):
        _prune_dirs(dirpath, dirs, reqs_dir)
        for fn in files:
            if not fn.endswith(CODE_EXTS):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, code_root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
                continue
            try:
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        seen = set()
                        for role, cap in TAG_RE.findall(line):
                            key = (role, cap)
                            if key in seen:        # same tag twice on one line
                                continue
                            seen.add(key)
                            members.setdefault(cap, []).append((role, rel, i))
            except OSError:
                continue
    return members


# ---------- hashing / drift ----------
def binding_hash(body):  # implements: CORE-DRIFT-003
    """Hash only the NORMATIVE sections — the Contract and the Acceptance criteria.
    Everything else (Verify-intent, Notes, Current-implementation, links) is
    commentary and may drift freely without tripping the gate. (Legacy docs used
    Input/Output/Acceptance; those headers are still honored for back-compat.)"""
    keep, grab = [], False
    for line in body.splitlines():
        h = line.strip().lower()
        if h.startswith("## "):
            grab = any(s in h for s in ("contract", "acceptan", "input", "output"))
            continue
        if grab and line.strip():
            keep.append(line.strip())
    return hashlib.sha256("\n".join(keep).encode()).hexdigest()[:12]


def lock_path(reqs_dir):  # implements: CORE-DRIFT-003
    return os.path.join(reqs_dir, "_reqlock.json")


def load_lock(reqs_dir):  # implements: CORE-DRIFT-003
    p = lock_path(reqs_dir)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}  # empty / corrupt / merge-conflicted lock: treat as no lock
    return {}


def save_lock(reqs_dir, lock):  # implements: CORE-DRIFT-003
    os.makedirs(reqs_dir, exist_ok=True)
    with open(lock_path(reqs_dir), "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, sort_keys=True)


# ---------- commands ----------
def _has_section(body, name):  # implements: REQ-CHECK-006
    """True if the body has a `## ` heading whose text contains `name` (case-insensitive).
    Used to detect legacy-schema requirements that lack a `## WHAT — Verify intent`
    section — `findings` mines only that section, so its absence means findings is
    silently inactive for that requirement."""
    name = name.lower()
    for line in body.splitlines():
        s = line.strip().lower()
        if s.startswith("## ") and name in s:
            return True
    return False


def cmd_scan(reqs, members):  # implements: REQ-SCAN-005
    for cap in sorted(set(list(reqs) + list(members))):
        print(cap)
        for role, fp, ln in members.get(cap, []):
            print(f"    {role:18} {fp}:{ln}")
        if cap not in members:
            print("    (no members found)")


def _engine_version_at(path):
    """Best-effort MAP_ENGINE_VERSION parsed from a reqmap.py at `path`; None on any failure."""
    try:
        with open(path, encoding="utf-8") as f:
            m = re.search(r'MAP_ENGINE_VERSION\s*=\s*"([^"]+)"', f.read(4000))
        return m.group(1) if m else None
    except Exception:  # fail open — never let the staleness probe break the gate
        return None


def warn_if_stale():  # implements: REQ-CHECK-006
    """Print a non-fatal notice when this vendored copy is older than the installed
    plugin's. Silent in CI: only runs when CLAUDE_PLUGIN_ROOT is set. Never raises,
    never affects the exit code."""
    try:
        root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if not root:
            return
        plugin_ver = _engine_version_at(os.path.join(root, "scripts", "reqmap.py"))
        if plugin_ver and plugin_ver > MAP_ENGINE_VERSION:
            print(f"WARN  vendored reqmap.py is stale ({MAP_ENGINE_VERSION} < plugin "
                  f"{plugin_ver}) - re-seed: cp \"$CLAUDE_PLUGIN_ROOT/scripts/reqmap.py\" "
                  f"scripts/reqmap.py")
    except Exception:
        return


def cmd_check(reqs, members, reqs_dir, update_lock):  # implements: REQ-CHECK-006
    errors, warns = [], []
    warn_if_stale()
    cap_ids = set(reqs)

    for cap, hits in members.items():
        if cap not in cap_ids:
            errors.append(f"dangling tag: code references {cap} but no requirement exists")

    for rid, r in reqs.items():
        m = r["meta"]
        if m.get("status") not in VALID_STATUS:
            errors.append(f"{rid}: invalid status {m.get('status')!r}")
        if m.get("layer") not in VALID_LAYER:
            errors.append(f"{rid}: invalid layer {m.get('layer')!r}")
        for dep in _as_list(m.get("depends_on")):
            if dep not in cap_ids:
                errors.append(f"{rid}: depends_on missing {dep}")
        impls = [x for x in members.get(rid, []) if x[0] == "implements"]
        if m.get("status") in ENFORCED and not impls:
            errors.append(f"{rid}: status {m['status']} but no implements: tag found in code")
        tests = [x for x in members.get(rid, []) if x[0] == "tested-by"]
        if m.get("status") == "confirmed" and not tests and not m.get("test_exempt"):
            warns.append(f"{rid}: confirmed but no tested-by: tag — acceptance tests not linked")
        if m.get("status") == "confirmed":
            if not _has_section(r["body"], "contract"):
                warns.append(
                    f"{rid}: confirmed but missing '## WHAT — Contract' section — "
                    "add the normative contract or drop status back to in-progress"
                )
            if not _has_section(r["body"], "acceptan"):
                warns.append(
                    f"{rid}: confirmed but missing '## HOW — Acceptance' section — "
                    "add acceptance criteria or drop status back to in-progress"
                )

    lock = load_lock(reqs_dir)
    # load_lock fails open ({}) on an absent OR corrupt/merge-conflicted lock; the
    # two look identical to the drift loop (every `old` is None -> no drift ever
    # fires). Surface the corrupt case so a silently-disabled drift signal is visible.
    lp = lock_path(reqs_dir)
    if os.path.exists(lp):
        try:
            with open(lp, encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, OSError):
            warns.append("_reqlock.json present but unreadable (corrupt/merge-conflicted) "
                         "— drift detection skipped this run; re-run with --update-lock")
    new_lock = {}
    for rid, r in reqs.items():
        h = binding_hash(r["body"])
        new_lock[rid] = h
        old = lock.get(rid)
        if old and old != h and r["meta"].get("status") == "confirmed":
            # name the member locations so the warning is actionable, not "its members"
            locs = [f"{fp}:{ln}" for (_role, fp, ln) in members.get(rid, [])]
            where = ", ".join(locs) if locs else "no members tagged — add an implements: tag"
            warns.append(f"{rid}: DRIFT — contract changed since lock; "
                         f"re-check {len(locs)} member(s): {where}")

    # Health signals (non-blocking): how much of the corpus is human-validated, and
    # how much still uses the legacy body schema. Surfaced so an all-baseline corpus
    # (drift fires only on `confirmed`, so the gate enforces nothing yet) and a
    # silently-inactive `findings` cannot be mistaken for a clean, enforcing SSOT.
    n_confirmed = sum(1 for r in reqs.values() if r["meta"].get("status") == "confirmed")
    legacy = [rid for rid in sorted(reqs)
              if not _has_section(reqs[rid]["body"], "verify intent")]
    if legacy:
        warns.append("{}/{} requirement(s) use the legacy schema (no '## WHAT — Verify "
                     "intent' section) — `findings` is inactive for them: {}"
                     .format(len(legacy), len(reqs), ", ".join(legacy)))

    for w in warns:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)

    if update_lock:
        save_lock(reqs_dir, new_lock)
        print("lock updated.")

    n_find = sum(len(items) for _rid, _t, items in collect_findings(reqs))
    if n_find:
        print(f"info  {n_find} open verify-intent finding(s) — run `reqmap.py findings`")

    print(f"\n{len(reqs)} requirements ({n_confirmed} confirmed, {len(legacy)} legacy-schema), "
          f"{sum(len(v) for v in members.values())} members, "
          f"{len(errors)} errors, {len(warns)} warnings.")
    return 1 if errors else 0


# Built-in scaffold so `new` needs no separate templates/ dir — the engine is
# self-contained (one file). An on-disk templates/requirement.md still overrides
# it when cmd_new is given a tmpl_path that exists.
REQUIREMENT_TEMPLATE = """\
---
id: AREA-NAME-NNN
status: draft        # draft | baseline | in-progress | implemented | confirmed | deprecated
layer: feature       # bus | feature
owner: Alex
depends_on: []       # ids of bus/other capabilities this builds on
superseded_by:       # <ID>, if replaced
# area:              # optional: System Map grouping label (else the id prefix is used)
---

# Short name

> WHY: one line — what this is, in plain language.

## WHAT — Contract (normative)
<!-- Audience: a developer new to THIS project. Define project-specific terms inline
     on first use; attach roles to named components; keep "shall" phrasing. -->
- The feature shall ... (one binding, testable behavior per line; "shall" phrasing;
  no function names; true regardless of how the code is implemented).
- Output shape + allowed values; required vs optional inputs and how it degrades
  when an optional input is missing/invalid; the decision logic that selects each
  output (say so explicitly if it is delegated to a model/heuristic).

## WHAT — Verify intent (open questions for the human)
- Observed: <a behavior that may be an AI accident — swallowed error, empty-string
  fallback, magic constant, unreachable branch>. Intended, or a bug to fix?

## WHAT — Notes & known limitations (informative)
- A known fragility/footgun the implementer should know but which is NOT enforced.

## HOW — Acceptance (= tests)
<!-- Audience: a developer new to THIS project. Keep Given/When/Then concrete and
     self-explanatory; spell out any term the Contract introduced. -->
AC-1
  Given  <precondition>
  When   <action>
  Then   <observable, pass/fail result>   (one test per AC; each maps to tested-by)

## WHERE — Current implementation
- How the code does it today (the volatile narrative — may drift from the contract).

## WHERE — Members in code (auto)
"""


def cmd_new(reqs_dir, tmpl_path, cap_id):  # implements: REQ-NEW-004
    dest = os.path.join(reqs_dir, cap_id + ".md")
    if os.path.exists(dest):
        print(f"exists: {dest}"); return 1
    t = None
    if tmpl_path:                      # an on-disk template, if supplied, wins
        try:
            with open(tmpl_path, encoding="utf-8") as f:
                t = f.read()
        except OSError:
            t = None
    if t is None:                      # otherwise use the built-in scaffold
        t = REQUIREMENT_TEMPLATE
    t = t.replace("AREA-NAME-NNN", cap_id)
    os.makedirs(reqs_dir, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(t)
    print(f"created {dest}")
    return 0


def _set_frontmatter_status(text, value):  # implements: REQ-PROMOTE-011
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
    new_head, n = re.subn(r"(?m)^(\s*status\s*:\s*)(\S+)", r"\g<1>" + value, head, count=1)
    return new_head + rest, n


def cmd_promote(reqs, members, cap_id):  # implements: REQ-PROMOTE-011
    """Flip a requirement's status to `confirmed` (the human-validation step) by a
    single frontmatter edit. Refuses if the requirement has no `implements:` member
    (a confirmed requirement must point to code — else the gate would error), and
    warns when no `tested-by:` member is linked."""
    r = reqs.get(cap_id)
    if not r:
        print(f"no requirement with id {cap_id} (expected requirements/{cap_id}.md)")
        return 1
    cur = r["meta"].get("status")
    if cur == "confirmed":
        print(f"{cap_id} is already confirmed.")
        return 0
    roles = [m[0] for m in members.get(cap_id, [])]
    if "implements" not in roles:
        print(f"refusing: {cap_id} has no `implements:` member — a confirmed requirement "
              f"must point to code. Tag the implementing code `# implements: {cap_id}` first.")
        return 1
    with open(r["path"], encoding="utf-8-sig") as f:
        text = f.read()
    new_text, n = _set_frontmatter_status(text, "confirmed")
    if n == 0:
        print(f"could not find a `status:` line in {r['path']}")
        return 1
    with open(r["path"], "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"promoted {cap_id}: {cur or '(unset)'} -> confirmed")
    if "tested-by" not in roles:
        print(f"  note: no `tested-by:` member — wire an acceptance test (`# tested-by: {cap_id}`) "
              f"or set `test_exempt: <reason>` to silence the untested signal.")
    print("  next: reqmap.py check --update-lock  &&  reqmap.py map")
    return 0


def _draft_id(rel):  # implements: REQ-EXTRACT-008
    """Mint a draft capability id from a file's relative path. Path-aware so
    same-basename files in different dirs don't collide; falls back to FILE when
    the name has no usable A-Z0-9 token (e.g. `_.py`, non-ASCII stems)."""
    slug = re.sub(r"[^A-Z0-9]+", "-", os.path.splitext(rel)[0].upper()).strip("-")
    return "DRAFT-" + (slug or "FILE")


def classify_prose(rel):  # implements: REQ-EXTRACT-008
    """Bucket a POSIX-relative .md/.html path for the auto-draft path. Returns
    'ignore' (meta/boilerplate, invisible), 'sync_only' (README/docs/*.html — never
    drafted, but a drift- and semantic-checked member when explicitly tagged), or
    'capability' (prompt/spec prose — auto-drafted as a `draft` stub). Governs AUTO
    behavior only: scan_members still honors an explicit tag on any file."""
    base = os.path.basename(rel)
    # Bucket 1 — meta/boilerplate.
    if base in META_IGNORE_NAMES:
        return "ignore"
    if base == "LICENSE" or base.startswith("LICENSE."):
        return "ignore"
    if base.startswith("_"):                      # generated _map.*, _findings.md
        return "ignore"
    # Bucket 2 — sync-only.
    if base == "README" or base.startswith("README."):
        return "sync_only"
    if rel == "docs" or rel.startswith("docs/"):
        return "sync_only"
    if rel.endswith(".html"):                      # all HTML is an overview/derived doc
        return "sync_only"
    # Bucket 3 — capability source (prompts/specs/modes and other prose .md).
    return "capability"


def _prose_facts(src):  # implements: REQ-EXTRACT-008
    """(title, [headings]) from markdown/HTML prose, for a draft scaffold.
    Title: markdown frontmatter `title:`, else first `# ` H1, else <title>/<h1>.
    Headings: markdown `## ` H2 lines, else <h2>. Returns (None, []) when absent.
    The scaffold lists headings as an authoring hint — never the contract."""
    meta, body = parse_frontmatter(src)
    title = meta.get("title") or None
    headings = []
    for line in body.splitlines():
        s = line.strip()
        if title is None:
            m = re.match(r"#\s+(.+)", s)                      # markdown H1
            if m:
                title = m.group(1).strip()
                continue
            m = re.search(r"<(?:title|h1)[^>]*>(.*?)</(?:title|h1)>", s, re.I)
            if m:
                title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                # no continue: a line may carry both <title> and <h2> (see test_html_title_and_h2)
        m = re.match(r"##\s+(.+)", s)                         # markdown H2 (not H3)
        if m:
            headings.append(m.group(1).strip())
            continue
        for inner in re.findall(r"<h2[^>]*>(.*?)</h2>", s, re.I):  # html H2
            headings.append(re.sub(r"<[^>]+>", "", inner).strip())
    return title, headings


def cmd_extract(reqs, members, code_root, reqs_dir):  # implements: REQ-EXTRACT-008
    """Propose DRAFT requirements for code files that have no member tag yet."""
    tagged = {fp for hits in members.values() for (_, fp, _) in hits}
    ignore = load_ignore(code_root, reqs_dir)   # honor .reqmapignore, same as scan
    proposed, used = 0, set()
    os.makedirs(reqs_dir, exist_ok=True)
    for dirpath, dirs, files in os.walk(code_root):
        _prune_dirs(dirpath, dirs, reqs_dir)   # skip noise + the SSOT output dir
        dirs.sort()                            # deterministic id/suffix assignment
        for fn in sorted(files):
            is_code = fn.endswith((".py", ".js", ".ts", ".cpp", ".c"))
            is_prose = fn.endswith(PROSE_EXTS)
            if not (is_code or is_prose):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), code_root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in ignore):  # ignored -> never draft
                continue
            if rel in tagged:
                continue
            if is_prose and classify_prose(rel) != "capability":
                continue                           # bucket 1/2 -> never auto-drafted
            cap = base = _draft_id(rel)
            k = 2
            while cap in used:                 # residual collision (case/ext only)
                cap = "{}-{}".format(base, k); k += 1
            used.add(cap)
            dest = os.path.join(reqs_dir, cap + ".md")
            if os.path.exists(dest):
                continue
            with open(os.path.join(dirpath, fn), encoding="utf-8", errors="ignore") as f:
                src = f.read()
            if is_prose:
                title, headings = _prose_facts(src)
                review = "REVIEW"   # intent is unrecoverable from prose — always author
                hint = "\n".join("  - {}".format(h) for h in headings) \
                    or "  - (no section headings detected)"
                # str.format (not f-string): the template embeds literal {cap}/{rel} inside backticked instructions
                with open(dest, "w", encoding="utf-8") as f:
                    f.write("---\nid: {cap}\nstatus: draft\nlayer: feature\n"
                            "owner: auto\ndepends_on: []\n"
                            "risk: 2  # REVIEW — prose capability, author the contract "
                            "before promoting\n---\n\n"
                            "# {title}\n\n"
                            "> DRAFT extracted from {rel} (prose capability). The source "
                            "prose is NOT the contract — author the normative behavior "
                            "below, then tag the source `# generated-from: {cap}` "
                            "(HTML: `<!-- generated-from: {cap} -->`) and promote.\n\n"
                            "## WHAT — Contract (normative)\n"
                            "- TODO: the capability this prose defines (author from "
                            "intent, do not copy the prose).\n\n"
                            "## WHAT — Verify intent (open questions for the human)\n"
                            "- TODO: which source sections are normative vs illustrative?\n\n"
                            "Source sections detected (authoring hint, not the contract):\n"
                            "{hint}\n\n"
                            "## HOW — Acceptance (= tests)\n"
                            "- TODO: Given/When/Then checks for the contract above.\n\n"
                            "## WHERE — Current implementation\n- {rel}\n".format(
                                cap=cap, title=(title or os.path.splitext(fn)[0]),
                                rel=rel, hint=hint))
            else:
                risk = _risk(src)
                review = "REVIEW" if risk >= 2 else "auto-baseline"
                with open(dest, "w", encoding="utf-8") as f:
                    # new emission schema (Contract / Verify-intent / Acceptance / Current-impl),
                    # matching cmd_new so a promoted draft needs no reshaping
                    f.write(f"---\nid: {cap}\nstatus: draft\nlayer: feature\n"
                            f"owner: auto\ndepends_on: []\n"
                            f"risk: {risk}  # {review} — author triage hint, not read by the engine\n---\n\n"
                            f"# {os.path.splitext(fn)[0]}\n\n"
                            f"> DRAFT extracted from {rel}. Describes observed behavior, "
                            f"not validated intent.\n\n"
                            f"## WHAT — Contract (normative)\n"
                            f"- TODO: the observed behavior (characterization — correctness UNVERIFIED).\n\n"
                            f"## WHAT — Verify intent (open questions for the human)\n"
                            f"- TODO: anything that looks like an accident (swallowed error, magic "
                            f"constant, dead branch) — intended, or a bug to fix?\n\n"
                            f"## HOW — Acceptance (= tests)\n"
                            f"- characterization: current behavior captured, correctness UNVERIFIED\n\n"
                            f"## WHERE — Current implementation\n- {rel}\n")
            proposed += 1
            print(f"{review:14} {cap}  <- {rel}")
    print(f"\n{proposed} draft requirements proposed. Review the REVIEW ones before promoting.")
    return 0


def _risk(src):  # implements: REQ-EXTRACT-008
    score = 0
    if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", src): score += 1
    if "# noqa" in src or "eslint-disable" in src: score += 1
    if len(src.splitlines()) > 300: score += 1
    return score


# ---------- candidates (capability extraction plan) ----------
# Stage 1 of AI extraction: gather the raw material an authoring step (a human or
# an LLM agent) needs to write a real, capability-level requirement. READ-ONLY —
# emits a JSON plan, writes NO .md, so it cannot repeat extract's empty-stub failure.
CANDIDATE_EXTS = (".py", ".js", ".ts", ".tsx", ".jsx")
BUS_FANIN_THRESHOLD = 5      # a module this many capabilities depend on is bus-like
SPLIT_LOC_THRESHOLD = 300    # oversize file -> flag for human split, do not auto-split


def _py_facts(src):  # implements: REQ-CANDIDATES-009
    """Module/symbol docstrings, top-level signatures and import targets via the
    stdlib `ast`. A SyntaxError yields empty facts so one unparseable file never
    aborts the whole plan."""
    facts = {"signatures": [], "docstrings": {}, "imports": []}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return facts
    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        facts["docstrings"]["module"] = mod_doc.strip().splitlines()[0][:200]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts["signatures"].append("def {}({})".format(
                node.name, ", ".join(a.arg for a in node.args.args)))
        elif isinstance(node, ast.ClassDef):
            facts["signatures"].append("class {}".format(node.name))
        else:
            continue
        d = ast.get_docstring(node)
        if d:
            facts["docstrings"][node.name] = d.strip().splitlines()[0][:200]
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imports.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.add(node.module.split(".")[0])
    facts["imports"] = sorted(imports)
    return facts


def _js_facts(src):  # implements: REQ-CANDIDATES-009
    """Best-effort JS/TS facts via regex (no stdlib JS parser): the leading block
    comment as the module doc, and top-level function/binding names. Imports are
    not resolved for JS in v1 (the agent and _capmap.json fill that gap)."""
    facts = {"signatures": [], "docstrings": {}, "imports": []}
    # Leading block comment via plain string scan over a capped prefix — NOT a regex.
    # The old `/\*+(.*?)\*/` backtracks O(n^2) on a file opening with a long run of
    # `*` (a DoS on `candidates`); str.find is linear and cannot backtrack. The
    # leading `*`s of `/***` are stripped by the per-line `.strip(" *")` below.
    head_src = src[:8000].lstrip()
    if head_src.startswith("/*"):
        close = head_src.find("*/", 2)
        if close != -1:
            head = [ln.strip(" *") for ln in head_src[2:close].strip().splitlines()
                    if ln.strip(" *")]
            if head:
                facts["docstrings"]["module"] = head[0][:200]
    names = re.findall(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", src)
    names += re.findall(r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", src)
    facts["signatures"] = list(dict.fromkeys(names))   # dedupe, keep order
    return facts


def _md_facts(src):  # implements: REQ-CANDIDATES-009
    """Best-effort capability facts from a Markdown prompt/spec file (no parser):
    the first H1 (`# `) is the title, the first blockquote (`>`) AFTER that H1 is the
    intent, and each `## ` H2 heading is a structural-signature line. Free prose is
    never hashed — these facts only seed a human-authored requirement (Stage 2); the
    binding hash anchors on the authored Contract+Acceptance, like any code requirement."""
    facts = {"signatures": [], "docstrings": {}, "imports": []}
    title, intent, after_h1 = None, None, False
    for line in src.splitlines():
        s = line.strip()
        if title is None and s.startswith("# "):
            title = s[2:].strip(); after_h1 = True; continue
        if after_h1 and intent is None and s.startswith(">"):
            intent = s.lstrip(">").strip()
        if s.startswith("## "):
            facts["signatures"].append("## " + s[3:].strip())
    if title:
        facts["docstrings"]["title"] = title[:200]
    if intent:
        facts["docstrings"]["module"] = intent[:200]
    return facts


def _file_facts(path, rel):  # implements: REQ-CANDIDATES-009
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            src = f.read()
    except OSError:
        return {"signatures": [], "docstrings": {}, "imports": [], "loc": 0}
    if rel.endswith(".py"):
        facts = _py_facts(src)
    elif rel.endswith(".md"):
        facts = _md_facts(src)
    else:
        facts = _js_facts(src)
    facts["loc"] = len(src.splitlines())
    facts["signatures"] = facts["signatures"][:40]
    return facts


def _load_capmap(reqs_dir):  # implements: REQ-CANDIDATES-009
    """Optional `requirements/_capmap.json`: a hand-authored capability grouping,
    authoritative when present. Shape: {"capabilities": [{id, layer, files:[...]}]}
    (a bare list is also accepted). Returns []; fail-open on absent/unreadable."""
    try:
        with open(os.path.join(reqs_dir, "_capmap.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    caps = data.get("capabilities", []) if isinstance(data, dict) else data
    out = []
    if isinstance(caps, list):
        for c in caps:
            if isinstance(c, dict) and c.get("id") and c.get("files"):
                out.append({"id": c["id"], "layer": c.get("layer"),
                            "files": [f.replace(os.sep, "/") for f in _as_list(c["files"])]})
    return out


def _mint_cap_id(rel):  # implements: REQ-CANDIDATES-009
    """A TAG_RE-valid suggested id from a path stem (Stage 2 may rename it)."""
    slug = re.sub(r"[^A-Z0-9]+", "-", os.path.splitext(rel)[0].upper()).strip("-")
    return (slug or "MOD") + "-001"


def _collect_files(code_root, reqs_dir, md_globs=None):  # implements: REQ-CANDIDATES-009
    """Sorted rel paths of candidate source files, honoring _prune_dirs (noise +
    the SSOT dir) and .reqmapignore — the same exclusions scan_members uses.

    `md_globs` is the opt-in, scope-bounding allowlist for non-code discovery: a
    `.md` file is included ONLY when it matches one of these globs (and is not
    ignored). Empty/None -> no `.md` is ever collected (behavior unchanged). The
    presence of a glob IS the opt-in; there is no separate on/off flag."""
    ignore = load_ignore(code_root, reqs_dir)   # match scan_members: look in requirements/ first
    md_globs = md_globs or []
    out = []
    for dirpath, dirs, files in os.walk(code_root):
        _prune_dirs(dirpath, dirs, reqs_dir)
        dirs.sort()
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(dirpath, fn), code_root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
                continue
            if fn.endswith(CANDIDATE_EXTS):
                out.append(rel)
            elif fn.endswith(".md") and any(fnmatch.fnmatch(rel, g) for g in md_globs):
                out.append(rel)
    return out


def cmd_candidates(reqs, members, code_root, reqs_dir, out, md_globs=None):  # implements: REQ-CANDIDATES-009
    """Emit a deterministic JSON capability-extraction plan and write NO .md.
    Grouping: authoritative `requirements/_capmap.json` when present, else one
    candidate per file (the Stage-2 agent merges/splits using judgment).
    `md_globs` opts non-code `.md` files (prompts, specs) into discovery — advisory
    only, never auto-written; a human authors + confirms each into the SSOT."""
    files = _collect_files(code_root, reqs_dir, md_globs)
    facts_by_file = {rel: _file_facts(os.path.join(code_root, rel), rel) for rel in files}

    tagged = {}   # file -> already-implemented requirement id (idempotency hint)
    for cap, hits in members.items():
        for role, fp, _ln in hits:
            if role == "implements":
                tagged.setdefault(fp, cap)

    # depends_on is resolved by matching an import name to a file STEM. Known
    # limitation (Stage-1 heuristic): an import that shadows a stdlib/3rd-party name
    # (e.g. `import json` next to a local json.py) or collides with a same-basename
    # file in another dir can yield a false edge — the Stage-2 author prunes these.
    stem_of = {os.path.splitext(os.path.basename(r))[0]: r for r in files}  # for depends_on

    # ----- grouping: _capmap.json wins; uncovered files fall back to one-per-file
    groups, claimed = [], set()
    for entry in _load_capmap(reqs_dir):
        present = [f for f in entry["files"] if f in facts_by_file]
        if present:
            groups.append({"id": entry["id"], "layer": entry.get("layer"), "files": present})
            claimed.update(present)
    for rel in files:
        if rel not in claimed:
            groups.append({"id": _mint_cap_id(rel), "layer": None, "files": [rel]})

    group_id_of_file = {f: g["id"] for g in groups for f in g["files"]}

    cands = []
    for g in groups:
        sigs, docs, imps, loc = [], {}, set(), 0
        my_stems = set()
        for f in g["files"]:
            ff = facts_by_file[f]
            sigs += ["{}: {}".format(f, s) for s in ff["signatures"]]
            for k, v in ff["docstrings"].items():
                docs["{}:{}".format(f, k)] = v
            imps.update(ff["imports"])
            loc += ff.get("loc", 0)
            my_stems.add(os.path.splitext(os.path.basename(f))[0])
        own = set(g["files"])
        deps = sorted({group_id_of_file[stem_of[m]] for m in imps
                       if m in stem_of and stem_of[m] not in own})
        tested_by = sorted(
            r for r in files
            if os.path.basename(r).startswith("test_")
            and os.path.splitext(os.path.basename(r))[0][len("test_"):] in my_stems)
        existing = next((tagged[f] for f in g["files"] if f in tagged), None)
        cands.append({
            "suggested_id": g["id"], "_layer": g["layer"], "files": g["files"],
            "docstrings": docs, "signatures": sigs[:60], "imports": sorted(imps),
            "depends_on": deps, "tested_by": tested_by, "loc": loc,
            "existing_req": existing, "split_candidate": loc > SPLIT_LOC_THRESHOLD,
        })

    fanin = {}
    for c in cands:
        for d in c["depends_on"]:
            fanin[d] = fanin.get(d, 0) + 1
    for c in cands:
        n = fanin.get(c["suggested_id"], 0)
        c["importer_count"] = n
        c["suggested_layer"] = c.pop("_layer") or ("bus" if n >= BUS_FANIN_THRESHOLD else "feature")

    authored = sum(1 for c in cands if c["existing_req"])
    plan = {
        "engine_version": MAP_ENGINE_VERSION,
        # surfaces the unfilled-plan gap so an advisory plan nobody authored cannot
        # masquerade as coverage (with_existing_req = candidates already tagged in code)
        "coverage_summary": {"total_candidates": len(cands), "with_existing_req": authored},
        "lineage_note": ("A generated-from/implements tag records authoring lineage only; it "
                         "does NOT mean the requirement auto-tracks later edits to the source "
                         "file. Re-touch the requirement's Contract+Acceptance when the source's "
                         "behavior changes."),
        "bus": sorted(c["suggested_id"] for c in cands if c["suggested_layer"] == "bus"),
        "candidates": cands,
    }
    text = json.dumps(plan, indent=2, ensure_ascii=False)
    if out and out != "-":
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote {} ({} candidates)".format(out, len(cands)))
    else:
        print(text)
    return 0


# ---------- findings (open verify-intent items) ----------
FINDINGS_SIDECAR = "_findings_triage.json"
_SEV_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3, "": 4}
_SEV_BADGE = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}


def _req_title(body, rid):
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return rid


def collect_findings(reqs):  # implements: REQ-FINDINGS-010
    """Per requirement, the open '## WHAT — Verify intent' bullets minus the
    'None - ...' placeholder. Returns [(rid, title, [item, ...]), ...] for reqs
    that have >=1 real finding, in id order. Deterministic; reads only the md."""
    out = []
    for rid in sorted(reqs):
        body = reqs[rid]["body"]
        items = [b for b in _bullets(body, "verify intent")
                 if b and not b.lstrip("*_ ").lower().startswith("none")]
        if items:
            out.append((rid, _req_title(body, rid), items))
    return out


def _render_findings_raw(groups, total):
    L = ["# Open findings", "",
         "> {} open verify-intent item(s) across {} requirement(s), aggregated from each "
         "requirement's `## WHAT — Verify intent` section by `reqmap.py findings`."
         .format(total, len(groups)),
         ">",
         "> These are open questions raised while reconstructing intent from code - NOT "
         "confirmed bugs. Resolve each by fixing the code or promoting the behavior into a "
         "Contract line. Run the AI triage pass (see SKILL.md) and drop a `{}` beside this "
         "file for a verified, prioritized view.".format(FINDINGS_SIDECAR),
         "", "---", ""]
    if not groups:
        L.append("_No open findings._")
        return "\n".join(L) + "\n", 0, 0
    for rid, title, items in groups:
        L.append("## {} - {}  ({})".format(rid, title, len(items)))
        L.append("")
        for it in items:
            L.append("- {}".format(it))
        L.append("")
    return "\n".join(L) + "\n", 0, 0


def _render_findings_triaged(triage, raw_total):
    items = [it for it in triage.get("items", []) if isinstance(it, dict)]
    buckets = {"REAL_BUG": [], "USER_DECISION": [], "INTENTIONAL": [], "FALSE_POSITIVE": []}
    for it in items:
        # an unknown/typo'd/missing classification folds into USER_DECISION rather
        # than landing in an orphan bucket that no block renders (silent loss). The
        # AI triage sidecar is LLM-authored, so an off-enum value is realistic.
        cls = it.get("classification")
        buckets[cls if cls in buckets else "USER_DECISION"].append(it)
    bugs = sorted(buckets.get("REAL_BUG", []),
                  key=lambda x: _SEV_RANK.get((x.get("severity") or "").lower(), 9))
    n = len(items)
    L = ["# Open findings - triaged", "",
         "> {} finding(s) classified: {} confirmed bug(s), {} product/config decision(s), "
         "{} intentional, {} false-positive. Source: `{}`{}."
         .format(n, len(bugs), len(buckets.get("USER_DECISION", [])),
                 len(buckets.get("INTENTIONAL", [])), len(buckets.get("FALSE_POSITIVE", [])),
                 FINDINGS_SIDECAR,
                 " (generated {})".format(triage["generated_at"]) if triage.get("generated_at") else "")]
    if raw_total and raw_total != n:
        L += [">", "> WARN  {} raw verify-intent item(s) currently in the requirements vs {} "
                   "triaged - re-run the AI triage pass to refresh.".format(raw_total, n)]
    L += ["", "---", ""]

    def block(title, rows, detail):
        L.append("## {} ({})".format(title, len(rows)))
        L.append("")
        for it in rows:
            rid = it.get("req_id", "?")
            sev = (it.get("severity") or "").lower()
            head = "**[{}] `{}`**".format(_SEV_BADGE[sev], rid) if (detail and sev in _SEV_BADGE) \
                else "**`{}`**".format(rid)
            L.append("- {} {}".format(head, it.get("finding", "")))
            if detail and it.get("location"):
                L.append("  - where: `{}`".format(it["location"]))
            if detail and it.get("fix"):
                L.append("  - fix: {}".format(it["fix"]))
        L.append("")

    if bugs:
        block("Confirmed bugs", bugs, True)
    if buckets.get("USER_DECISION"):
        block("Your call - config / product decisions", buckets["USER_DECISION"], True)
    if buckets.get("INTENTIONAL"):
        block("Intentional", buckets["INTENTIONAL"], False)
    if buckets.get("FALSE_POSITIVE"):
        block("False-positive", buckets["FALSE_POSITIVE"], False)
    return "\n".join(L) + "\n", n, len(bugs)


def cmd_findings(reqs, reqs_dir, raw=False):  # implements: REQ-FINDINGS-010
    """Aggregate every requirement's open verify-intent items into
    requirements/_findings.md. If a `_findings_triage.json` sidecar exists (and
    --raw is off), render the verified, classified view from it instead; else the
    raw grouped list. Stdlib-only: the AI triage that produces the sidecar lives
    in the skill, not here (same split as candidates vs AI-authoring)."""
    groups = collect_findings(reqs)
    total = sum(len(items) for _rid, _t, items in groups)

    triage = None
    if not raw:
        sidecar = os.path.join(reqs_dir, FINDINGS_SIDECAR)
        if os.path.exists(sidecar):
            try:
                with open(sidecar, encoding="utf-8") as f:
                    triage = json.load(f)
            except (json.JSONDecodeError, OSError):
                triage = None

    if triage and isinstance(triage.get("items"), list):
        md, n_tri, n_bugs = _render_findings_triaged(triage, total)
    else:
        md, n_tri, n_bugs = _render_findings_raw(groups, total)

    os.makedirs(reqs_dir, exist_ok=True)
    out = os.path.join(reqs_dir, "_findings.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    extra = ", {} triaged, {} confirmed bug(s)".format(n_tri, n_bugs) if triage else ""
    print("{} open finding(s) across {} requirement(s){} -> {}"
          .format(total, len(groups), extra, out))
    return 0


# ---------- map (HTML) ----------
def _build_map_data(reqs, members):  # implements: REQ-MAP-007
    """Assemble the {nodes, edges} registry graph that drives every rendered
    surface (HTML map, Mermaid blocks, and the JSON export). Pure: no IO."""
    used_by = {rid: [] for rid in reqs}
    for rid, r in reqs.items():
        for dep in _as_list(r["meta"].get("depends_on")):
            if dep in used_by:
                used_by[dep].append(rid)
    data = {"nodes": [], "edges": []}
    for rid, r in reqs.items():
        m = r["meta"]
        data["nodes"].append({
            "id": rid, "layer": m.get("layer", "feature"),
            "status": m.get("status", "draft"),
            "area": (m.get("area") or "").strip() or _area_of(rid),
            "title": _title(r["body"]),
            "intent": _first_quote(r["body"]),
            # new emission schema (Contract / Verify-intent / Notes / Current-impl)
            "contract": _bullets(r["body"], "contract"),
            "verify": _bullets(r["body"], "verify"),
            "notes": _bullets(r["body"], "notes"),
            "current_impl": _bullets(r["body"], "current implementation"),
            "acc": _bullets(r["body"], "acceptan"),          # AC bullets if any
            "accept": _section_raw(r["body"], "acceptan"),    # raw acceptance (AC blocks, line breaks kept)
            # legacy schema (Input / Description / Output) — kept so old docs still render
            "input": _section(r["body"], "input"),
            "output": _section(r["body"], "output"),
            "desc": _section(r["body"], "description"),
            "deps": _as_list(m.get("depends_on")),
            "used_by": used_by.get(rid, []),
            "members": [{"role": x[0], "loc": f"{x[1]}:{x[2]}"} for x in members.get(rid, [])],
            "test_exempt": m.get("test_exempt"),
            "milestone": m.get("milestone"),
            "risks": [{"signal": s, "advice": RISK_ADVICE[s]} for s in _risk_signals(
                {"status": m.get("status", "draft"), "members": members.get(rid, []),
                 "verify": _bullets(r["body"], "verify"), "test_exempt": m.get("test_exempt")})],
        })
    for rid, r in reqs.items():
        for dep in _as_list(r["meta"].get("depends_on")):
            data["edges"].append([rid, dep])
    return data


def _parse_todos_from_text(text):
    """Parse TODO.md content → list of {name, lane, milestone, done} dicts. Pure.
    Items before the first ## vX.Y heading are silently ignored (milestone is required)."""
    todos, current_ms = [], None
    for line in text.splitlines():
        ms_m = re.match(r"^##\s+(v\d[\d.]*)\s*$", line.strip())
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
                lane_m = re.search(r"lane:\s*(\w+)", meta)  # lane must be a single word (bus|feature|ops)
                lane = lane_m.group(1) if lane_m else "feature"
            else:
                name, lane = rest.strip(), "feature"
            todos.append({"name": name, "lane": lane, "milestone": current_ms, "done": done})
    return todos


def _parse_todos(root):
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


def cmd_map(reqs, members, reqs_dir, root=".", check=False):  # implements: REQ-MAP-007
    data = _build_map_data(reqs, members)
    data["repo"] = _repo_name(root)
    data["todos"] = _parse_todos(root)

    if check:
        return _map_check(data, reqs_dir)

    md_out   = render_md(data, reqs_dir)
    json_out = render_json(data, reqs_dir)
    html_out = render_html(data, reqs_dir)
    print("wrote {}".format(md_out))
    print("wrote {}".format(json_out))
    if html_out:
        print("wrote {}".format(html_out))
        docs_out = _docs_publish_path(root)
        if docs_out:
            with open(html_out, "rb") as src, open(docs_out, "wb") as dst:
                dst.write(src.read())
            print("wrote {}".format(docs_out))
    print("({} nodes, {} edges)".format(len(data["nodes"]), len(data["edges"])))
    return 0


def cmd_export(reqs, members, reqs_dir, root=".", out=None):  # implements: REQ-MAP-007
    """Emit the registry graph as JSON for an external front-end to consume.
    Same {nodes, edges} shape that drives the map; '-' = stdout, --out PATH, or
    requirements/_map.json by default."""
    data = _build_map_data(reqs, members)
    data["repo"] = _repo_name(root)
    text = _build_json_text(data)
    target = out if out else os.path.join(reqs_dir, "_map.json")
    if target == "-":
        print(text)
        return 0
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote {} ({} nodes, {} edges)".format(target, len(data["nodes"]), len(data["edges"])))
    return 0


def _risk_score(meta):  # implements: REQ-NEXT-013
    """Extract's per-file risk hint (0-3) from frontmatter, or 0 when absent /
    unparseable. Used only to float REVIEW-flagged drafts to the top of a bucket —
    never to gate. Hand-authored requirements have no `risk:` field -> 0."""
    try:
        return int(str(meta.get("risk")).strip())
    except (TypeError, ValueError):
        return 0


def cmd_next(reqs, members, show_all=False, top_n=3):  # implements: REQ-NEXT-013
    """Terminal 'what should I do next': a focused, counted worklist over the same
    `_risk_signals` + `RISK_ADVICE` that drive the Risk tab. Prints a progress
    header, leads with the most-urgent bucket, shows the top few per bucket (the
    extract REVIEW-flagged ones first), and collapses the rest behind --all. Each
    item names the requirement file to open. Read-only, always exit 0."""
    total = len(reqs)
    if total == 0:   # distinguish "nothing set up yet" from "all clean"
        print("No requirements yet. Run `reqmap.py init` to bootstrap from existing "
              "code, or `reqmap.py new AREA-NAME-NNN` to author one.")
        return 0
    confirmed = sum(1 for r in reqs.values() if r["meta"].get("status") == "confirmed")
    tested = sum(1 for rid in reqs if any(role == "tested-by" for role, *_ in members.get(rid, [])))
    drafts = sum(1 for r in reqs.values() if r["meta"].get("status", "draft") == "draft")
    print("{} requirement(s) · {} confirmed · {} tested · {} draft(s)\n".format(
        total, confirmed, tested, drafts))

    dependents = {rid: 0 for rid in reqs}
    for rid, r in reqs.items():
        for dep in _as_list(r["meta"].get("depends_on")):
            if dep in dependents:
                dependents[dep] += 1
    buckets = {}  # signal -> [(rid, risk_score)]
    for rid, r in reqs.items():
        m = r["meta"]
        node = {"status": m.get("status", "draft"), "members": members.get(rid, []),
                "verify": _bullets(r["body"], "verify"), "test_exempt": m.get("test_exempt")}
        for sig in _risk_signals(node):
            buckets.setdefault(sig, []).append((rid, _risk_score(m)))
    # Action buckets, MOST-URGENT FIRST: an unimplemented contract outranks an
    # unreviewed draft. Each bucket is shown and truncated
    # independently, so a high-priority bucket is never hidden below a long low one.
    PLAN = [
        ("unimplemented",     "Orphans (confirmed, no code)"),
        ("untested",          "Needs tests"),
        ("unverified-intent", "Needs intent review"),
        ("unreviewed",        "Drafts to review"),
    ]
    pending = [(sig, label, sorted(buckets[sig], key=lambda x: (-x[1], x[0])))
               for sig, label in PLAN if buckets.get(sig)]
    if not pending:
        print("Nothing pending — every confirmed requirement is implemented, tested and intent-checked.")
        return 0
    total_actions = sum(len(ids) for _, _, ids in pending)
    print("{} item(s) need attention across {} {}:\n".format(
        total_actions, len(pending), "category" if len(pending) == 1 else "categories"))
    for sig, label, ids in pending:
        print("{} ({})".format(label, len(ids)))
        shown = ids if show_all else ids[:top_n]
        for rid, score in shown:
            flag = "  [REVIEW]" if score >= 2 else ""
            print("  {}{}   requirements/{}.md".format(rid, flag, rid))
        if not show_all and len(ids) > top_n:
            print("  ... {} more — run `reqmap.py next --all`".format(len(ids) - top_n))
        print("  -> {}\n".format(RISK_ADVICE[sig]))
    # Granularity advisory: requirements with many ACs covering disjoint behaviors
    AC_SPLIT_THRESHOLD = 5
    oversize = sorted(
        [(rid, len(_bullets(r["body"], "acceptan")))
         for rid, r in reqs.items()
         if len(_bullets(r["body"], "acceptan")) >= AC_SPLIT_THRESHOLD],
        key=lambda x: (-x[1], x[0])
    )
    if oversize:
        print("Granularity ({})".format(len(oversize)))
        for rid, n in oversize:
            print("  {}   ({} ACs) — consider splitting   requirements/{}.md".format(rid, n, rid))
        print(
            "  -> A requirement with >={} acceptance criteria covering disjoint behaviors "
            "is a split candidate. Author two requirements, each with its own contract.\n"
            .format(AC_SPLIT_THRESHOLD)
        )
    return 0


def _strip_line_tag(line):
    """Remove a reqmap membership-tag comment from a source line.
    Finds the comment marker (#, //, <!--) closest to the tag and cuts from
    there to end-of-line, preserving the code before it.
    Lines with no tag are returned unchanged."""
    m = TAG_RE.search(line)
    if m is None:
        return line
    pre = line[:m.start()]
    nl = "\n" if line.endswith("\n") else ""
    cut = -1
    for marker in ("#", "//", "<!--"):
        idx = pre.rfind(marker)
        if idx > cut:
            cut = idx
    if cut >= 0:
        return line[:cut].rstrip() + nl
    return line  # no recognisable comment marker — leave unchanged


def _wipe(reqs_dir, code_root):
    """Hard-reset: delete non-generated requirement files (names not starting
    with `_`) and strip membership tags from every scanned source file so that
    `cmd_extract` can re-draft from a clean slate."""
    deleted = 0
    if os.path.isdir(reqs_dir):
        for fn in os.listdir(reqs_dir):
            if fn.endswith(".md") and not fn.startswith("_"):
                try:
                    os.remove(os.path.join(reqs_dir, fn))
                    deleted += 1
                except OSError:
                    pass
    stripped_files = 0
    ignore = load_ignore(code_root, reqs_dir)
    for dirpath, dirs, files in os.walk(code_root):
        _prune_dirs(dirpath, dirs, reqs_dir)
        for fn in files:
            if not fn.endswith(CODE_EXTS):
                continue
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, code_root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
                continue
            try:
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                new_lines = [_strip_line_tag(l) for l in lines]
                if new_lines != lines:
                    with open(fp, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                    stripped_files += 1
            except OSError:
                continue
    print("wipe: deleted {} requirement file(s), stripped tags from {} source file(s).".format(
        deleted, stripped_files))


def _reqmapignore_seed(code_root, reqs_dir):  # implements: REQ-INIT-012
    """Content for a freshly-seeded `.reqmapignore`. Normally ignores the vendored
    engine at `scripts/reqmap.py` — its `implements:` self-tags would otherwise read
    as dangling refs in a consumer repo. EXCEPTION — a self-hosting repo: when that
    file carries membership tags that resolve to requirements already present, the
    engine IS the managed code and must stay scanned, so the line is omitted (a
    comment explains why) to avoid orphaning those requirements."""
    header = ("# Paths reqmap should not scan (one fnmatch glob per line, # comments ok).\n"
              "# The bundled single-file viewer is a generated artifact, never a member.\n"
              "scripts/_map_viewer.html\n")
    engine = os.path.join(code_root, "scripts", "reqmap.py")
    req_ids = set(load_requirements(reqs_dir))
    if req_ids and os.path.isfile(engine):
        try:
            with open(engine, encoding="utf-8") as f:
                tagged = {m.group(2) for m in TAG_RE.finditer(f.read())}
        except OSError:
            tagged = set()
        if tagged & req_ids:   # self-hosting: the engine's tags point at local reqs
            return (header +
                    "# scripts/reqmap.py is intentionally NOT ignored: this repo hosts its own\n"
                    "# requirements there (its membership tags resolve to local requirements), so\n"
                    "# the engine must stay scanned. Add other vendored/generated paths below.\n")
    return (header +
            "# The engine carries its own `implements:` self-tags; ignore it so the\n"
            "# gate does not flag them as dangling refs.\n"
            "scripts/reqmap.py\n")


def cmd_init(reqs_dir, code_root, wipe=False):  # implements: REQ-INIT-012
    """First-use bootstrap for a fresh repo: create requirements/, seed a minimal
    .reqmapignore (idempotent — never clobbers an existing one), draft requirements
    from existing code, build the lock + map, then print guided next steps.
    Pass wipe=True (--wipe flag) for a hard reset: all non-generated requirement
    files are deleted and membership tags stripped from source before re-extracting."""
    if wipe:
        _wipe(reqs_dir, code_root)
    created = []
    if not os.path.isdir(reqs_dir):
        os.makedirs(reqs_dir, exist_ok=True)
        created.append(os.path.relpath(reqs_dir, code_root).replace(os.sep, "/") + "/")
    ignore = os.path.join(code_root, ".reqmapignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as f:
            f.write(_reqmapignore_seed(code_root, reqs_dir))
        created.append(".reqmapignore")
    print("Bootstrapping draft requirements from existing code...\n")
    reqs = load_requirements(reqs_dir)
    members = scan_members(code_root, reqs_dir)
    cmd_extract(reqs, members, code_root, reqs_dir)
    # extract wrote new files -> reload before locking + mapping
    reqs = load_requirements(reqs_dir)
    members = scan_members(code_root, reqs_dir)
    cmd_check(reqs, members, reqs_dir, update_lock=True)
    cmd_map(reqs, members, reqs_dir, code_root)
    print("\n" + "=" * 60)
    if not reqs:   # nothing to extract — don't masquerade as "all clean"
        print("reqmap initialized, but no requirements were extracted")
        print("(no supported source files found, or all are ignored by .reqmapignore).")
        if created:
            print("created: " + ", ".join(created))
        print("\nNext: author your first requirement with `reqmap.py new AREA-NAME-NNN`.")
        return 0
    print("reqmap initialized — {} requirement(s) tracked.".format(len(reqs)))
    if created:
        print("created: " + ", ".join(created))
    print("\nNext: run `reqmap.py next` — it shows what to do, most important first.")
    print("Then wire the gate: add `python scripts/reqmap.py check` to your pre-commit hook.")
    return 0


def _strip_generated(text):
    """Drop volatile lines so a freshness diff compares content, not the
    environment: the `generated: <timestamp>` frontmatter line (`_map.md`) and the
    `"repo": ...` field (`_map.json`), which is git-derived and differs across
    forks/clones — comparing it would make `map --check` spuriously fail on a fork."""
    return "\n".join(l for l in text.splitlines()
                     if not l.startswith("generated: ")
                     and not l.lstrip().startswith('"repo":'))


def _map_check(data, reqs_dir):  # implements: REQ-MAP-007
    """Freshness gate: regenerate the map in memory and compare to the committed
    files. Stale (committed != freshly-built) -> exit 1 so a code/requirement edit
    that shifts the map can't be committed without regenerating it. A map that was
    never generated (file absent) is NOT stale — consumers who don't track maps pass.
    The `generated:` timestamp is ignored so an unchanged map never trips on time."""
    stale = []
    for name, fresh in (("_map.md", _build_md_text(data)),
                        ("_map.json", _build_json_text(data))):
        path = os.path.join(reqs_dir, name)
        if not os.path.exists(path):
            continue   # nothing committed to be stale against
        on_disk = open(path, encoding="utf-8").read()
        if _strip_generated(on_disk) != _strip_generated(fresh):
            stale.append(name)
    if stale:
        print("FAIL  map is stale: {} — run `reqmap.py map` and commit the result."
              .format(", ".join(stale)))
        return 1
    print("OK  map is fresh.")
    return 0


def _title(body):  # implements: REQ-MAP-007
    """The human title from the requirement's first `# ` heading."""
    for line in body.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    return ""


def _first_quote(body):  # implements: REQ-MAP-007
    for line in body.splitlines():
        if line.strip().startswith(">"):
            return line.strip()[1:].strip()
    return ""


def _section(body, name):  # implements: REQ-MAP-007
    out, grab = [], False
    for line in body.splitlines():
        h = line.strip().lower()
        if h.startswith("## "):
            grab = name in h
            continue
        if grab and line.strip() and not line.strip().startswith("<!--"):
            out.append(line.strip().lstrip("- "))
    return " ".join(out)


def _section_raw(body, name):  # implements: REQ-MAP-007
    """Like _section but preserves line breaks + indentation — used for the
    multi-line Given/When/Then acceptance blocks so they read as written."""
    out, grab = [], False
    for line in body.splitlines():
        h = line.strip().lower()
        if h.startswith("## "):
            grab = name in h
            continue
        if grab and not line.strip().startswith("<!--"):
            out.append(line.rstrip())
    return "\n".join(out).strip()


def _bullets(body, name):  # implements: REQ-MAP-007
    out, grab = [], False
    for line in body.splitlines():
        h = line.strip().lower()
        if h.startswith("## "):
            grab = name in h
            continue
        if grab and line.strip().startswith("-"):
            out.append(line.strip()[1:].strip())
    return out


# ---------- mermaid generators ----------
def _safe_id(rid):
    """Mermaid-safe node ID: replace non-alphanumeric chars with underscores."""
    return re.sub(r"[^A-Za-z0-9]", "_", rid)


def _mlabel(text):
    """Make free text safe inside a quoted Mermaid node label.

    Even inside quotes, Mermaid's parser chokes on backticks, brackets,
    braces, pipes and backslashes; under securityLevel:loose, angle
    brackets would also be rendered as HTML. Neutralize all of them.
    """
    text = text or "—"
    for a, b in (('"', "'"), ("`", "'"), ("[", "("), ("]", ")"),
                 ("{", "("), ("}", ")"), ("|", "/"), ("\\", "/"),
                 ("<", "‹"), (">", "›")):
        text = text.replace(a, b)
    return text


def _node_label(n):
    """Two-line node label: human title big, capability id small below.

    The `<br>`/`<small>` tags are added outside `_mlabel` (which would
    otherwise neutralize the angle brackets); only the title text is
    passed through the sanitizer.
    """
    title = _mlabel(n.get("title") or n["id"])
    return "{}<br><small>{}</small>".format(title, _mlabel(n["id"]))


def _area_of(rid):  # implements: REQ-MAP-007
    """Capability 'area' = the first id segment (BUS-PATHS-001 -> BUS). Used to
    cluster a large System Map into per-area subgraphs so 40+ nodes stay legible."""
    return rid.split("-", 1)[0] or rid


def _node_area(n):  # implements: REQ-MAP-007
    """Grouping key for a node: an explicit `area:` frontmatter field wins (lets a
    repo group e.g. several standalone capabilities under one ANALYSIS box without
    renaming ids); otherwise fall back to the id prefix."""
    return (n.get("area") or "").strip() or _area_of(n["id"])


def _grouped_areas(nodes):  # implements: REQ-MAP-007
    """Order nodes into [(area_label, [node,...]), ...]: multi-node areas first
    (sorted), then one 'misc' bucket of every single-node area. Shared by the
    System / Dependency / Risk diagrams so a 40+ node map stays navigable
    (Miller 7+-2 / C4 levels — split a big diagram by meaningful boundary)."""
    areas = {}
    for n in nodes:
        areas.setdefault(_node_area(n), []).append(n)
    groups = [(a, areas[a]) for a in sorted(areas) if len(areas[a]) > 1]
    singles = [n for a in sorted(areas) if len(areas[a]) == 1 for n in areas[a]]
    if singles:
        groups.append(("misc", sorted(singles, key=lambda n: n["id"])))
    return groups


def _emit_area_subgraphs(lines, nodes, label_fn=None):
    """Append per-area `subgraph` blocks (singletons collapse into 'misc')."""
    label_fn = label_fn or _node_label
    for area, ns in _grouped_areas(nodes):
        lines.append('  subgraph sg_{}["{}"]'.format(_safe_id(area), area))
        for n in ns:
            lines.append('    {}["{}"]'.format(_safe_id(n["id"]), label_fn(n)))
        lines.append("  end")


def _bus_ids(nodes):
    return [n["id"] for n in nodes if n.get("layer") == "bus"]


def _hub_targets(data, bus_ids):
    """Bus nodes + any node with fan-in >= SYSTEM_HUB_FANIN (the hub hairball)."""
    fanin = {}
    for _src, tgt in data["edges"]:
        fanin[tgt] = fanin.get(tgt, 0) + 1
    return set(bus_ids) | {nid for nid, c in fanin.items() if c >= SYSTEM_HUB_FANIN}


def _mermaid_system(data):  # implements: REQ-MAP-007
    # Per-area subgraphs + hide edges into bus/hubs (the hairball); the full graph
    # is in the Dependency Map. Bus nodes keep a thick stroke.
    lines = ["graph LR"]   # left-right fills a wide/landscape area better than top-down
    bus_ids = _bus_ids(data["nodes"])
    _emit_area_subgraphs(lines, data["nodes"])
    hubs = _hub_targets(data, bus_ids)
    for a, b in data["edges"]:
        if b not in hubs:
            lines.append("  {} --> {}".format(_safe_id(a), _safe_id(b)))
    for bid in bus_ids:
        lines.append("  style {} stroke-width:3px".format(_safe_id(bid)))
    return "\n".join(lines)


def _mermaid_deps(data):  # implements: REQ-MAP-007
    # Area-level coupling overview (C4 'container' zoom-out): one box per area, an
    # edge A->B when ANY capability in A depends on one in B. Aggregating the
    # per-capability edges here kills the bus hub hairball; the System Map keeps
    # the per-capability detail and the detail panel lists each node's deps.
    groups = _grouped_areas(data["nodes"])
    if not groups:
        return 'graph LR\n  none["(no requirements)"]'
    label_of, counts, bus_areas = {}, {}, set()
    for label, ns in groups:
        counts[label] = len(ns)
        for n in ns:
            label_of[n["id"]] = label
            if n.get("layer") == "bus":
                bus_areas.add(label)
    edges = set()
    for a, b in data["edges"]:
        la, lb = label_of.get(a), label_of.get(b)
        if la and lb and la != lb:
            edges.add((la, lb))
    lines = ["graph LR"]
    for label in sorted(counts):
        lines.append('  a_{}["{}<br><small>{} caps</small>"]'.format(
            _safe_id(label), _mlabel(label), counts[label]))
    for la, lb in sorted(edges):
        lines.append("  a_{} --> a_{}".format(_safe_id(la), _safe_id(lb)))
    for label in sorted(bus_areas):
        lines.append("  style a_{} stroke-width:3px".format(_safe_id(label)))
    return "\n".join(lines)


def _mermaid_req_to_code(data):  # implements: REQ-MAP-007
    lines = ["graph LR"]
    for n in data["nodes"]:
        rid = n["id"]
        sid = _safe_id(rid)
        lines.append('  {}["{}"]'.format(sid, _node_label(n)))
        if not n["members"]:
            # enforced-but-unlinked is a real gap (red); a baseline/draft not yet
            # tagged is expected, so render it muted grey rather than alarming red
            if n.get("status") in ENFORCED:
                lines.append("  style {} fill:#fee,stroke:#c66".format(sid))
            else:
                lines.append("  style {} fill:#eee,stroke:#bbb,color:#888".format(sid))
            continue
        # group by role+file, compute min/max line numbers
        groups = {}
        for m in n["members"]:
            c = m["loc"].rfind(":")
            f, ln = m["loc"][:c], int(m["loc"][c + 1:])
            k = m["role"] + "|" + f
            if k not in groups:
                groups[k] = {"role": m["role"], "f": f, "min": ln, "max": ln}
            else:
                groups[k]["min"] = min(groups[k]["min"], ln)
                groups[k]["max"] = max(groups[k]["max"], ln)
        for g in groups.values():
            loc = "{}:{}".format(g["f"], g["min"]) if g["min"] == g["max"] \
                  else "{}:{}-{}".format(g["f"], g["min"], g["max"])
            file_sid = "f_" + re.sub(r"[^A-Za-z0-9]", "_", loc)
            lines.append('  {}["{}"]'.format(file_sid, _mlabel(loc)))
            lines.append("  {} -->|{}| {}".format(sid, g["role"], file_sid))
    return "\n".join(lines)


def _member_roles(members):
    """Roles of a node's members, tolerant of both member shapes in play: the raw
    scan tuples (role, file, line) used by cmd_scan/cmd_check and the {role, loc}
    dicts attached to map data nodes."""
    roles = []
    for m in members or []:
        if isinstance(m, dict):
            roles.append(m.get("role"))
        elif isinstance(m, (list, tuple)) and m:
            roles.append(m[0])
    return roles


def _risk_signals(node):
    signals = []
    if node["status"] == "confirmed" and not node["members"]:
        signals.append("unimplemented")
    if node["status"] in ("draft", "baseline"):
        signals.append("unreviewed")
    # implemented-but-untested: has hand-written code linked but no acceptance test.
    # Gated on an implements member so not-yet-built drafts (already 'unreviewed')
    # are not double-flagged. Opt out per requirement with `test_exempt: <reason>`.
    roles = _member_roles(node.get("members"))
    if "implements" in roles and "tested-by" not in roles and not node.get("test_exempt"):
        signals.append("untested")
    # open verify-intent questions reconstructed from code — surface them on the map,
    # not just in the detail panel / _findings.md. Mirror collect_findings: a "None —"
    # placeholder bullet is not an open finding. A *draft* is suppressed here: its
    # intent questions are subsumed by 'unreviewed' (the whole draft is unreviewed),
    # and every auto-extracted draft carries a template verify TODO — flagging both
    # would double-count every draft. Re-surfaces once promoted past draft. This
    # rule lives in the shared signal source so `next` and the Risk tab agree.
    if node["status"] != "draft" and any(
            b and not b.lstrip("*_ ").lower().startswith("none") for b in (node.get("verify") or [])):
        signals.append("unverified-intent")
    return signals


def _mermaid_risk(data):  # implements: REQ-MAP-007
    dep_count = {n["id"]: 0 for n in data["nodes"]}
    for _, b in data["edges"]:
        dep_count[b] = dep_count.get(b, 0) + 1

    risky = [(n, _risk_signals(n)) for n in data["nodes"]]
    risky = [(n, s) for n, s in risky if s]

    lines = ["graph LR"]
    if not risky:
        lines.append('  ok["No risk signals detected"]')
        return "\n".join(lines)

    # Grouped by area, colored by signal, NO edges — Risk answers "which
    # capabilities need attention", not topology (the Dependency Map has edges).
    sigs_by = {n["id"]: s for n, s in risky}
    _emit_area_subgraphs(lines, [n for n, _ in risky],
                         label_fn=lambda n: _node_label(n) + "<br>" + ", ".join(sigs_by[n["id"]]))
    for n, sigs in risky:
        sid = _safe_id(n["id"])
        if "unimplemented" in sigs:
            lines.append("  style {} fill:#fee,stroke:#c00,color:#900".format(sid))
        elif "unreviewed" in sigs:
            lines.append("  style {} fill:#fff3cd,stroke:#a66,color:#630".format(sid))
        else:
            lines.append("  style {} fill:#fff9c4,stroke:#aa0,color:#550".format(sid))
    return "\n".join(lines)


def _add_clicks(diagram, data):
    """Append Mermaid click statements for every requirement node."""
    clicks = "\n".join(
        "  click {} sel_{}".format(_safe_id(n["id"]), _safe_id(n["id"]))
        for n in data["nodes"]
    )
    return diagram + "\n" + clicks


# Per-tab legends (parallel to the 4 diagrams, same order) so each view is
# self-explanatory. HTML uses colored swatches; markdown uses words.
_LEGEND_MD = [
    "Capabilities grouped by area; thick border = bus; arrows = `depends_on`. Edges into the bus/hubs are hidden (the Dependency Map shows area-level coupling).",
    "Each requirement → its code; arrow label = role (`implements` / `tested-by`). Red = confirmed but no code linked (a gap); grey = baseline/draft, not linked yet (expected).",
    "Area-level coupling: one box per area (N caps), arrow A->B = some capability in A depends on one in B. The System Map has the per-capability detail.",
    "Requirements needing attention: red = unimplemented (confirmed, no code); orange = unreviewed (promote after review); yellow = untested (implemented but no tested-by — set `test_exempt` to silence), or unverified-intent (open verify-intent question).",
]


def _build_md_text(data):  # implements: REQ-MAP-007
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    dep_count = {n["id"]: 0 for n in data["nodes"]}
    for _, b in data["edges"]:
        dep_count[b] = dep_count.get(b, 0) + 1

    diagrams = [
        ("System Map",          _mermaid_system(data)),
        ("Requirement-to-Code", _mermaid_req_to_code(data)),
        ("Dependency Map",      _mermaid_deps(data)),
        ("Risk & Unknowns",     _mermaid_risk(data)),
    ]

    lines = [
        "---",
        "generated: {}".format(ts),
        "nodes: {}".format(len(data["nodes"])),
        "edges: {}".format(len(data["edges"])),
        "---",
        "",
        "# Requirement Map",
        "",
    ]
    for i, (title, diagram) in enumerate(diagrams):
        legend = _LEGEND_MD[i] if i < len(_LEGEND_MD) else ""
        lines += ["## {}".format(title), "", "_{}_".format(legend), "", "```mermaid", diagram, "```", ""]

    # risk table — each flagged requirement with its scripted recommendation
    risk_rows = []
    for n in data["nodes"]:
        sigs = _risk_signals(n)
        if sigs:
            rec = " ".join(RISK_ADVICE[s] for s in sigs).replace("|", "/").replace("\n", " ")
            risk_rows.append((n["id"], n["status"],
                              len(n["members"]), dep_count.get(n["id"], 0),
                              ", ".join(sigs), rec))
    if risk_rows:
        lines += [
            "### Risk Table", "",
            "| ID | status | members | dependents | risks | recommendation |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in risk_rows:
            lines.append("| {} | {} | {} | {} | {} | {} |".format(*row))
        lines.append("")

    return "\n".join(lines)


def render_md(data, reqs_dir):  # implements: REQ-MAP-007
    out = os.path.join(reqs_dir, "_map.md")
    os.makedirs(reqs_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_build_md_text(data))
    return out


def _repo_name(root):  # implements: REQ-MAP-007
    """Best-effort `owner/repo` (else the repo directory name) identifying the
    project this map describes, for display in the viewer header. Tries the git
    `remote.origin.url`, then the directory name; returns None when nothing
    resolves. Never raises and never blocks map generation — git may be absent or
    the tree may not be a checkout. Environment-derived (it differs across forks
    and clones), so it is excluded from the `map --check` freshness diff (see
    `_strip_generated`).

    `REQMAP_REPO` env var overrides the derived value: set it to a public-facing
    slug (e.g. on a private dev repo that publishes elsewhere, so the inlined
    `repo` never leaks the dev remote), or to "" to emit no repo at all."""
    override = os.environ.get("REQMAP_REPO")
    if override is not None:
        return override or None
    url = ""
    try:
        r = subprocess.run(["git", "-C", root, "config", "--get", "remote.origin.url"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            url = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        url = ""
    if url:
        slug = url[:-4] if url.endswith(".git") else url
        parts = [p for p in re.split(r"[:/]", slug.rstrip("/")) if p]
        if len(parts) >= 2:
            return "/".join(parts[-2:])
    return os.path.basename(os.path.abspath(root)) or None


def _build_json_text(data):  # implements: REQ-MAP-007
    """The registry graph as a JSON string: {engine_version, repo, nodes, edges}.
    json.dumps neutralizes any hostile id/title/body by construction — there is
    no markup context to break out of — so no extra escaping is needed."""
    payload = {"engine_version": MAP_ENGINE_VERSION, "repo": data.get("repo"),
               "nodes": data["nodes"], "edges": data["edges"],
               "todos": data.get("todos", [])}
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_json(data, reqs_dir):  # implements: REQ-MAP-007
    out = os.path.join(reqs_dir, "_map.json")
    os.makedirs(reqs_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_build_json_text(data))
    return out


# A pre-built, single-file React viewer ships next to this engine as
# `_map_viewer.html`. It carries the marker `<!--REQMAP_DATA-->`; the engine
# swaps that for a <script> assigning this repo's graph to window.__REQMAP_DATA__,
# producing a self-contained `_map.html` that opens by double-click (no server).
VIEWER_TEMPLATE = "_map_viewer.html"
_REQMAP_DATA_MARKER = "<!--REQMAP_DATA-->"


def _docs_publish_path(root):  # implements: REQ-MAP-007
    """Return docs/map.html path when docs/ carries a GitHub Pages signal
    (.nojekyll or index.html present), else None. Opt-in by folder contents —
    repos without the signal are unaffected.

    Uses the git root so repos where reqmap runs from a sub-directory (e.g.
    plugin/) still find docs/ at the project root. Falls back to root itself
    when git is absent or the tree is not a checkout."""
    try:
        git_root = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_root = root
    docs = os.path.join(git_root, "docs")
    if not os.path.isdir(docs):
        return None
    if (os.path.exists(os.path.join(docs, ".nojekyll")) or
            os.path.exists(os.path.join(docs, "index.html"))):
        return os.path.join(docs, "map.html")
    return None


def _viewer_template_path():  # implements: REQ-MAP-007
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), VIEWER_TEMPLATE)


def _inject_viewer(template_text, data):  # implements: REQ-MAP-007
    """Replace the data marker with an inline <script> assigning the graph to
    window.__REQMAP_DATA__. `</` is escaped to `<\\/` so a requirement that
    contains `</script>` cannot break out of the script element."""
    blob = _build_json_text(data).replace("</", "<\\/")
    script = "<script>window.__REQMAP_DATA__=" + blob + ";</script>"
    return template_text.replace(_REQMAP_DATA_MARKER, script, 1)


def render_html(data, reqs_dir):  # implements: REQ-MAP-007
    """Write the self-contained viewer `_map.html` by injecting `data` into the
    vendored template. Returns the path, or None when no template is present
    (the engine still emits _map.md + _map.json — the viewer is optional)."""
    tpl = _viewer_template_path()
    if not os.path.exists(tpl):
        return None
    with open(tpl, encoding="utf-8") as f:
        template_text = f.read()
    out = os.path.join(reqs_dir, "_map.html")
    os.makedirs(reqs_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_inject_viewer(template_text, data))
    return out


def main():
    # The engine prints non-ASCII (em-dashes in WARN/info lines, the JSON plan with
    # ensure_ascii=False). On a legacy Windows codepage (cp437/cp850) a bare `python
    # reqmap.py check` would crash with UnicodeEncodeError and fail the gate on an
    # encoding error, not a real violation. Force UTF-8 so no caller has to remember
    # `-X utf8`. Guarded: reconfigure() is Python 3.7+ and may be absent on exotic streams.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="reqmap")
    ap.add_argument("cmd", choices=["init", "new", "scan", "check", "map", "export", "next", "extract", "candidates", "findings", "promote"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--root", default=".")
    ap.add_argument("--reqs", default=None)
    ap.add_argument("--code", default=None)
    ap.add_argument("--out", default=None, help="candidates: write plan JSON here ('-' or omit = stdout); "
                    "export: write graph JSON here ('-' = stdout, omit = requirements/_map.json)")
    ap.add_argument("--md-glob", action="append", default=None,
                    help="candidates: also discover .md files matching this glob (repeatable; "
                         "comma-separated ok). Off unless given. e.g. --md-glob 'prompts/**' --md-glob 'modes/**'")
    ap.add_argument("--raw", action="store_true",
                    help="findings: ignore the triage sidecar and emit the raw grouped list")
    ap.add_argument("--all", dest="show_all", action="store_true",
                    help="next: list every pending item instead of the top few per bucket")
    ap.add_argument("--update-lock", action="store_true")
    ap.add_argument("--wipe", action="store_true",
                    help="init: hard-reset — delete all non-generated requirements and strip "
                         "membership tags from source files before re-extracting")
    ap.add_argument("--check", dest="check_fresh", action="store_true",
                    help="map: verify the committed _map.* is fresh (exit 1 if stale) instead of writing")
    a = ap.parse_args()
    reqs_dir = a.reqs or os.path.join(a.root, "requirements")
    code_root = a.code or a.root
    # prefer an on-disk templates/requirement.md if present (back-compat), else the
    # built-in REQUIREMENT_TEMPLATE — so no templates/ dir is required.
    here = os.path.dirname(os.path.abspath(__file__))
    tmpl = os.path.join(here, "..", "templates", "requirement.md")
    if not os.path.exists(tmpl):
        tmpl = None

    if a.cmd == "new":
        if not a.arg:
            print("usage: reqmap new AREA-NAME-NNN"); return 2
        return cmd_new(reqs_dir, tmpl, a.arg)
    if a.cmd == "init":
        return cmd_init(reqs_dir, code_root, wipe=a.wipe)

    reqs = load_requirements(reqs_dir)
    members = scan_members(code_root, reqs_dir)
    if a.cmd == "scan":
        cmd_scan(reqs, members); return 0
    if a.cmd == "next":
        return cmd_next(reqs, members, a.show_all)
    if a.cmd == "check":
        rc = cmd_check(reqs, members, reqs_dir, a.update_lock)
        if a.update_lock:
            cmd_map(reqs, members, reqs_dir, code_root)
        return rc
    if a.cmd == "map":
        return cmd_map(reqs, members, reqs_dir, code_root, a.check_fresh)
    if a.cmd == "export":
        return cmd_export(reqs, members, reqs_dir, code_root, a.out)
    if a.cmd == "extract":
        return cmd_extract(reqs, members, code_root, reqs_dir)
    if a.cmd == "candidates":
        md_globs = []
        for g in (a.md_glob or []):
            md_globs += [x.strip() for x in g.split(",") if x.strip()]
        return cmd_candidates(reqs, members, code_root, reqs_dir, a.out, md_globs)
    if a.cmd == "findings":
        return cmd_findings(reqs, reqs_dir, a.raw)
    if a.cmd == "promote":
        if not a.arg:
            print("usage: reqmap promote AREA-NAME-NNN"); return 2
        return cmd_promote(reqs, members, a.arg)


if __name__ == "__main__":
    sys.exit(main() or 0)
