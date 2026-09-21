"""`map` / `export` / `map --check`: assemble the data, write _map.md/_map.json/_map.html, refresh
_findings.md, and tell a committed artifact from a stale one.
"""
import os, re

from . import config as cfg
from .author import _parse_todos
from .design_report import _design_summary
from .findings import _render_findings, cmd_findings
from .git import _git, _git_branch, _repo_name
from .health import _health_record
from .i18n import _attach_translations
from .history import by_month, read_history
from .mapdata import _read_roadmap, _build_map_data
from .mapjson import _build_json_text, render_json
from .mapmd import _build_md_text, render_md
from .scan import scan_ac_verifies
from .site import _extract_region, _render_region, _site_context_from_data, _site_default_target
from .targets import load_targets
from .viewer import render_html


def cmd_map(ws, root=".", check=False):
    # implements: ARCH-MAP-007  # implements: REQ-FINDINGS-856  # implements: REQ-MAP-870
    """Regenerate every derived view of the corpus — `_map.md`, `_map.json` and the
    single-file viewer `_map.html` — or, with `check`, write nothing and return non-zero
    when the committed copies are stale.

    One rendered viewer, and it never leaves `requirements/`. A published copy is built
    where it is published (ADR-0034)."""
    reqs, reqs_dir = ws.reqs, ws.reqs_dir
    data = ws.map_data(root)

    if check:
        return _map_check(data, ws, root)

    md_out   = render_md(data, reqs_dir)
    json_out = render_json(data, reqs_dir)
    html_out = render_html(data, reqs_dir)
    print("wrote {}".format(md_out))
    print("wrote {}".format(json_out))
    if html_out:
        print("wrote {}".format(html_out))
    print("({} nodes, {} edges)".format(len(data["nodes"]), len(data["edges"])))
    if os.path.exists(os.path.join(reqs_dir, "_findings.md")):  # implements: ARCH-FINDINGS-010
        cmd_findings(reqs, reqs_dir)   # a committed report follows the requirements it summarizes
    return 0


def _assemble_map_data(reqs, members, reqs_dir, root=".", ac_cover=None):
    # implements: ARCH-MAP-007  # implements: REQ-MAP-870
    """The graph plus the three fields every rendered surface needs on top of it
    (repo, todos, translations). One assembler, so `map`, `export` and the gate's
    freshness probe cannot build three subtly different documents and disagree about
    which one is stale."""
    if ac_cover is None:
        # `init` and any embedding caller pass none; computing it here (instead of
        # emitting a coverage-less map) keeps every writer of _map.json byte-identical,
        # so `map --check` cannot flag a map as stale merely because a different
        # command wrote it.
        ac_cover = scan_ac_verifies(root, reqs_dir)
    data = _build_map_data(reqs, members, ac_cover)
    data["repo"] = _repo_name(root)
    # The branch the shipped band is shipped ON. Git-derived like `repo`, so it varies
    # between a branch and a fork of the same corpus and is excluded from the freshness
    # diff for the same reason.  implements: REQ-PLANBRANCH-1011
    branch = _git_branch(root)
    if branch:
        data["branch"] = branch
    data["language"] = cfg.LANGUAGE          # implements: REQ-TRANSLATE-996
    data["todos"] = _parse_todos(root)
    # The horizon plan, beside the versioned one. A repo keeps one, the other, or
    # both; the viewer shows the Horizons column set only when this list is non-empty,
    # so a repo with no ROADMAP.md sees exactly what it saw before.
    # implements: REQ-VIEWER-999
    data["roadmap"] = _read_roadmap(root) or []
    # What already shipped, from CHANGELOG.md. Grouped by month here rather than in
    # the viewer, so the CLI and the chart cannot disagree about what a month held.
    # implements: REQ-HISTORY-1003
    data["history"] = by_month(read_history(root))
    # implements: REQ-DESIGN-954  # implements: REQ-DESIGN-976
    _design = _design_summary(root, reqs_dir, with_findings=True)
    if _design is not None:
        data["design"] = _design
    # The same record `next` prints its headline from, so the viewer reads the score
    # rather than defining a second one.  # implements: REQ-HEALTH-968
    data["health"] = _health_record(reqs, members, reqs_dir)
    planning = load_targets(reqs_dir)
    if planning:
        data["planning"] = planning
        data["targets"] = planning  # legacy alias — one release
    _attach_translations(data, reqs, reqs_dir)
    return data


