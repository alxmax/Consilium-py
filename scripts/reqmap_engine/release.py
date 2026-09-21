# implements: ARCH-RELEASE-072
"""`sync --release`: cut the next planned version from the plan, in one step.

The number comes from the plan: the lowest planned milestone above what has already been
declared (ADR-0040). The run writes nothing without `--apply`; with it, the version files
are bumped, the CHANGELOG gains the dated entry listing the work planned on that version,
and the plan drops the milestone and its bars — a plan that keeps a shipped version is a
plan describing the past. Tagging is left to CI, which reads the declared version back."""
import datetime
import json
import os

from .gate import run_gate_rules
from .git import _git
from .history import changelog_style, entry_body, parse_changelog, release_heading
from .mapdata import _read_roadmap
from .plandrift import items_for_bars
from .targets import PLANNING_FILES
from .versions import (
    newest_tag, next_planned_version, semver3, shipped_baseline, tag_form, version_files,
    write_version_file
)
from .workspace import GateContext

CHANGELOG = "CHANGELOG.md"


def _changelog_path(code_root):
    """The CHANGELOG `read_history` reads — the code root's, else its parent's — or the
    code root's path when there is none yet."""
    root = os.path.abspath(code_root)
    for base in dict.fromkeys([root, os.path.dirname(root)]):
        if os.path.isfile(os.path.join(base, CHANGELOG)):
            return os.path.join(base, CHANGELOG)
    return os.path.join(root, CHANGELOG)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _planning_path(reqs_dir):
    for name in PLANNING_FILES:
        path = os.path.join(reqs_dir, name)
        if os.path.isfile(path):
            return path
    return None


def _released_work(reqs_dir, key):  # implements: REQ-PLANADVANCE-1020
    """(raw plan, milestone name, label, [bar]) for the planned version equal to `key`."""
    path = _planning_path(reqs_dir)
    try:
        raw = json.loads(_read(path)) if path else {}
    except ValueError:
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    milestones = raw.get("milestones") if isinstance(raw.get("milestones"), dict) else {}
    name = next((n for n in milestones if semver3(n) == key), None)
    entry = milestones.get(name) if name else None
    label = entry.get("label") if isinstance(entry, dict) else None
    bars = [b for b in raw.get("bars", []) if isinstance(b, dict)
            and semver3(b.get("milestone")) == key]
    return raw, name, label, bars


def _changelog_entry(style, version, date, label, bars):  # implements: REQ-RELEASECMD-1018
    """The dated entry for one release: a bold headline, then one bullet per planned bar."""
    lines = [release_heading(style, version, date), "",
             "**{}.**".format((label or "Release " + version).rstrip("."))]
    if bars:
        lines.append("")
        for bar in bars:
            req = bar.get("req")
            lines.append("- {}{}".format(bar.get("title", ""), " ({})".format(req) if req else ""))
    return "\n".join(lines) + "\n"


def _insert_entry(text, entry):  # implements: REQ-RELEASECMD-1018
    """`text` with `entry` placed newest-first: directly under `## [Unreleased]` when the
    file keeps one, so what was collected there becomes this release's notes; otherwise
    above the first `## ` heading; otherwise at the end."""
    lines = text.split("\n") if text else ["# Changelog", ""]
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## [unreleased]"):
            return "\n".join(lines[:i + 1] + ["", entry.rstrip("\n")] + lines[i + 1:])
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[:i] + [entry.rstrip("\n"), ""] + lines[i:])
    return "\n".join(lines).rstrip("\n") + "\n\n" + entry


def _declared(reqs_dir, code_root):  # implements: REQ-RELEASEWORKFLOW-1019
    """What CI releases: the declared version, whether its tag exists, and its notes."""
    keys = [semver3(v) for _, v in version_files(reqs_dir, code_root)]
    tag = newest_tag(code_root)
    key = max(keys) if keys else (tag[0] if tag else None)
    if key is None:
        return {"declared": None, "tag_exists": False, "notes": ""}
    name = tag_form(key)
    exists = bool((_git(["-C", code_root, "tag", "-l", name], timeout=5) or "").strip())
    return {"declared": name, "tag_exists": exists,
            "notes": entry_body(_read(_changelog_path(code_root)), name)}


