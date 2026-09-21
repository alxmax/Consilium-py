"""Every `--flag` the CLI accepts, registered on a parser argparse already built.

Lifted out of `reqmap.py` because it is not the command line's shape, only its
surface: 117 lines of mechanical `add_argument` calls that push the CLI module past
the 500-line bar `ask --design` holds every engine file to. `reqmap.py` keeps what
reads as the command line — the floor check, the parser assembly, dispatch — and the
registry that names these flags already lives here, in `commands.py`.
"""
import sys

from .commands import COMMANDS
from .similar import _threshold_arg


def _add_workspace_and_query_flags(ap):
    # implements: ARCH-CMDREGISTRY-033
    ap.add_argument("--root", default=".")
    ap.add_argument("--reqs", default=None)
    ap.add_argument("--code", default=None)
    ap.add_argument("--out", default=None,
                    help="candidates: write plan JSON here ('-' or omit = stdout); export: write "
                         "graph JSON here ('-' = stdout, omit = requirements/_map.json)")
    ap.add_argument("--md-glob", action="append", default=None,
                    help="candidates: also discover .md files matching this glob (repeatable; "
                         "comma-separated ok). Off unless given. e.g. --md-glob 'prompts/**' "
                         "--md-glob 'modes/**'")
    ap.add_argument("--all", dest="show_all", action="store_true",
                    help="next: list every pending item instead of the top few per bucket")
    ap.add_argument("--strict", action="store_true",
                    help="lint: exit non-zero on errors. check: promote drift and test-link "
                         "integrity from warn to error.")
    ap.add_argument("--no-lint", dest="no_lint", action="store_true",
                    help="gate: skip the requirement readability check")
    ap.add_argument("--no-map-check", dest="no_map_check", action="store_true",
                    help="gate: skip the committed-map freshness check")
    ap.add_argument("--findings", action="store_true",
                    help="sync: also create requirements/_findings.md the first time (it is "
                         "refreshed automatically once it exists)")
    ap.add_argument("--untagged", action="store_true",
                    help="next: list the source files carrying no implements: tag")
    ap.add_argument("--plan", action="store_true",
                    help="draft: emit the JSON extraction plan and write no requirement")
    ap.add_argument("--delete", action="store_true",
                    help="retire: remove the requirement outright instead of deprecating it")
    ap.add_argument("--force", action="store_true",
                    help="retire: proceed despite dependents, or on a dirty working tree")
    ap.add_argument("--decompose", action="store_true",
                    help="clarify --decompose: scaffold one draft requirement per statement-size "
                         "finding (opt-in; the only mode that writes files)")
    ap.add_argument("--levels", action="store_true",
                    help="clarify --levels: propose a V-model rung for every requirement that "
                         "declares none (read-only; --apply writes them)")
    ap.add_argument("--threshold", type=_threshold_arg, default=None,
                    help="ask --dupes: cosine cutoff in (0,1] for reporting a pair (default 0.35)")
    ap.add_argument("--top", type=int, default=None,
                    help="ask --search: max ranked matches to show (default 5); ask --dupes: max "
                         "pairs to print (default all)")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="gate (bare, --risk, --audit, --show), ask (--search, --dupes, --design, "
                         "--i18n), sync --retire/--release, clarify: emit JSON")
    ap.add_argument("--badge", dest="as_badge", action="store_true",
                    help="health: emit Shields.io endpoint JSON (schemaVersion, label, message, "
                         "color)")
    ap.add_argument("--accept-drift",
                    dest="accept_drift", nargs="?", const=True, default=False, metavar="REASON",
                    help="sync: advance the drift baseline even when a confirmed/implemented "
                         "contract changed (otherwise sync refuses and exits non-zero)")
    ap.add_argument("--since", metavar="REF",
                    help="gate: scope to requirements whose member files changed since REF "
                         "(hypothesis: highest-frequency changes; falls back to full scan on git "
                         "error)")
    ap.add_argument("--wipe", action="store_true",
                    help="init: hard-reset — delete all non-generated requirements and strip "
                         "membership tags from source files before re-extracting")

