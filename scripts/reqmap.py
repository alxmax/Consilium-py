#!/usr/bin/env python3
"""reqmap — requirement manager engine (stdlib only).

Subcommands:
  init              first-use bootstrap: scaffold requirements/ + .reqmapignore, draft
                    requirements from existing code, build the lock + map, print next steps
  scan              list code members (implements/generated-from/... tags) per capability
  gate              the gate: link sync + drift + test-link integrity; exit non-zero on error
                    (pre-commit/CI)
  sync              rescan + advance the drift baseline + regen the map and a committed _findings.md
                    (--accept-drift for an edited contract)
  map               generate requirements/_map.md (Mermaid) + _map.json (graph) [+ _map.html viewer]
  site              inject/refresh engine-owned regions into a presentation page
                    (--attach/--regions/--diagram)
  export            emit the registry graph as requirements/_map.json (for a front-end)
  next              terminal 'what should I do next': counted, actionable risk buckets
  lint [--strict]   readability/structure check on non-draft requirements (warn; --strict fails on
                    errors)
  show <ID>         consolidated dossier for one requirement (contract, deps, members, risk)
  dupes [--threshold T]  flag requirement pairs with overlapping contracts (TF-IDF cosine)
  health [--json]   corpus coherence score + component counts (--json for a CI badge)
  draft             draft requirements from legacy code (status: draft, risk-scored)
  plan              read-only JSON capability-extraction plan (writes no .md)
  findings          aggregate open verify-intent items into requirements/_findings.md
  design            advisory design candidates in the repo's code, any language (four OOP pillars +
                    metrics + standards; never the gate)
  mcp [--allow-writes]  serve the requirements to an AI assistant over MCP (stdio)
  confirm <ID>      flip a reviewed requirement's status to confirmed (one frontmatter edit)
  review [ID]       emit a JSON review plan (intent/contract/acceptance/anchors) for AI-assisted
                    quality review
  translate [--to ro|en]  manual, opt-in: cache a `claude -p` translation of the corpus's
                    majority-language requirements into requirements/_i18n/<locale>.json.
                    Never called by gate/sync/lint/map/the pre-commit hook.
  check             DEPRECATED alias for `gate` (report) / `sync` (with --update-lock); removed in
                    v4.0.0

Layout on disk (relative to repo root, override with --root / --reqs / --code):
  requirements/*.md     the source of truth (markdown + YAML-ish frontmatter)
  <code>/**            scanned for tags like:  # implements: <ID>

The engine itself is the reqmap_engine package beside this file; this module is
the command line (parser, dispatch, the Python floor) and the flat namespace
`import reqmap` has always offered.
"""
import argparse, errno, os, sys

