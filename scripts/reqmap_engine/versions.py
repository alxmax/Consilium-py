# implements: ARCH-RELEASE-072
"""Where a repository declares its version, and how the plan, the tags and the CHANGELOG
line up against it.

A version lives in a different file in every ecosystem — `package.json`, `pyproject.toml`,
`Cargo.toml`, a Claude plugin manifest, a bare `VERSION` file — and the plan, the
CHANGELOG and the git tags each name versions of their own. This module reads all of them
in one form, `(major, minor, patch)`, so every comparison the engine makes about versions
is made once."""
import json
import os
import re

from . import config as cfg
from .git import _git
from .history import read_history
from .targets import load_targets

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")
# Probed at the code root and beside the requirements directory, in this order. The
# plugin manifest is last among the JSON files because a repo that is ALSO an npm
# package declares its version in `package.json` first.
VERSION_FILE_CANDIDATES = ("package.json", "pyproject.toml", "Cargo.toml",
                           ".claude-plugin/plugin.json", "VERSION")
# The TOML tables a version is declared under; any other table's `version` key (a
# dependency pin, a tool setting) is not the project's version.
_TOML_TABLES = ("project", "tool.poetry", "package", "workspace.package")
_TOML_TABLE_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
_TOML_VERSION_RE = re.compile(r'^(\s*version\s*=\s*")([^"]*)(".*)$')
_JSON_VERSION_RE = re.compile(r'("version"\s*:\s*")([^"]*)(")')


def semver3(text):  # implements: REQ-PLANSTALE-1013
    """(major, minor, patch) for `vX.Y`, `vX.Y.Z` or `X.Y.Z`, or None for anything else.

    A missing patch is 0, so milestone `v7.19` is the same number as release `v7.19.0`."""
    m = _SEMVER_RE.match(text.strip()) if isinstance(text, str) else None
    return tuple(int(g or 0) for g in m.groups()) if m else None


def tag_form(key):
    """`vX.Y.Z` — the one spelling every message and tag uses."""
    return "v{}.{}.{}".format(*key)


def _toml_version(lines):
    """(line index, version) of the project version in a TOML file's lines, or None."""
    table = None
    for i, line in enumerate(lines):
        head = _TOML_TABLE_RE.match(line)
        if head:
            table = head.group(1).strip()
            continue
        m = _TOML_VERSION_RE.match(line)
        if m and table in _TOML_TABLES:
            return i, m.group(2)
    return None


