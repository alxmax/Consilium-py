"""`init`: scaffold, seed .reqmapignore, wipe."""
import json
import os

from .draft import cmd_extract
from .mapdata import _roadmap_signals
from .gate import cmd_check
from .mapcmd import cmd_map
from .mcpconfig import seed_mcp_files
from .release import seed_release_files
from .versions import version_files
from .parse import load_requirements
from .scan import _walk_code, scan_members
from .site import _site_default_target, _site_pages_bootstrap, cmd_site
from .tags import TAG_RE, _findall_tags, _scan_file_tags
from .workspace import Workspace


def _strip_line_tag(line):
    """Remove a reqmap membership-tag comment from a source line.

    Strips only when a comment marker (#, //, <!--) *directly opens* the tag —
    i.e. nothing but whitespace sits between the marker and the tag id. A line
    that merely mentions a tag in prose or a heading (e.g. a doc line
    `# How implements: AREA-NAME-001 tags work`, or
    `<!-- note --> ... implements: AREA-NAME-001 is required <!-- end -->`) is
    left unchanged, so `init --wipe` never truncates documentation that
    documents the tagging convention. A multi-char heading/banner marker
    (`## `, `//// `) is removed whole rather than leaving a dangling bare `#`.
    Lines with no tag are returned unchanged."""
    m = TAG_RE.search(line)
    if m is None:
        return line
    pre = line[:m.start()]
    nl = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    cut = -1
    for marker in ("#", "//", "<!--", "/*", "--", ";"):
        idx = pre.rfind(marker)
        if marker == "--" and idx >= 2 and pre[idx - 2:idx] == "<!":
            continue   # the tail of an HTML comment opener, handled as `<!--` above
        # the marker opens the tag's comment only when the gap between the
        # marker token and the tag id is whitespace-only; otherwise it is an
        # unrelated heading / inline comment and must not anchor the cut
        if idx > cut and pre[idx + len(marker):].strip() == "":
            cut = idx
    if cut < 0:
        return line  # no comment marker directly opens the tag — leave unchanged
    # walk back over a contiguous run of the same marker char (`## `, `//// `)
    # so the whole heading/banner marker is removed, not just its last char
    while cut > 0 and pre[cut - 1] == pre[cut]:
        cut -= 1
    return line[:cut].rstrip() + nl


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
    for fp, _rel in _walk_code(code_root, reqs_dir):
        try:
            # surrogateescape (read AND write) round-trips any non-UTF-8 bytes
            # verbatim, so stripping a tag never silently corrupts e.g. a
            # Latin-1 comment elsewhere in the file (errors="ignore" dropped them).
            # newline="" on both ends: read/write the file's own line endings verbatim
            # so stripping ONE tag comment never silently normalizes the WHOLE file to
            # the host platform's os.linesep (e.g. flips an LF-committed shell hook to
            # CRLF on Windows, which breaks /bin/sh on the CR).
            with open(fp, encoding="utf-8", errors="surrogateescape", newline="") as f:
                lines = f.readlines()
            # Only the lines the SCANNER reads as tags. Cutting every TAG_RE hit
            # sliced a tag-shaped string literal in a test fixture in half
            # (`"# implements: X\n..."` -> `"`, a SyntaxError) and blanked the fenced
            # examples in every README that documents the tagging convention.
            hits = {ln for _role, _cid, ln in (_scan_file_tags(fp, lines) or [])}
            # A line that was NOTHING but a tag comment leaves no blank line behind.
            # `_strip_line_tag` blanks it (its own tested contract, and the right answer
            # for `def f():  # implements: X`), but `init` now writes whole-line tags
            # itself, so a wipe that left one blank per file would make init --wipe --> init
            # grow the source a line at a time. implements: REQ-INITTAG-1008
            new_lines = []
            for i, l in enumerate(lines, 1):
                if i not in hits:
                    new_lines.append(l)
                    continue
                stripped = _strip_line_tag(l)
                if stripped.strip():
                    new_lines.append(stripped)
            if new_lines != lines:
                with open(fp, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                    f.writelines(new_lines)
                stripped_files += 1
        except OSError:
            continue
    print("wipe: deleted {} requirement file(s), stripped tags from {} source file(s).".format(
        deleted, stripped_files))



ROADMAP_SEED = """# Roadmap

The product plan. Not a log: versions live in CHANGELOG.md and in the git tag.

Format: `- [ ] text | req: ID` under Now or Next. A `Later` item needs `unpark:` —
a condition that would bring it back, because parked with no way back is parked
forever, and `gate --audit` says so.

Lines indented under an item are its note. They are carried into the map and shown
when its bar is selected in the Plan, so this is where the reasoning goes.

Reserved headings: Now, Next, Later, Not now. Items under any other `## ` heading
are skipped.

## Now

## Next

## Later

## Not now
"""


def _planning_seed():
    # implements: ARCH-INIT-012  # implements: REQ-PLANHORIZON-1010
    """Content for a freshly-seeded `_planning.json`.

    Deliberately carries NO `until`: the horizon is a live rule (`default_horizon`),
    so a calendar written today still reaches three months out a year from now. A date
    frozen here would be a plan that quietly stops — the failure this file already had
    once, when it planned a version that had shipped.

    The lanes are a starting vocabulary, not a schema: rename them freely, the chart
    reads whatever is here."""
    return json.dumps({
        "_comment": [
            "Bars drawn on the Plan chart. `lanes` are yours to rename.",
            "Name a milestone in full, vX.Y.Z (like v1.4.0), the form tags and CHANGELOG use.",
            "While nothing here has a date, the calendar runs to the end of this year,",
            "or three months out, whichever is later - the engine computes it. Once bars",
            "or dues exist it ends at the last of them; add `until` to `cadence` to pin it.",
        ],
        "lanes": ["Feature", "Fix", "Release"],
        "cadence": {"every": "week", "on": "friday", "lane": "Release"},
        "milestones": {},
        "bars": [],
    }, ensure_ascii=False, indent=2) + "\n"


def _reqmapignore_seed(code_root, reqs_dir):
    # implements: ARCH-INIT-012  # implements: REQ-INIT-860
    """Content for a freshly-seeded `.reqmapignore`. Normally ignores the vendored
    engine at `scripts/reqmap.py` — its `implements:` self-tags would otherwise read
    as dangling refs in a consumer repo. EXCEPTION — a self-hosting repo: when that
    file carries membership tags that resolve to requirements already present, the
    engine IS the managed code and must stay scanned, so the line is omitted (a
    comment explains why) to avoid orphaning those requirements."""
    header = ("# Paths reqmap should not scan (one fnmatch glob per line, # comments ok).\n"
              "# The bundled single-file viewer is a generated artifact, never a member.\n"
              "scripts/_map_viewer.html\n"
              "# Isolated agent worktrees. Each holds a FULL second copy of this repo, so a\n"
              "# local scan counts every member twice and reads the copies' tags as dangling\n"
              "# refs — errors that do not exist in the code, in files CI never checks out.\n"
              "# Both spellings: Claude Code creates `.claude/worktrees/`, older\n"
              "# parallel-session tooling `.worktrees/`.\n"
              ".worktrees/**\n"
              ".claude/worktrees/**\n"
              "# The plan, not a capability. `_read_roadmap` opens it by name, so the\n"
              "# scanner never needs to: left scanned, the extractor reads it as untagged\n"
              "# prose and drafts a requirement whose subject is the plan file itself.\n"
              "ROADMAP.md\n"
              "# The release history and the release workflow `init` seeds: read by name,\n"
              "# or run by CI, and neither is a capability to draft.\n"
              "CHANGELOG.md\n"
              ".github/workflows/reqmap-release.yml\n")
    engine = os.path.join(code_root, "scripts", "reqmap.py")
    req_ids = set(load_requirements(reqs_dir))
    if req_ids and os.path.isfile(engine):
        try:
            with open(engine, encoding="utf-8") as f:
                # expand comma-lists like scan_members
                tagged = {cap for (_role, cap) in _findall_tags(f.read())}
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
            "scripts/reqmap.py\n"
            "scripts/reqmap_engine/**\n")