from reqmap_engine import config as cfg
from reqmap_engine.audit import _audit_summary, cmd_audit
from reqmap_engine.candidates import cmd_candidates
from reqmap_engine.clarify import cmd_clarify
from reqmap_engine.cliflags import (
    _add_todo_and_mode_flags, _add_workspace_and_query_flags, _verb_scope
)
from reqmap_engine.commands import COMMANDS, COMMAND_GROUPS
from reqmap_engine.config import apply_config, load_config
from reqmap_engine.design_report import cmd_design
from reqmap_engine.findings import cmd_findings
from reqmap_engine.gate import cmd_check
from reqmap_engine.groups import cmd_decompose_groups
from reqmap_engine.health import cmd_coverage, cmd_health
from reqmap_engine.i18n import cmd_i18n
from reqmap_engine.init import cmd_init
from reqmap_engine.levels import cmd_levels
from reqmap_engine.lint import cmd_lint
from reqmap_engine.mapcmd import cmd_map
from reqmap_engine.mcp import serve as cmd_mcp
from reqmap_engine.registry import _cli_choices, cmd_gen_integration
from reqmap_engine.release import cmd_release
from reqmap_engine.retire import cmd_retire
from reqmap_engine.review import cmd_review
from reqmap_engine.risk import cmd_next
from reqmap_engine.show import cmd_show
from reqmap_engine.search import SEARCH_TOP, cmd_search
from reqmap_engine.similar import _redundant_groups, cmd_similar
from reqmap_engine.site import _site_default_target, cmd_site
from reqmap_engine.workspace import Workspace, _is_source_repo
from reqmap_engine import (
    config, model, parse, sections, acceptance, text, tags, scan,
    orphans, git, locks, commands, registry, author, draft, candidates,
    findings, i18n, lintrules, lint, decompose, groups, similar, clarify,
    risk, show, design, design_python, design_brace, design_report, mapmd,
    mapjson, viewer, site, mapdata, health, mapcmd, workspace, rules,
    gate, audit, init, retire, levels, review, targets, plandrift, history,
    pyramid, cliflags, site_template, docclaims, versions, release, mcp, mcpconfig, search,
)
# Declared support floor, deliberately equal to the OLDEST version CI actually runs
# (the `tests` matrix in .github/workflows/ci.yml). The code itself needs only 3.7
# (subprocess.run's capture_output/text, stream.reconfigure), but 3.7 and 3.8 are not
# installable on current GitHub runners, so promising them would be a claim nothing
# proves - the failure mode this project exists to prevent. Move this only together
# with the matrix that tests it.
MIN_PYTHON = (3, 9)  # implements: REQ-PYFLOOR-902
def _python_floor_error(version_info=None):
    # implements: ARCH-PYFLOOR-040  # implements: REQ-PYFLOOR-902
    """Return a message when the interpreter is below MIN_PYTHON, else None.

    A pure predicate rather than an inline exit, so a test can pin the floor on any
    interpreter - a test process cannot spawn a 3.8 to watch the real thing happen.
    Note what this cannot catch: the module uses f-strings, so an interpreter below
    3.6 fails at COMPILE time and never reaches this check. 3.6-3.8 - the range a
    real user plausibly still has - get the readable message. ASCII only: a legacy
    Windows codepage is exactly where an old interpreter turns up.
    """
    major, minor = tuple(version_info or sys.version_info)[:2]
    if (major, minor) >= MIN_PYTHON:
        return None
    return ("reqmap needs Python %d.%d or newer (running %d.%d). The engine is stdlib-only, "
            "so a newer interpreter is the entire fix - no install, no dependencies: re-run "
            "with one, e.g. `python%d.%d scripts/reqmap.py ...`."
            % (MIN_PYTHON[0], MIN_PYTHON[1], major, minor, MIN_PYTHON[0], MIN_PYTHON[1]))

def _build_parser():  # implements: ARCH-CMDREGISTRY-033
    """The argument parser for every verb and flag, built from the command
    registry; flag registration lives in the `_add_*_flags` helpers below."""
    # The epilog is rendered from the registry: a hand-written one listed twelve verbs
    # argparse rejected (`draft`, `confirm`, `translate`, ...) for a whole release.
    epilog = []
    for group, names in COMMAND_GROUPS:
        epilog.append(group.capitalize() + ":")
        for name in names:
            spec = COMMANDS[name]; verb = name + (" " + spec["arg"] if spec.get("arg") else "")
            flags = " ".join(p["flag"] for p in spec["params"])
            epilog.append("  {:<22} {}".format(verb, spec["summary"].split(". ")[0]))
            if flags: epilog.append("  {:<22} flags: {}".format("", flags))
    ap = argparse.ArgumentParser(
        prog="reqmap", formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(epilog))
    ap.add_argument("cmd", choices=_cli_choices()); ap.add_argument("arg", nargs="?")
    _add_workspace_and_query_flags(ap)
    _add_todo_and_mode_flags(ap)
    return ap