def read_version_file(path):  # implements: REQ-VERSIONFILES-1014
    """The version string one file declares, or None when it declares none it can read."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    name = os.path.basename(path)
    if name.endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        value = data.get("version") if isinstance(data, dict) else None
    elif name.endswith(".toml"):
        found = _toml_version(text.splitlines())
        value = found[1] if found else None
    else:
        value = text.strip().splitlines()[0].strip() if text.strip() else None
    return value if semver3(value) else None


def write_version_file(path, new):  # implements: REQ-RELEASECMD-1018
    """Rewrite the version one file declares to `new` (no `v`), touching nothing else.

    Returns True when the file changed. The replacement is textual on purpose: a JSON or
    TOML round-trip would reorder keys and reflow every line a human formatted."""
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    name = os.path.basename(path)
    if name.endswith(".json"):
        out, count = _JSON_VERSION_RE.subn(lambda m: m.group(1) + new + m.group(3), text, count=1)
        changed = count == 1
    elif name.endswith(".toml"):
        lines = text.split("\n")
        found = _toml_version(lines)
        if found:
            m = _TOML_VERSION_RE.match(lines[found[0]])
            lines[found[0]] = m.group(1) + new + m.group(3)
        out, changed = "\n".join(lines), bool(found)
    else:
        out, changed = new + "\n", True
    if changed and out != text:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(out)
        return True
    return False


def version_files(reqs_dir, code_root):
    # implements: ARCH-RELEASE-072  # implements: REQ-VERSIONFILES-1014
    """[(path relative to the code root, version)] for every file declaring a version.

    `VERSION_FILES` in `_config.json` names them outright; empty, the engine probes the
    usual names at the code root and beside the requirements directory."""
    root = os.path.abspath(code_root or ".")
    if cfg.VERSION_FILES:
        paths = [os.path.join(root, p) for p in cfg.VERSION_FILES]
    else:
        bases = dict.fromkeys([root, os.path.dirname(os.path.abspath(reqs_dir or "."))])
        paths = [os.path.join(b, c) for b in bases for c in VERSION_FILE_CANDIDATES]
    found = []
    for path in dict.fromkeys(paths):
        value = read_version_file(path) if os.path.isfile(path) else None
        if value:
            found.append((os.path.relpath(path, root).replace(os.sep, "/"), value))
    return found


def newest_tag(code_root):  # implements: REQ-VERSIONALIGN-1016
    """(key, tag) of the highest `v*` semver tag, or None."""
    out = _git(["-C", code_root, "tag", "-l", "v*"], timeout=5) if code_root else None
    tags = [(semver3(t), t) for t in (out or "").split() if semver3(t)]
    return max(tags) if tags else None


def newest_changelog(code_root):  # implements: REQ-VERSIONALIGN-1016
    """(key, version) of the highest dated CHANGELOG release, or None."""
    entries = [(semver3(e["version"]), e["version"]) for e in read_history(code_root)
               if semver3(e["version"])] if code_root else []
    return max(entries) if entries else None


def shipped_baseline(reqs_dir, code_root):
    # implements: ARCH-ROADMAP-038  # implements: REQ-PLANSTALE-1013
    """(key, "vX.Y.Z", source) — the highest version any version file, tag or CHANGELOG
    heading has already committed to — or None when none of them names one.

    All three, because each is ahead of the others at some point in a release: the
    manifest is bumped before a tag exists, the CHANGELOG heading is written with the
    bump, and a tag can exist for a repo that keeps neither."""
    found = [(semver3(v), path) for path, v in version_files(reqs_dir, code_root)]
    tag = newest_tag(code_root)
    if tag:
        found.append((tag[0], "git tag"))
    log = newest_changelog(code_root)
    if log:
        found.append((log[0], "CHANGELOG.md"))
    if not found:
        return None
    key, source = max(found, key=lambda f: f[0])
    return key, tag_form(key), os.path.basename(source)


def _planned_names(reqs_dir):
    """Every milestone key and bar `milestone` the plan names."""
    plan = load_targets(reqs_dir)
    names = set(plan.get("milestones", {}))
    names.update(bar["milestone"] for bar in plan.get("bars", []) if bar.get("milestone"))
    return names


def stale_plan_milestones(reqs_dir, code_root):
    # implements: ARCH-ROADMAP-038  # implements: REQ-PLANSTALE-1013
    """{"baseline", "source", "milestones"} naming every planned milestone at or below
    `shipped_baseline`, or None when there is none. Read-only: never a gate rule."""
    names = _planned_names(reqs_dir)
    base = shipped_baseline(reqs_dir, code_root) if names else None
    if base is None:
        return None
    stale = sorted((n for n in names if semver3(n) and semver3(n) <= base[0]), key=semver3)
    if not stale:
        return None
    return {"baseline": base[1], "source": base[2], "milestones": stale}


def next_planned_version(reqs_dir, code_root):
    # implements: ARCH-RELEASE-072  # implements: REQ-NEXTVERSION-1017
    """The milestone name the next release takes: the lowest planned version above the
    baseline, as the plan spells it, or None when the plan names none.

    The plan is where the number comes from, not a commit trailer or a PR label: the
    milestone a bar was scheduled on is already the author's statement of which release
    the work goes out in (ADR-0040)."""
    names = [n for n in _planned_names(reqs_dir) if semver3(n)]
    base = shipped_baseline(reqs_dir, code_root)
    ahead = [n for n in names if base is None or semver3(n) > base[0]]
    return min(ahead, key=semver3) if ahead else None


def version_alignment_lines(reqs_dir, code_root):
    # implements: ARCH-RELEASE-072  # implements: REQ-VERSIONALIGN-1016
    """Zero or more lines saying where the version files, the CHANGELOG and the tags
    disagree. A tag BELOW the declared version is the normal state between a bump and
    its release, so it is not reported; a tag above it is."""
    files = version_files(reqs_dir, code_root)
    lines = []
    keys = {semver3(v) for _, v in files}
    if len(keys) > 1:
        lines.append("version files disagree: " + ", ".join(
            "{} {}".format(p, v) for p, v in files))
    declared = max(keys) if keys else None
    log = newest_changelog(code_root)
    if declared and log and log[0] != declared:
        lines.append("CHANGELOG.md's newest release is {} while the version files declare "
                     "{} - {}".format(log[1], tag_form(declared),
                                      "write its entry" if log[0] < declared
                                      else "the CHANGELOG is ahead of the files"))
    tag = newest_tag(code_root)
    if declared and tag and tag[0] > declared:
        lines.append("git tag {} is above the declared {} - the version files were not "
                     "bumped past a release".format(tag[1], tag_form(declared)))
    return lines