def _seed_plan_files(code_root, reqs_dir, created):
    # implements: ARCH-INIT-012  # implements: REQ-PLANHORIZON-1010
    """Seed the plan and what a release needs, appending each file made to `created`.
    Returns the notes the release seeding raised.

    A plan file a repo does not have is a plan nobody writes, and a release needs a
    CHANGELOG to write into and, on GitHub, the workflow that tags it (ARCH-RELEASE-072).
    Every file is seeded once and never clobbered, so `init` stays idempotent."""
    roadmap = os.path.join(code_root, "ROADMAP.md")
    if not os.path.exists(roadmap):
        with open(roadmap, "w", encoding="utf-8") as f:
            f.write(ROADMAP_SEED)
        created.append("ROADMAP.md")
    planning = os.path.join(reqs_dir, "_planning.json")
    if not os.path.exists(planning):
        with open(planning, "w", encoding="utf-8") as f:
            f.write(_planning_seed())
        created.append(os.path.relpath(planning, code_root).replace(os.sep, "/"))
    seeded, notes = seed_release_files(code_root, reqs_dir)
    created.extend(seeded)
    seeded, mcp_notes = seed_mcp_files(code_root, reqs_dir)  # implements: REQ-MCPSEED-1029
    created.extend(seeded)
    return notes + mcp_notes