def _dispatch_gate(a, ws, code_root, reqs_dir):
    """`gate`: the verdict, or the report its --audit/--risk/--show mode asks for.
    `ask` goes to `_dispatch_ask`. Returns the exit code; only the bare verdict can make it
    non-zero."""
    if a.cmd == "ask":
        return _dispatch_ask(a, ws)
    if a.mode_audit:
        return cmd_audit(ws, strict=a.strict, as_json=a.as_json)
    if a.mode_risk:
        if a.as_badge:
            return cmd_health(ws, False, True)
        if a.as_json:
            return cmd_health(ws, True, False)
        if a.untagged:
            return cmd_coverage(ws, False)
        cmd_health(ws, False, False, headline_only=True)
        return cmd_next(ws, a.show_all)
    if a.mode_show is not None:
        if not a.mode_show:
            print("usage: reqmap gate --show <ID>"); return 2
        # Workspace.load (the non-cache path) already produced level_cover in the
        # same walk; ws.levels() only re-walks when --cache forced the
        # scan_members-only path (cache is scan_members-only, see scan_all's docstring).
        return cmd_show(ws, a.mode_show, ws.levels(), as_json=a.as_json)
    # The whole verdict, in the order every hook and CI already ran it: link sync +
    # drift + test-link, then requirement readability, then map freshness. They were
    # three commands because they were written on three days, not because a caller
    # ever wanted one without the others (the published Action defaults both extras
    # to on). Report-only throughout: never touches the lock, never writes a map.
    rc = cmd_check(ws, False, a.strict, a.as_json, getattr(a, "since", None))
    if a.as_json:
        return rc                      # one machine-readable document, not three
    if not a.no_lint:
        rc = cmd_lint(ws, strict=True) or rc
    if not a.no_map_check:
        rc = cmd_map(ws, code_root, True) or rc
    # Last, because a reader takes the last line as the verdict. `cmd_check` prints its
    # own counts where it runs, which is FIRST — a hundred lines above the end on this
    # corpus — so the line a run finished on was the readability sub-report's count. An
    # auditor read that as the gate under-reporting itself by 32. The sub-reports now say
    # which check they belong to, and this line is the verdict: nothing may print below it.
    print("\ngate: {} — link sync + drift + test links{}{}.".format(
        "PASS" if rc == 0 else "FAIL",
        "" if a.no_lint else ", readability",
        "" if a.no_map_check else ", map freshness"))
    return rc
def _dispatch_ask(a, ws):  # implements: REQ-CMDREGISTRY-1031
    """`ask`: the read-only questions that are not the verdict (ADR-0044). Returns the
    question's exit code; with no mode, a usage line and 2."""
    reqs, members, reqs_dir = ws.reqs, ws.members, ws.reqs_dir
    if a.mode_i18n:
        return cmd_i18n(ws, as_json=a.as_json)
    if a.mode_search is not None:
        if not a.mode_search:
            print("usage: reqmap ask --search \"<query>\"   [--top N]"); return 2
        return cmd_search(reqs, a.mode_search, a.top if a.top is not None else SEARCH_TOP,
                          reqs_dir=reqs_dir, as_json=a.as_json)
    if a.mode_review is not None:
        # No id plans the whole corpus: what cmd_review and the review skill always said.
        return cmd_review(reqs, a.mode_review or None)
    if a.mode_dupes:
        return cmd_similar(reqs, a.threshold if a.threshold is not None else cfg.SIMILAR_THRESHOLD,
                           members, top=a.top, as_json=a.as_json)
    if a.mode_design:
        return cmd_design(ws.code_root, reqs_dir, as_json=a.as_json)
    print("usage: reqmap ask --search QUERY | --dupes | --design | --review [ID] | --i18n")
    return 2