def release_plan(ws, code_root, reqs_dir, version=True):
    # implements: ARCH-RELEASE-072  # implements: REQ-RELEASECMD-1018
    # implements: REQ-NEXTVERSION-1017
    """Everything `--apply` would do, as data. Writes nothing."""
    plan = dict(_declared(reqs_dir, code_root))
    base = shipped_baseline(reqs_dir, code_root)
    plan["baseline"] = base[1] if base else None
    wanted = version if isinstance(version, str) else next_planned_version(reqs_dir, code_root)
    key = semver3(wanted) if wanted else None
    problems = []
    if key is None:
        problems.append("no planned milestone above {} - plan one in _planning.json, or name "
                        "the version: sync --release vX.Y.Z".format(plan["baseline"] or "v0.0.0"))
    elif base and key <= base[0]:
        problems.append("{} is not above {} ({})".format(tag_form(key), base[1], base[2]))
    errs, _ = run_gate_rules(GateContext(ws, full_members=ws.members, update_lock=False),
                             strict=False)
    if errs:
        problems.append("gate reports {} error(s) - fix them before a release".format(len(errs)))
    plan.update({"target": tag_form(key) if key else None, "problems": problems,
                 "date": datetime.date.today().isoformat()})
    if key is None:
        return plan
    _, name, label, bars = _released_work(reqs_dir, key)
    text = _read(_changelog_path(code_root))
    plan["files"] = [{"path": p, "from": v, "to": tag_form(key).lstrip("v")}
                     for p, v in version_files(reqs_dir, code_root)]
    plan["changelog"] = _changelog_entry(changelog_style(text), tag_form(key), plan["date"],
                                         label, bars)
    plan["plan"] = {"milestone": name, "bars": [b.get("title") for b in bars]}
    # Suggested, never written: ticking an item is the author's statement that it is done.
    plan["roadmap"] = [it["name"] for it in items_for_bars(_read_roadmap(code_root), bars)]
    return plan


def apply_release(plan, code_root, reqs_dir):
    # implements: REQ-RELEASECMD-1018  # implements: REQ-PLANADVANCE-1020
    """Carry out a problem-free plan: bump the files, write the entry, advance the plan."""
    root = os.path.abspath(code_root)
    for change in plan["files"]:
        write_version_file(os.path.join(root, change["path"]), change["to"])
    path = _changelog_path(code_root)
    text = _read(path)
    if not any(semver3(e["version"]) == semver3(plan["target"]) for e in parse_changelog(text)):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(_insert_entry(text, plan["changelog"]))
    raw, name, _, bars = _released_work(reqs_dir, semver3(plan["target"]))
    if name or bars:
        if name:
            del raw["milestones"][name]
        raw["bars"] = [b for b in raw.get("bars", []) if b not in bars]
        with open(_planning_path(reqs_dir), "w", encoding="utf-8") as f:
            f.write(json.dumps(raw, ensure_ascii=False, indent=2) + "\n")


def _print_plan(plan, applied):
    print("release {} (declared {}, baseline {})".format(
        plan["target"] or "-", plan["declared"] or "-", plan["baseline"] or "-"))
    for problem in plan["problems"]:
        print("  BLOCKED  " + problem)
    for change in plan.get("files", []):
        print("  bump     {}: {} -> {}".format(change["path"], change["from"], change["to"]))
    if plan.get("changelog"):
        print("  write    CHANGELOG.md entry:")
        for line in plan["changelog"].rstrip("\n").split("\n"):
            print("             " + line)
    advanced = plan.get("plan") or {}
    if advanced.get("milestone") or advanced.get("bars"):
        print("  advance  _planning.json: drop {} and {} bar(s)".format(
            advanced.get("milestone") or "-", len(advanced.get("bars", []))))
    for name in plan.get("roadmap", []):
        print("  tick     ROADMAP.md (by hand, if it is done): " + name)
    print("applied." if applied else
          "dry run - nothing written; add --apply to release. Tagging is CI's job.")


def cmd_release(ws, code_root, reqs_dir, version=True, apply_it=False, as_json=False):
    # implements: ARCH-RELEASE-072  # implements: REQ-RELEASECMD-1018
    """Print the release plan; with `apply_it`, carry it out. Exit 2 when blocked."""
    plan = release_plan(ws, code_root, reqs_dir, version)
    applied = bool(apply_it and not plan["problems"])
    if applied:
        apply_release(plan, code_root, reqs_dir)
    plan["applied"] = applied
    if as_json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    else:
        _print_plan(plan, applied)
    return 2 if apply_it and plan["problems"] else 0