def _print_release_setup(reqs_dir, code_root, notes):
    # implements: ARCH-INIT-012  # implements: REQ-VERSIONFILES-1014
    """Say where this repo's version is read from, so a release is never set up blind."""
    found = version_files(reqs_dir, code_root)
    if found:
        print("version: read from " + ", ".join("{} ({})".format(p, v) for p, v in found))
    else:
        print("version: no version file found - releases follow git tags only. Name the "
              "file in _config.json as VERSION_FILES if it lives elsewhere.")
    for note in notes:
        print("note: " + note)
    # implements: REQ-ROADMAP-983
    # Said once, here: a TODO.md with no version heading gives the roadmap chart nothing,
    # and silence there reads the same as "all is well".
    roadmap = _roadmap_signals(code_root)
    if roadmap and not roadmap["newest_milestone"] and roadmap["unversioned_headings"]:
        print("roadmap: TODO.md has {} heading(s) and none starts with a version (`## vX.Y`), "
              "so the roadmap chart stays empty".format(len(roadmap["unversioned_headings"])))


def cmd_init(reqs_dir, code_root, wipe=False, no_site=False):
    # implements: ARCH-INIT-012  # implements: REQ-INIT-861
    """First-use bootstrap for a fresh repo: create requirements/, seed a minimal
    .reqmapignore (idempotent — never clobbers an existing one), draft requirements
    from existing code, build the lock + map, then print guided next steps.
    Pass wipe=True (--wipe flag) for a hard reset: all non-generated requirement
    files are deleted and membership tags stripped from source before re-extracting."""
    created = []
    if not os.path.isdir(reqs_dir):
        os.makedirs(reqs_dir, exist_ok=True)
        created.append(os.path.relpath(reqs_dir, code_root).replace(os.sep, "/") + "/")
    # Seed the ignore file BEFORE a wipe reads it: on a fresh consumer the wipe
    # otherwise ran with no patterns and stripped the vendored engine's own tags.
    ignore = os.path.join(code_root, ".reqmapignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as f:
            f.write(_reqmapignore_seed(code_root, reqs_dir))
        created.append(".reqmapignore")
    release_notes = _seed_plan_files(code_root, reqs_dir, created)
    if wipe:
        _wipe(reqs_dir, code_root)
    print("Bootstrapping draft requirements from existing code...\n")
    cmd_extract(Workspace(load_requirements(reqs_dir),
                          scan_members(code_root, reqs_dir), reqs_dir, code_root))
    # extract wrote new files -> reload before locking + mapping
    ws = Workspace(load_requirements(reqs_dir),
                   scan_members(code_root, reqs_dir), reqs_dir, code_root)
    reqs = ws.reqs
    cmd_check(ws, update_lock=True)
    cmd_map(ws, code_root)
    # implements: ARCH-SITE-026 — best-effort project site. Never aborts init.
    if not no_site:
        target = _site_default_target(code_root)
        if target:
            try:
                _site_pages_bootstrap(os.path.dirname(target))   # .nojekyll + index.html redirect
                cmd_site(ws, code_root, attach=target, regions=["nav", "stats"])
            except Exception as e:   # site is decorative; a failure must not break bootstrap
                print("note: site step skipped ({}).".format(e))
        else:
            print("note: no docs/ folder — run the requirement-manager skill to set up "
                  "a project site.")
    print("\n" + "=" * 60)
    if not reqs:   # nothing to extract — don't masquerade as "all clean"
        print("reqmap initialized, but no requirements were extracted")
        print("(no supported source files found, or all are ignored by .reqmapignore).")
        if created:
            print("created: " + ", ".join(created))
        print("\nNext: write your first requirement as requirements/AREA-NAME-NNN.md.")
        return 0
    print("reqmap initialized — {} requirement(s) tracked.".format(len(reqs)))
    if created:
        print("created: " + ", ".join(created))
    _print_release_setup(reqs_dir, code_root, release_notes)
    print("\nNext: run `reqmap.py gate --risk` — it shows what to do, most important first.")
    print("Then wire the gate: add `python scripts/reqmap.py gate` to your pre-commit hook.")
    # `init` drafts the three rungs only for code it EXTRACTED, and it extracts only
    # untagged files (ARCH-EXTRACT-008). On a repo that already carries membership tags
    # it therefore proposes nothing and says so — which reads as "nothing to do" when the
    # truth is "this run could not reach your existing requirements". `clarify --levels`
    # is the path that can (ADR-0031); naming it here is the difference between a gap a
    # reader can close and one they never learn about.
    _unlevelled = sum(1 for r in reqs.values() if not r["meta"].get("level"))
    if _unlevelled:
        print("\nNote: {} of {} requirement(s) declare no `level:`. `init` proposes rungs "
              "only for code it extracted, and it skips files that already carry a tag, so "
              "it cannot reach those.".format(_unlevelled, len(reqs)))
        print("Run `reqmap.py clarify --levels` to see a proposed rung for each "
              "(read-only; --apply writes them, marked `level_source: auto`).")
    return 0
