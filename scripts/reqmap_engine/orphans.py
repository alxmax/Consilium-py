"""Files the map cannot account for: members git does not track, tags in files the scan never
reads, doc bundles and code with no tag at all.
"""
import fnmatch, os

from . import config as cfg
from .git import _git
from .scan import _walk_code, _walk_files, load_ignore, read_source_lines, read_source_text
from .tags import PROSE_EXTS, TAG_RE, _is_code_file, _scan_file_tags, classify_prose


def untracked_members(code_root, members):
    # implements: ARCH-TRACKED-042  # implements: REQ-TRACKED-936
    """Sorted rel-paths of member files git does not track, or None when unknowable.

    The invariant: a committed generated artifact must depend only on TRACKED files.
    Break it and the map records members a fresh checkout cannot produce, so the
    committed _map.json is unreproducible - `map --check` then fails in CI for a file
    that is not in the repo, which reads as a mystery rather than a mistake. That
    happened twice in one day here: a subagent worktree (a full second copy of the
    tree, gitignored) and a Consilium report carrying a real `generated-from:` tag.
    Both were invisible locally, because the local scan can see what CI never will.

    One `git ls-files` call, not one `check-ignore` per path: being untracked is the
    property that matters, and it also catches a file that is merely uncommitted
    rather than ignored. Returns None - the fail-open signal, matching
    `_since_changed_files` - when git is absent or `code_root` is not a work tree.
    """
    tracked_out = _git(["-c", "core.quotepath=off", "ls-files", "-z"],
                       cwd=code_root, timeout=30)
    if tracked_out is None:
        return None
    tracked = {os.path.normcase(p.replace("/", os.sep))
               for p in tracked_out.split("\0") if p}
    seen = set()
    for hits in members.values():
        for _role, fp, _ln in hits:
            seen.add(fp)
    return sorted(fp for fp in seen
                  if os.path.normcase(fp.replace("/", os.sep)) not in tracked)



# Never worth opening for a tag: a tag can only live in text a human wrote.
_BINARY_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tgz", ".7z",
                ".woff", ".woff2", ".ttf", ".otf", ".eot", ".docx", ".xlsx", ".pptx", ".exe",
                ".dll", ".so", ".dylib", ".bin", ".jar", ".class", ".pyc", ".lock", ".mp3", ".mp4")
_UNSCANNED_MAX_BYTES = 1_000_000


def tagged_unscanned_files(code_root, reqs_dir=None):
    # implements: ARCH-UNSCANNEDTAG-045  # implements: REQ-UNSCANNEDTAG-939
    """Sorted rel-paths of TRACKED files the scan never reads (extension/basename
    outside CODE_EXTS/BASENAME_CODE_FILES) that nonetheless carry a membership tag,
    or None when git cannot answer. A tag in such a file is silently not a member:
    the first consumer run had a tagged Caddyfile and a tagged Prisma schema, both
    invisible. Bounded by `git ls-files` like untracked_members, skips `.reqmapignore`
    matches, the SSOT dir, `_`-prefixed and binary/oversized files; a non-UTF-8 file
    is skipped, never reported."""
    tracked_out = _git(["-c", "core.quotepath=off", "ls-files", "-z"],
                       cwd=code_root, timeout=30)
    if tracked_out is None:
        return None
    ignore = load_ignore(code_root, reqs_dir)
    reqs_rel = None
    if reqs_dir:
        try:
            reqs_rel = os.path.relpath(reqs_dir, code_root).replace(os.sep, "/") + "/"
        except ValueError:
            reqs_rel = None
    out = []
    for rel in tracked_out.split("\0"):
        if not rel:
            continue
        fn = os.path.basename(rel)
        # git's and the engine's own dotfiles quote tags as examples (this repo's
        # .reqmapignore explains an illustration id); any other dotfile — .env was the
        # infra run's case — is as tag-worthy as a Makefile and is reported
        if (_is_code_file(fn) or fn.startswith(("_", ".git", ".reqmap"))
                or fn.lower().endswith(_BINARY_EXTS)):
            continue
        if reqs_rel and not reqs_rel.startswith("../") and rel.startswith(reqs_rel):
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
            continue
        fp = os.path.join(code_root, rel.replace("/", os.sep))
        try:
            if os.path.getsize(fp) > _UNSCANNED_MAX_BYTES:
                continue
            with open(fp, encoding="utf-8") as f:
                text = f.read()
        except (OSError, ValueError):
            continue
        if TAG_RE.search(text):
            out.append(rel)
    return sorted(out)


def untagged_doc_bundles(code_root, members, reqs_dir=None):
    # implements: ARCH-DOCBUNDLE-026  # implements: REQ-DOCBUNDLE-840
    """Sorted rel-paths of large `docs/` HTML docs that carry no `generated-from:`
    tag — the doc-sync blind spot: a whole-system doc (built from many requirements)
    that drifts from them with nothing linking the two. A bare `generated-from:` only
    pins ONE id, but the multi-id list (ARCH-SCAN-002) lets one doc name all its
    sources. Walk discipline matches scan_members: honors `.reqmapignore`, prunes
    noise. Skips engine-generated outputs (`_`-prefixed, the published `map.html`
    viewer). Threshold-only + warn-only by design, so it nudges without false alarms."""
    tagged = {fp for hits in members.values()
              for (role, fp, _ln) in hits if role == "generated-from"}
    def wanted(fn, rel):
        return (fn.endswith(".html") and not fn.startswith("_") and fn != "map.html"
                and rel.startswith("docs/") and rel not in tagged)

    out = []
    for fp, rel in _walk_files(code_root, reqs_dir, wanted):
        try:
            if os.path.getsize(fp) >= cfg.DOC_BUNDLE_MIN_BYTES:
                out.append(rel)
        except OSError:
            continue
    return sorted(out)