def _add_todo_and_mode_flags(ap):
    # implements: ARCH-CMDREGISTRY-033
    ap.add_argument("--cache", action="store_true",
                    help="opt-in: reuse a per-file scan cache (requirements/_scancache.json) so "
                         "unchanged files skip re-parsing. Off by default; results are identical "
                         "with or without it.")
    ap.add_argument("--attach", default=None,
                    help="sync: target HTML to inject the site's engine-owned regions into "
                         "(scaffolds it if absent)")
    ap.add_argument("--no-site", dest="no_site", action="store_true",
                    help="init: skip the final site step")
    ap.add_argument("--allow-writes", dest="allow_writes", action="store_true",
                    help="mcp: also offer the tools that write (sync, release)")
    ap.add_argument("--apply", dest="do_apply", action="store_true",
                    help="sync --retire / --release: actually write the change (without it, "
                         "the run is a dry report)")
    # Mode flags: the read-only queries that used to be their own verbs. The work
    # they do is unchanged — only the entry point moved: `gate` keeps the verdict and
    # the reports on it, `ask` every other question (ADR-0044), `sync` every write.
    ap.add_argument("--audit", dest="mode_audit", action="store_true",
                    help="gate: also print risk, duplicate contracts, design signals and tag "
                         "coverage")
    ap.add_argument("--risk", dest="mode_risk", action="store_true",
                    help="gate: print the corpus risk snapshot and what to do next")
    ap.add_argument("--i18n", dest="mode_i18n", action="store_true",
                    help="ask: list the translations the configured LANGUAGE expects and does not "
                         "have")
    ap.add_argument("--show", dest="mode_show", metavar="ID", nargs="?", default=None, const="",
                    help="gate: print one requirement's dossier")
    ap.add_argument("--search",
                    dest="mode_search", metavar="QUERY", nargs="?", default=None, const="",
                    help="ask: rank requirements by lexical relevance to a query")
    ap.add_argument("--review", dest="mode_review", metavar="ID", nargs="?", default=None, const="",
                    help="ask: emit the review plan for one requirement, or the whole corpus")
    ap.add_argument("--dupes", dest="mode_dupes", action="store_true",
                    help="ask: rank requirement pairs whose contracts overlap")
    ap.add_argument("--design", dest="mode_design", action="store_true",
                    help="ask: print the advisory design review of the code")
    ap.add_argument("--retire", dest="mode_retire", metavar="ID", nargs="*", default=None,
                    help="sync: take one or more requirements out of service; prints the blast "
                         "radius first")
    ap.add_argument("--release", dest="mode_release", metavar="VERSION", nargs="?", const=True,
                    default=None,
                    help="sync: cut the next planned version (or the vX.Y.Z named); prints "
                         "the plan first")


# The flags every verb accepts: where the workspace is, and whether to cache the scan.
WORKSPACE_FLAGS = ("--root", "--reqs", "--code", "--cache")


def _owners(flag):
    """The verbs whose registry entry gives them `flag`."""
    return [v for v in COMMANDS if any(p["flag"] == flag for p in COMMANDS[v]["params"])]


def _foreign_flags(ap, a, verb):  # implements: REQ-CMDREGISTRY-1031
    """The flags given on this call that `verb` does not own. The parser is flat, so the
    registry is what says which verb a flag belongs to."""
    owned = set(WORKSPACE_FLAGS) | {p["flag"] for p in COMMANDS[verb]["params"]}
    out = []
    for action in ap._actions:
        longs = [o for o in action.option_strings if o.startswith("--")]
        if not longs or longs[0] in owned or action.dest == "help":
            continue
        if getattr(a, action.dest, action.default) != action.default:
            out.append(longs[0])
    return out


def _verb_scope(ap, a):  # implements: REQ-CMDREGISTRY-1031
    """Refuse a flag the registry gives another verb, on every verb, naming the verb that
    owns it. `gate`'s old spellings of `ask`'s questions are refused the same way since
    v8.0.0 (ADR-0044). Returns 2 when the call is refused, else 0."""
    foreign = _foreign_flags(ap, a, a.cmd)
    if not foreign:
        return 0
    hints = ["{} is `{}`'s".format(f, "`/`".join(_owners(f)) or "no verb")
             for f in foreign]
    print("reqmap {0}: not a `{0}` flag: {1}. `{0}` takes {2}".format(
        a.cmd, "; ".join(hints),
        " ".join(p["flag"] for p in COMMANDS[a.cmd]["params"]) or "no flags"),
        file=sys.stderr)
    return 2