def _dispatch_sync(a, ws, code_root, reqs_dir):
    """`sync` and its write modes. Returns the exit code."""
    reqs, members = ws.reqs, ws.members   # the commands that take only part of it
    if a.mode_retire is not None:
        if not a.mode_retire:
            print("usage: reqmap sync --retire AREA-NAME-NNN [ID ...]"); return 2
        return cmd_retire(ws, a.mode_retire, delete=a.delete,
                          do_apply=a.do_apply, force=a.force, as_json=a.as_json)
    if a.mode_release is not None:
        return cmd_release(ws, code_root, reqs_dir, version=a.mode_release,
                           apply_it=a.do_apply, as_json=a.as_json)
    # Before the gate, not after: the generated integration artifacts are derived
    # from the command registry, and RM028 reports them stale. Regenerating them
    # downstream of a check that fails ON them can never converge.
    if _is_source_repo(code_root):
        cmd_gen_integration(reqs_dir, code_root)
    # rescan + regenerate map + advance the drift baseline (guarded). Members were
    # already scanned above; cmd_check rewrites the lock unless confirmed drift is
    # detected without --accept-drift, then map regenerates only on success.
    # `--accept-drift` alone yields True, with a reason the string, absent False;
    # cmd_check reads all three.
    rc = cmd_check(ws, True, strict=a.strict,
                   accept_drift=getattr(a, "accept_drift", False))
    if rc == 0:
        cmd_map(ws, code_root)
        # Everything derived is rebuilt in one place: there is no state of the world
        # in which regenerating the map but not the findings digest, the presentation
        # page or (in this repository) the generated integration artifacts is what the
        # caller wanted. Each step below is a no-op when its target does not exist.
        # `map` already refreshes an existing digest; this is the create path,
        # kept opt-in so a consumer repo never gains a file it did not ask for.
        if a.findings and not os.path.exists(os.path.join(reqs_dir, "_findings.md")):
            cmd_findings(reqs, reqs_dir, raw=False)
        _site_page = a.attach or _site_default_target(code_root)
        if _site_page and os.path.isfile(_site_page):
            cmd_site(ws, code_root, attach=_site_page,
                     regions=["nav", "stats"], diagram=None, detect=False)
        # Deliberately here and not in cmd_check: `gate` runs on every commit via the
        # hook, and a corpus-shape advisory there is noise on work that is already
        # correct. `sync` is the moment the corpus was just rewritten, which is when
        # a newly-minted duplicate appears.  # implements: REQ-REDUNDANCY-058
        _dups = _redundant_groups(reqs)
        if _dups:
            print("info  {} group(s) of requirements share an identical contract "
                  "({} could be folded away) — run `reqmap.py gate --risk` to see them"
                  .format(len(_dups), sum(len(g) - 1 for g in _dups)))
        # Everything the engine can discover, named in one place at the moment the
        # corpus was just rewritten. `sync` regenerates what is derived; until now it
        # said nothing about what is WRONG beyond the gate, so a repo could sync for
        # months without ever meeting `dupes`, `design`, the exemption list or the
        # fact that its corpus is flat.  # implements: REQ-AUDIT-973
        _audit_summary(reqs, members, reqs_dir, code_root)
    else:
        # The lock may still have advanced above (it is written unless CONFIRMED
        # drift was refused), while the map was not regenerated — the two then
        # disagree, `gate` passes locally, and CI fails on `map --check`. Say so
        # where it happens instead of leaving the reader to infer it.
        print("sync: gate failed — the map was NOT regenerated. Fix the errors above "
              "and re-run `sync`, or run `map` explicitly.", file=sys.stderr)
    return rc
def main():
    """Parse the command line, load the workspace once, and dispatch to the verb.
    Returns the process exit code."""
    # Refuse an interpreter below the declared floor before anything else runs, so the
    # user gets one readable line instead of an AttributeError from some stdlib call
    # that did not exist yet.
    floor = _python_floor_error()  # implements: REQ-PYFLOOR-902
    if floor:
        print(floor)
        return 2
    # The engine prints non-ASCII (em-dashes in WARN/info lines, the JSON plan with
    # ensure_ascii=False). On a legacy Windows codepage (cp437/cp850) a bare `python
    # reqmap.py gate` would crash with UnicodeEncodeError and fail the gate on an
    # encoding error, not a real violation. Force UTF-8 so no caller has to remember
    # `-X utf8`. Guarded: reconfigure() is Python 3.7+ and may be absent on exotic streams.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    ap = _build_parser()
    a = ap.parse_args()
    if _verb_scope(ap, a):              # a foreign flag is refused before any scan runs
        return 2
    reqs_dir = a.reqs or os.path.join(a.root, "requirements")
    code_root = a.code or a.root
    apply_config(load_config(reqs_dir))   # implements: ARCH-CONFIG-060
    # prefer an on-disk templates/requirement.md if present (back-compat), else the
    # built-in REQUIREMENT_TEMPLATE — so no templates/ dir is required.
    here = os.path.dirname(os.path.abspath(__file__))
    tmpl = os.path.join(here, "..", "templates", "requirement.md")
    if not os.path.exists(tmpl):
        tmpl = None

    if a.cmd == "mcp":               # a long-running server: no workspace of its own
        return cmd_mcp(a)
    if a.cmd == "init" and not a.plan:
        return cmd_init(reqs_dir, code_root, wipe=a.wipe, no_site=a.no_site)

    # One walk for the commands that need coverage too (gate/sync); the rest only ever
    # asked for members. --cache stays on scan_members, the only scanner that implements
    # it - see scan_all's docstring for why it is not duplicated there.
    ws = Workspace.load(reqs_dir, code_root, cache=a.cache)
    if a.cmd == "init":            # init --plan: the read-only extraction plan
        md_globs = []
        for g in (a.md_glob or []):
            md_globs += [x.strip() for x in g.split(",") if x.strip()]
        return cmd_candidates(ws, a.out, md_globs)
    if a.cmd in ("gate", "ask"):
        return _dispatch_gate(a, ws, code_root, reqs_dir)
    if a.cmd == "sync":
        return _dispatch_sync(a, ws, code_root, reqs_dir)
    if a.cmd == "clarify":
        if a.decompose:
            if a.arg and a.arg not in ws.reqs:
                print("no requirement with id {}".format(a.arg)); return 1
            # Two seams, tried in order. A requirement whose Description carries bold
            # group labels is split along THOSE — the author already drew the lines, and
            # the children are the code rung a tagged corpus otherwise cannot reach. Only
            # a requirement with no groups falls through to the older clause-level path,
            # which scaffolds one draft per over-long clause and never edits the parent.
            rc = cmd_decompose_groups(ws, only=a.arg or None, apply_it=a.do_apply,
                                      code_root=code_root)
            if rc is not None:
                return rc
            return cmd_lint(ws, strict=False, decompose=True, only=a.arg or None)
        if a.levels:
            # the retrofit ADR-0030 leaves out: `init` mints the rungs only for the
            # drafts it extracts, so a corpus that was already tagged has no path to
            # the axis. Human-invoked on purpose, and never on `sync`.
            return cmd_levels(ws, apply_it=a.do_apply, only=a.arg or None)
        return cmd_clarify(ws.reqs, a.arg, as_json=a.as_json)