# Files the "untagged" bucket never lists: prose and repo boilerplate that will not
# carry a tag by design — decision records, issue/PR templates, security policy,
# dependabot config. Everything else scannable and tagless is a real signal.
_UNTAGGED_NOISE = ("adr/*", "*/adr/*", "decisions/*", "*/decisions/*",
                   "*/ISSUE_TEMPLATE/*", "*PULL_REQUEST_TEMPLATE.md",
                   "SECURITY.md", "*/SECURITY.md", "CODE_OF_CONDUCT.md", "*/CODE_OF_CONDUCT.md",
                   "*dependabot.yml", "*/FUNDING.yml")


def untaggable_by_design(rel):
    # implements: ARCH-COVERAGE-029  # implements: REQ-UNTAGGEDSET-1007
    """True for a scannable file that will never carry a membership tag by contract —
    prose in the auto-draft "ignore" bucket (CLAUDE.md, TODO.md, CHANGELOG.md, LICENSE,
    `_`-prefixed: ARCH-PROSE-024) and repo boilerplate (`_UNTAGGED_NOISE`).

    The one definition, because two reports disagreed about it: the "Untagged files"
    bucket skipped these, the per-directory coverage ratio counted them, and the gap
    was two root files that appeared in no bucket, were named nowhere, and made the
    ratio unable to reach 100% no matter what the author tagged."""
    fn = os.path.basename(rel)
    if fn.endswith(PROSE_EXTS) and classify_prose(rel) == "ignore":
        return True
    return any(fnmatch.fnmatch(rel, pat) for pat in _UNTAGGED_NOISE)


def _scan_untagged(code_root, reqs_dir=None):
    # implements: ARCH-NEXT-013  # implements: ARCH-COVERAGE-029
    # implements: REQ-NEXT-886  # implements: REQ-COVERAGE-836
    # implements: REQ-UNTAGGEDSET-1007
    """Scannable files that carry no membership tag at all, as sorted rel paths.
    Skips whatever `untaggable_by_design` excludes — the same set the coverage
    ratio excludes."""
    untagged = []
    for fp, rel in _walk_code(code_root, reqs_dir):
        if untaggable_by_design(rel):
            continue
        tags = _scan_file_tags(fp)
        if tags is not None and not tags:
            untagged.append(rel)
    return sorted(untagged)
# program-logic extensions only: prose/config/styling coverage is ARCH-DOCBUNDLE-026's concern
ORPHAN_CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".cc", ".cpp",
                    ".h", ".hpp", ".java", ".go", ".rs",
                    ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte",
                    ".cs", ".php", ".rb", ".kt", ".kts", ".swift", ".scala", ".ex", ".exs", ".dart")


def orphan_code_files(code_root, covered, reqs_dir=None):
    # implements: ARCH-ORPHANCODE-034  # implements: REQ-ORPHANCODE-888
    """Sorted rel-paths of program-logic files >= ORPHAN_CODE_MIN_LOC lines that
    carry no requirement link — code implementing behavior no requirement describes.
    `covered` is the rel-path set already linked (membership tags + `verifies:`
    coverage), derived from the caller's existing scans so this adds no second tag
    scan. Walk discipline matches scan_members: honors `.reqmapignore`, prunes noise.
    Warn-only at ANY flag combination (the ARCH-COVERAGE-029 Senate audit capped
    coverage signals at advisory — a hard gate makes hollow tags the way to pass CI)."""
    out = []
    for fp, rel in _walk_files(code_root, reqs_dir,
                               lambda fn, r: fn.endswith(ORPHAN_CODE_EXTS) and r not in covered):
        lines, _problem = read_source_lines(fp)
        if lines is None:
            continue
        loc = len(lines)
        if loc >= cfg.ORPHAN_CODE_MIN_LOC:
            out.append(rel)
    return sorted(out)


def undecodable_source_files(code_root, reqs_dir=None):
    # implements: ARCH-UNREADABLE-070  # implements: REQ-UNREADABLE-1004
    """Sorted `(rel, reason)` for every scannable file the scan cannot read as text.

    The counterpart of `tagged_unscanned_files`: that one reports a tag in a file type the
    walk never opens, this one a file the walk DOES open and cannot decode. Both fail the
    same way from the outside — the tag is silently not a member — and neither is visible
    without being named. A UTF-16 file with a BOM is decoded and never appears here; what
    remains is a file whose bytes carry NULs with nothing to key the encoding on."""
    out = []
    for fp, rel in _walk_code(code_root, reqs_dir):
        _text, problem = read_source_text(fp)
        if problem:
            out.append((rel, problem))
    return sorted(out)