# The top-level `"design"` key of `_map.json`, as `json.dumps(indent=2)` writes it.
# The block closes at the first line that is exactly `  },` or `  }` — every line
# inside it is nested deeper, so the two-space indent is what ends it.
_DESIGN_BLOCK_OPEN = '  "design": {'
_DESIGN_BLOCK_CLOSE = ("  },", "  }")


def _strip_generated(text):  # implements: REQ-DESIGN-991
    """Drop volatile lines so a freshness diff compares content, not the
    environment: the `generated: <timestamp>` frontmatter line (`_map.md`) and the
    `"repo": ...` field (`_map.json`), which is git-derived and differs across
    forks/clones — comparing it would make `map --check` spuriously fail on a fork.

    The advisory design payload goes with them, and for a sharper reason than
    volatility. `_map.json` is ONE freshness-gated artifact carrying three classes of
    data with three different severities — the requirement graph (normative), `health`
    (derived) and `design` (advisory by its own contract, ARCH-DESIGN-061). The
    comparison was all-or-nothing, so anything landing in that document acquired ERROR
    severity by construction, whatever its own contract said: one blank line inserted
    into a file no requirement claims moved a `line:` number in `design.findings`,
    which made the committed map stale, which failed `gate` with zero requirement
    errors. Determinism was the wrong test for what may be gated — a freshness-checked
    payload needs STABILITY UNDER UNRELATED EDITS, and per-line findings have none.

    The data itself stays in the artifact: the viewer renders those rows in its Design
    tab. What changes is that they no longer carry a verdict. The cost, taken with eyes
    open, is that the committed design rows may lag the code until the next `sync`,
    which is the correct trade for advice nobody should be blocked by."""
    out, in_design = [], False
    for l in text.splitlines():
        if in_design:
            in_design = l not in _DESIGN_BLOCK_CLOSE
            continue
        if l == _DESIGN_BLOCK_OPEN:
            in_design = True
            continue
        if (l.startswith("generated: ")
                or l.startswith("engine: ")
                # `_map.md`'s one-line design summary: the same advisory number, and
                # the same reason it must not be able to fail a build.
                or l.startswith("design pass-rate: ")
                or l.lstrip().startswith('"repo":')
                or l.lstrip().startswith('"branch":')
                or l.lstrip().startswith('"engine_version":')):
            continue
        out.append(l)
    return "\n".join(out)


_ENGINE_STAT_RE = re.compile(r'<div class="stat"><b>[^<]*</b><span>engine</span></div>')


def _strip_engine_stat(html):  # implements: ARCH-SITE-026
    """Drop the `engine` stat cell before a site STATS-region freshness diff — it
    embeds the live MAP_ENGINE_VERSION, which changes on every engine change
    independent of requirement content, mirroring the `repo`/`engine_version`
    exclusions `_strip_generated` already applies to `_map.md`/`_map.json` for the
    same reason (a routine engine bump must not flag a committed site page stale)."""
    return _ENGINE_STAT_RE.sub("", html)


_MAP_ARTIFACTS = ("_map.md", "_map.json")


def _absent_tracked_artifacts(reqs_dir, root="."):
    # implements: ARCH-MAP-007  # implements: REQ-MAP-871
    """Map artifacts git TRACKS but that are missing from the working tree.

    `_stale_artifacts` reads an absent file as "nothing committed to be stale
    against", which is right for a consumer who never runs `map` and wrong for a
    file git is tracking: there the absence is a gap, and answering "fresh" would
    be a verdict reached by comparing nothing. Fails open exactly like every other
    git call here — no git, no work tree, a non-zero exit all mean "not tracked",
    so the old convention is what a consumer keeps."""
    absent = []
    for name in _MAP_ARTIFACTS:
        path = os.path.join(reqs_dir, name)
        if os.path.exists(path):
            continue
        # --error-unmatch: git exits non-zero when the path is untracked, and
        # `_git` turns any non-zero into None.
        if _git(["ls-files", "--error-unmatch", "--", os.path.relpath(path, root)],
                cwd=root):
            absent.append(name)
    return absent