# ---------- what `init` seeds so a new repo can release ----------
CHANGELOG_SEED = """# Changelog

Every release, newest first. A release is a heading `## [X.Y.Z] - YYYY-MM-DD` whose first
line is a bold sentence saying what shipped; the Plan chart reads these as its history.
`reqmap.py sync --release --apply` writes the heading for the next planned version, with the
work planned on it, and anything collected under `Unreleased` becomes that release's notes.

## [Unreleased]
"""

WORKFLOW_PATH = ".github/workflows/reqmap-release.yml"

_WORKFLOW = """# Seeded by `reqmap.py init` (REQ-RELEASEWORKFLOW-1019); edit freely, `init` never
# overwrites it. On every push to {branch} it releases the version this repository
# declares, once: when tag vX.Y.Z does not exist yet it is created, with a GitHub release
# whose notes are that version's CHANGELOG entry. Choosing and bumping the version is
# `reqmap.py sync --release --apply`, run before the push.
name: release
on:
  push:
    branches: [{branch}]
permissions:
  contents: write
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"
      - name: Release the declared version once
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          python {engine} sync --release --json --reqs {reqs} --code . > release.json
          python - <<'PY' > release.env
          import json
          d = json.load(open("release.json"))
          open("notes.md", "w").write(d["notes"] or d["declared"] or "")
          print("version=" + (d["declared"] or ""))
          print("exists=" + str(d["tag_exists"]).lower())
          PY
          . ./release.env
          if [ -z "$version" ] || [ "$exists" = "true" ]; then
            echo "nothing to release"; exit 0
          fi
          gh release create "$version" --target "$GITHUB_SHA" --title "$version" \
            --notes-file notes.md
"""


def _default_branch(code_root):
    """The remote's default branch, or `main` when git cannot say."""
    ref = (_git(["-C", code_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                timeout=3) or "").strip()
    return ref.split("/", 1)[1] if "/" in ref else "main"


def release_workflow(code_root, reqs_dir):  # implements: REQ-RELEASEWORKFLOW-1019
    """The workflow text for this repo, or None when the engine does not live inside it —
    a workflow cannot run an engine the checkout does not contain."""
    root = os.path.abspath(code_root)
    engine = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "reqmap.py")
    try:
        rel_engine = os.path.relpath(engine, root)
        rel_reqs = os.path.relpath(os.path.abspath(reqs_dir), root)
    except ValueError:
        # Windows: a path on another drive has no relative form, and it is certainly not
        # inside the checkout.
        return None
    if rel_engine.startswith(".."):
        return None
    return _WORKFLOW.format(branch=_default_branch(code_root),
                            engine=rel_engine.replace(os.sep, "/"),
                            reqs=rel_reqs.replace(os.sep, "/"))


def _uses_github(code_root):
    return (os.path.isdir(os.path.join(code_root, ".github"))
            or "github.com" in (_git(["-C", code_root, "config", "--get", "remote.origin.url"],
                                     timeout=3) or ""))


def seed_release_files(code_root, reqs_dir):
    # implements: ARCH-RELEASE-072  # implements: REQ-CHANGELOGFORMS-1015
    # implements: REQ-RELEASEWORKFLOW-1019
    """Create what a repo needs to release and never overwrite it: a CHANGELOG when there
    is none, and the release workflow when the repo is on GitHub. Returns (created, notes)."""
    created, notes = [], []
    changelog = os.path.join(code_root, CHANGELOG)
    if not os.path.exists(_changelog_path(code_root)):
        with open(changelog, "w", encoding="utf-8") as f:
            f.write(CHANGELOG_SEED)
        created.append(CHANGELOG)
    workflow = os.path.join(code_root, *WORKFLOW_PATH.split("/"))
    if _uses_github(code_root) and not os.path.exists(workflow):
        text = release_workflow(code_root, reqs_dir)
        if text is None:
            notes.append("no release workflow: the engine is not inside this repository, so "
                         "CI could not run it. Vendor it under scripts/ and re-run init.")
        else:
            os.makedirs(os.path.dirname(workflow), exist_ok=True)
            with open(workflow, "w", encoding="utf-8") as f:
                f.write(text)
            created.append(WORKFLOW_PATH)
    return created, notes