def _pipe_closed():  # implements: ARCH-PIPE-046
    """The reader (`| head`) stopped listening: point stdout at the null device so the
    interpreter's shutdown flush cannot raise a second time, and exit clean."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except Exception:
        pass
    # Measured on Windows: after the dup2 the interpreter's shutdown flush of the
    # original stdout buffer STILL raised EINVAL and the process exited 120 with
    # "Exception ignored in: <_io.TextIOWrapper ...>" on stderr — the fix above made
    # the traceback quieter, not the exit clean. Leave without that flush.
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(0)

def _run_cli(entry=None):  # implements: ARCH-PIPE-046  # implements: REQ-PIPE-893
    """Run `main` (or `entry`), turning a closed output pipe into a quiet exit 0.
    Windows has no SIGPIPE: a reader that closes early surfaces as OSError EINVAL (22),
    on POSIX as BrokenPipeError/EPIPE — `dupes | head` on a 1,141-requirement corpus
    died with a traceback on the primary supported OS. Every other OSError propagates."""
    try:
        return (entry or main)() or 0
    except BrokenPipeError:
        return _pipe_closed()
    except OSError as e:
        if e.errno in (errno.EPIPE, errno.EINVAL):
            return _pipe_closed()
        raise


# ---- one flat namespace -------------------------------------------------------
# The engine is the reqmap_engine package, but `import reqmap` still answers for
# every engine name (`reqmap._acc_blocks`, `reqmap.LINT_AC_MAX`, ...): the
# regression suite and any embedder read the engine through this module, and a
# config override applied at startup is read live through the same lookup.
_ENGINE_MODULES = (
    config, model, parse, sections, acceptance, text, tags, scan,
    orphans, git, locks, commands, registry, author, draft, candidates,
    findings, i18n, lintrules, lint, decompose, groups, similar, clarify,
    risk, show, design, design_python, design_brace, design_report, mapmd,
    mapjson, viewer, site, mapdata, health, mapcmd, workspace, rules,
    gate, audit, init, retire, levels, pyramid, review, targets, plandrift, history,
    cliflags, site_template, docclaims, versions, release, mcp, mcpconfig, search,
)


def __getattr__(name):
    for _m in _ENGINE_MODULES:
        if hasattr(_m, name):
            return getattr(_m, name)
    raise AttributeError("module 'reqmap' has no attribute {!r}".format(name))



if __name__ == "__main__":
    sys.exit(_run_cli())