def _stale_artifacts(data, ws, root="."):
    # implements: ARCH-MAP-007  # implements: REQ-FINDINGS-856  # implements: REQ-MAP-871
    """Names of the committed generated artifacts that no longer match a fresh
    render of `data` — the whole of the freshness verdict, with no printing and no
    exit code, so `map --check` (which fails) and `gate` (which warns) read the same
    answer instead of implementing it twice. `ws` supplies the requirements directory
    and, when it carries them, the requirements the findings report is rendered from."""
    reqs, reqs_dir = ws.reqs, ws.reqs_dir
    stale = []
    for name, fresh in (("_map.md", _build_md_text(data)),
                        ("_map.json", _build_json_text(data))):
        path = os.path.join(reqs_dir, name)
        if not os.path.exists(path):
            continue   # nothing committed to be stale against
        with open(path, encoding="utf-8") as f:
            on_disk = f.read()
        if _strip_generated(on_disk) != _strip_generated(fresh):
            stale.append(name)
    # Committed findings report: derived from the requirements' verify-intent bullets,
    # so a committed copy goes stale exactly like _map.* does (this repo's sat stale
    # for eleven weeks). Absent = never generated = not stale, same convention.
    findings_out = os.path.join(reqs_dir, "_findings.md")  # implements: ARCH-FINDINGS-010
    if reqs is not None and os.path.exists(findings_out):
        with open(findings_out, encoding="utf-8") as f:
            on_disk = f.read()
        if on_disk != _render_findings(reqs, reqs_dir)[0]:
            stale.append("_findings.md")
    # There is no second copy of the map to check. `requirements/_map.html` is the only
    # rendered viewer the engine writes, it is regenerable from two committed inputs
    # (`_map.json` and the vendored template) and is therefore gitignored — so nothing
    # here can go stale in a commit. A published copy is built where it is published:
    # see the `deploy-map` job.
    # Site presentation page: gate the deterministic STATS region only. NAV embeds
    # the git-derived repo URL (fork-specific) and is excluded, mirroring the
    # `repo`-field exclusion in _strip_generated.  # implements: ARCH-SITE-026
    site_target = _site_default_target(root)
    if site_target and os.path.exists(site_target):
        with open(site_target, encoding="utf-8") as f:
            on_disk = f.read()
        disk_stats = _extract_region(on_disk, "stats")
        if disk_stats is not None:
            ctx = _site_context_from_data(data, repo_url=None, map_ok=False, diagram_rel=None)
            fresh_stats = _render_region("stats", ctx)
            if _strip_engine_stat(disk_stats) != _strip_engine_stat(fresh_stats):
                stale.append(os.path.basename(site_target))
    return stale


def _map_check(data, ws, root="."):
    # implements: ARCH-MAP-007  # implements: REQ-MAP-871
    """Freshness gate: regenerate the map in memory and compare to the committed
    files. Stale (committed != freshly-built) -> exit 1 so a code/requirement edit
    that shifts the map can't be committed without regenerating it. A map that was
    never generated (file absent) is NOT stale — consumers who don't track maps pass.
    The `generated:` timestamp is ignored so an unchanged map never trips on time.
    A file git TRACKS but that is missing fails instead, and a run that compared no
    artifact at all says so rather than reporting freshness it did not measure."""
    reqs_dir = ws.reqs_dir
    absent = _absent_tracked_artifacts(reqs_dir, root)
    if absent:
        print("FAIL  committed map is missing from the working tree: {} — git tracks "
              "it; restore it or run `reqmap.py sync`.".format(", ".join(absent)))
        return 1
    stale = _stale_artifacts(data, ws, root)
    if stale:
        print("FAIL  map is stale: {} — run `reqmap.py sync` and commit the result."
              .format(", ".join(stale)))
        return 1
    if not any(os.path.exists(os.path.join(reqs_dir, n)) for n in _MAP_ARTIFACTS):
        print("OK  no committed map to check.")
        return 0
    print("OK  map is fresh.")
    return 0
