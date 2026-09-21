"""Membership tags: the tag grammar, which files count as code or prose, string/comment masking,
the per-file tag scan, and the test-path / prose classifiers.
"""
import os, re

from . import config as cfg


ROLES = ("implements", "generated-from", "validated-against", "tested-by")
# Both tag patterns are BUILT from ROLES rather than repeating it. The three used to be
# maintained by hand, which made ROLES look authoritative while driving nothing: adding a
# role there changed no behaviour, and the real vocabulary lived inside two regex literals.
_ROLE_ALT = "|".join(ROLES)
# the (?<![\w-]) left boundary stops substring matches like `reimplements:` or
# `x-implements:` from being picked up as a real `implements:` tag
_ID_PAT = r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+"
TAG_RE = re.compile(r"(?<![\w-])(" + _ROLE_ALT + r")\s*:\s*(" + _ID_PAT + r")")
# A single tag may bind several requirements via a comma-separated id list (one
# `<!-- generated-from: ... -->` listing several ids) — used for a whole-system doc
# generated from many requirements, so a contract drift on ANY of them lists the doc
# to re-sync. TAG_RE (single id) stays for callers that only need the tag's start
# position; TAG_LIST_RE captures the whole id list, which _findall_tags expands.
TAG_LIST_RE = re.compile(r"(?<![\w-])(" + _ROLE_ALT + r")\s*:\s*("
                         + _ID_PAT + r"(?:\s*,\s*" + _ID_PAT + r")*)")
_ID_RE = re.compile(_ID_PAT)


def _findall_tags(text):  # implements: REQ-VLEVEL-944
    """Like ``TAG_RE.findall`` but expands a comma-separated id list into one
    ``(role, id)`` pair per id, so ``generated-from: A-1, B-2`` yields two members."""
    out = []
    for role, idlist in TAG_LIST_RE.findall(text):
        for cap in _ID_RE.findall(idlist):
            out.append((role, cap))
    return out


# Phantom-member exclusion helpers used in _scan_file_tags
_FENCE_RE = re.compile(r'^(`{3,}|~{3,})')   # CommonMark fence opener/closer
# NOTE: only handles single-backtick spans; double/triple-backtick spans (CommonMark-valid)
# are not filtered. No instances exist in this corpus, but this is a known gap.
_BACKTICK_RE = re.compile(r'`[^`]*`')         # inline backtick span (strip before tag search)
# Per-acceptance-criterion coverage tag, placed in a test: `# verifies: <ID>#AC-1`.
# The id is spelled `<ID>` for the same reason the `tested-by:` example below is: a
# real-looking id in a PLAIN COMMENT is scanned as an actual tag (backtick spans are
# stripped only for .md/.html), and `REQ-X` here was silently recorded as per-case
# coverage for a requirement that does not exist until RM034 named it.
# Finer-grained sibling of `tested-by` — links ONE test to ONE labelled criterion so
# "Verifiable" becomes machine-checked per criterion, not just per requirement. The
# `#AC-N` suffix is what distinguishes it from a plain requirement reference.
AC_VERIFY_RE = re.compile(r"(?<![\w-])verifies\s*:\s*(" + _ID_PAT + r")#((?:CASE|AC)-\d+)")
# Verification level on a `tested-by:` tag, written `# tested-by: <ID> @integration`.
# The id is spelled `<ID>` here on purpose: a real-looking id in a PLAIN COMMENT would be
# scanned as an actual tag. `_scan_file_tags` strips backticked spans only on the .md/.html
# path; on the code path its guard is `_strip_py_strings`, which masks string literals and
# leaves comments alone. Docstrings are safe; comments are not.
# The level applies to the whole tag, so a comma-separated id list shares it — the only
# unambiguous reading, and it matches how TAG_LIST_RE already groups ids. The suffix is
# invisible to TAG_RE/TAG_LIST_RE, so an older vendored engine reads a levelled tag,
# resolves the id, and ignores the level (ARCH-VLEVEL-037).
TEST_LEVELS = ("unit", "integration", "system")
TEST_LEVEL_RE = re.compile(
    r"(?<![\w-])tested-by\s*:\s*(" + _ID_PAT + r"(?:\s*,\s*" + _ID_PAT + r")*)"
    r"\s*@(" + "|".join(TEST_LEVELS) + r")\b")

# Extensionless filenames scanned by exact basename match (no case-fold — CODE_EXTS
# is suffix-based and case-sensitive too, so this stays consistent). Git hook names
# (pre-commit, pre-push, ...) are as conventional and unambiguous as Dockerfile/
# Makefile — a repo's own .githooks/ scripts are exactly the kind of scannable
# pipeline code v2.9's "tag your own pipeline" item covers; an unrelated file that
# happens to share one of these names is a harmless no-op scan (no tag = no member).
BASENAME_CODE_FILES = {"Dockerfile", "Makefile",
                       "Caddyfile", "Jenkinsfile", "Procfile", "Vagrantfile",
                       "pre-commit", "pre-push", "pre-receive", "post-receive",
                       "commit-msg", "prepare-commit-msg", "post-checkout", "post-merge"}


def _is_code_file(fn):  # implements: ARCH-SCAN-002
    """True if fn should be scanned as code: matches CODE_EXTS, an extensionless
    basename like Dockerfile/Makefile, or a Dockerfile variant (`Dockerfile.dev`,
    `Dockerfile.converter` — a consumer tagged one and nothing read it)."""
    return fn.endswith(cfg.CODE_EXTS) or fn in BASENAME_CODE_FILES or fn.startswith("Dockerfile.")

# ---- prose auto-draft classification (cmd_extract) ----
# These buckets govern AUTO behavior (drafting) ONLY. scan_members still honors an
# explicit tag on ANY file, regardless of bucket — buckets never suppress a real tag.
PROSE_EXTS = (".md", ".html")
# Bucket 1 — meta/boilerplate: never auto-drafted, never sync-checked. Basename match.
META_IGNORE_NAMES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md", "CONTRIBUTING.md",
                     "SKILL.md", "TODO.md", "CHANGELOG.md"}


def _strip_py_quote_end(s, c, i, n):
    """Index just past the single-line string opened by quote char `c`, scanning
    forward from i (already past the opening quote), honouring backslash escapes."""
    while i < n and s[i] != c and s[i] != '\n':
        i += 2 if s[i] == '\\' and i + 1 < n else 1
    return i


def _strip_py_strings(s):
    """Mask Python string literal contents with spaces; detect an unclosed triple-quote.

    Handles single-line '' / "" strings and triple-quoted forms (both ''' and \""").
    Triple-quote detection takes precedence over single-quote detection.
    A '#' after all string content is consumed is preserved as-is (it starts a comment).

    Returns (masked_line, in_triple_or_None):
      masked_line        — line with all string *content* replaced by spaces
      in_triple_or_None  — the triple-quote delimiter ('\"\"\"' or \"'''\") if one opened
                           and did not close on this line, else None.
    """
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if i + 2 < n and s[i:i+3] in ('"""', "'''"):
            q = s[i:i+3]
            out.append('   ')    # mask the opening delimiter
            i += 3
            j = s.find(q, i)
            if j == -1:
                out.append(' ' * (n - i))
                return ''.join(out), q
            out.append(' ' * (j - i + 3))
            i = j + 3
        elif c in ('"', "'"):
            out.append(' ')
            i += 1
            start = i
            i = _strip_py_quote_end(s, c, i, n)
            out.append(' ' * (i - start))
            if i < n and s[i] == c:
                out.append(' ')
                i += 1
        elif c == '#':
            out.append(s[i:])
            break
        else:
            out.append(c)
            i += 1
    return ''.join(out), None


def _fence_transition(stripped, fence):
    # implements: ARCH-SCAN-002  # implements: REQ-SCAN-908  # implements: REQ-SCAN-992
    """(new_fence, is_marker) for one prose line: `is_marker` is True when `stripped`
    is a fence opener/closer line itself (so the caller skips yielding it), and
    `new_fence` is the fence state to carry into the next line."""
    fm = _FENCE_RE.match(stripped)
    if not fm:
        return fence, False
    marker = fm.group(1)
    rest = stripped[len(marker):].strip()
    if fence is None:
        return marker, True
    if marker[0] == fence[0] and len(marker) >= len(fence) and not rest:
        return None, True   # closer must be bare (no info string)
    return fence, False


def _close_triple_quote(s, in_triple):
    # implements: ARCH-SCAN-002  # implements: REQ-SCAN-908  # implements: REQ-SCAN-992
    """(remaining_text, still_open) for a line continuing a triple-quoted string
    opened on a previous line: None remaining when `in_triple` does not close here."""
    idx = s.find(in_triple)
    if idx == -1:
        return None, in_triple
    return s[idx + len(in_triple):], None


def _visible_lines(fp, lines):
    # implements: ARCH-SCAN-002  # implements: REQ-SCAN-908  # implements: REQ-SCAN-992
    """Yield `(lineno, text)` for every line of `fp` a tag may legitimately live on,
    with the excluded zones already removed or blanked.

    ONE masking pass for every scanner in the engine. There used to be three
    hand-copied ones — `_scan_file_tags`, `_extract_coverage` and `_walk_code_lines` —
    and they had already drifted: only the first knew what a Markdown fence was, so a
    `# verifies: ID#CASE-1` written inside a ```-fenced EXAMPLE counted as real
    per-criterion coverage and silenced the very warning that says the case is
    untested. A masking rule that lives in one place cannot be half-applied.

    PROSE (.md, .html): a fenced code block (``` / ~~~, CommonMark length-matched)
      and, in Markdown only, a >=4-space / tab indented block are code — those lines
      are not yielded at all. `<!-- implements: X -->` outside any such zone is a
      valid tag position and is yielded.
    PY: a triple-quoted string (state carried across lines) and single-line string
      literals are blanked. Comments are kept — `code()  # implements: X` is a real tag.
    Anything else: yielded unchanged.

    Backtick spans are deliberately NOT stripped here. The callers disagree on that
    (see `_extract_coverage`), and folding it in would hide a difference that is
    load-bearing. State is local, so nothing leaks between files.
    """
    ext = os.path.splitext(fp)[1].lower()
    if ext in PROSE_EXTS:
        fence = None   # None = not fenced; else the opening fence string e.g. "```"
        for i, raw in enumerate(lines, 1):
            s = raw.rstrip("\n\r")
            # Markdown indented code block (>=4 spaces / tab): treat as code so an
            # indented ```-prefixed line never opens a phantom fence that would
            # swallow every later tag, and an indented tag is excluded. Checked
            # BEFORE fence detection. HTML has no indented-code concept, so the
            # guard is Markdown-only — an indented tag comment in HTML stays valid.
            if ext == ".md" and (s.startswith("    ") or s.startswith("\t")):
                continue
            stripped = s.lstrip()
            fence, is_marker = _fence_transition(stripped, fence)
            if is_marker:
                continue
            if fence is None:
                yield i, s

    elif ext == ".py":
        in_triple = None   # None or the opening triple-quote delimiter
        for i, raw in enumerate(lines, 1):
            s = raw.rstrip("\n\r")
            if in_triple is not None:
                s, in_triple = _close_triple_quote(s, in_triple)
            if s is None:
                continue
            s, in_triple = _strip_py_strings(s)
            yield i, s

    else:
        for i, raw in enumerate(lines, 1):
            yield i, raw.rstrip("\n\r")


def _scan_file_tags(fp, lines=None):  # implements: ARCH-SCAN-002  # implements: REQ-SCAN-908
    """Membership tags in one file as [[role, cap, line], ...], or None on read error.

    `lines` lets a caller that has already read the file hand the content over, so the
    single-walk scanner (`scan_all`) reads each file once for all three extractors
    instead of three times. `fp` is still required: the masking rules key off its
    extension. Reading it here when `lines` is None keeps every existing caller working.

    Which positions count is `_visible_lines`' business; this adds the one rule that is
    its own — a prose backtick span is an example, not a tag — and de-duplicates the
    same (role, id) pair repeated on one line.
    """
    out = []
    if lines is None:
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            return None
    prose = os.path.splitext(fp)[1].lower() in PROSE_EXTS
    for i, s in _visible_lines(fp, lines):
        if prose:
            s = _BACKTICK_RE.sub("", s)
        seen = set()
        for role, cap in _findall_tags(s):
            key = (role, cap)
            if key not in seen:
                seen.add(key)
                out.append([role, cap, i])
    return out


def classify_prose(rel):  # implements: ARCH-PROSE-024  # implements: REQ-PROSE-900
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
    if base.upper() == "README" or base.upper().startswith("README."):   # readme.md is a README too
        return "sync_only"
    if rel == "docs" or rel.startswith("docs/"):
        return "sync_only"
    if rel.endswith(".html"):                      # all HTML is an overview/derived doc
        return "sync_only"
    # Bucket 3 — capability source (prompts/specs/modes and other prose .md).
    return "capability"
_TEST_DIR_NAMES = {"test", "tests", "spec", "specs", "__tests__", "testing", "e2e"}
_TEST_FILE_SUFFIXES = ("_test.py", "_test.go", "_test.rs", "_spec.rb", ".test.ts", ".test.tsx",
                       ".test.js", ".test.jsx", ".spec.ts", ".spec.tsx", ".spec.js", ".e2e.ts")


def _is_test_path(rel):  # implements: ARCH-CANDIDATES-009  # implements: REQ-CANDIDATES-827
    """Test code by convention (a `tests/` segment, `test_*.py`, `*_test.go`, `*.spec.ts`)."""
    parts = rel.replace(os.sep, "/").split("/")
    base = parts[-1]
    return (any(p in _TEST_DIR_NAMES for p in parts[:-1])
            or base.startswith("test_") or base.endswith(_TEST_FILE_SUFFIXES))


def tagged_files(members):
    # implements: ARCH-CANDIDATES-009  # implements: REQ-PLANTAGGED-1005
    """`{rel_path: requirement_id}` for every file that already carries a membership tag —
    the one definition of "this file is already accounted for".

    `plan` and the write path used to disagree about it: `plan` counted only `implements:`,
    so a test file linked by `tested-by:` was reported as a NEW draft, while `init` skipped
    that same file because it counted every role. On a 96%-tagged consumer corpus `--plan`
    listed 123 NEW candidates of which ~120 were tests that would never have been written.
    `--plan` exists to say what the write path will do, so the two read one function.

    First tag wins per file, in `members` order, so the hint is stable across runs."""
    out = {}
    for cap, hits in members.items():
        for _role, fp, _ln in hits:
            out.setdefault(fp, cap)
    return out


# How a membership tag is spelled in each file type. `_strip_line_tag` already knows how to
# REMOVE a tag behind any of these markers (`init --wipe`); this is the other direction, and
# the two must agree or a wipe would not undo a write.
_HASH, _SLASH, _HTML, _BLOCK, _DASH = "#", "//", "<!--", "/*", "--"
_TAG_COMMENT = {_HTML: "<!-- {} -->", _BLOCK: "/* {} */"}
_MARKER_BY_EXT = {
    ".js": _SLASH, ".ts": _SLASH, ".tsx": _SLASH, ".jsx": _SLASH, ".mjs": _SLASH,
    ".cjs": _SLASH, ".mts": _SLASH, ".cts": _SLASH, ".c": _SLASH, ".cpp": _SLASH,
    ".h": _SLASH, ".hpp": _SLASH, ".cc": _SLASH, ".java": _SLASH, ".go": _SLASH,
    ".rs": _SLASH, ".cs": _SLASH, ".php": _SLASH, ".kt": _SLASH, ".kts": _SLASH,
    ".swift": _SLASH, ".scala": _SLASH, ".dart": _SLASH, ".proto": _SLASH,
    ".prisma": _SLASH, ".graphql": _HASH, ".scss": _SLASH, ".less": _SLASH,
    ".py": _HASH, ".rb": _HASH, ".sh": _HASH, ".yaml": _HASH, ".yml": _HASH,
    ".toml": _HASH, ".tf": _HASH, ".ex": _HASH, ".exs": _HASH, ".sass": _HASH,
    ".html": _HTML, ".vue": _HTML, ".svelte": _HTML, ".md": _HTML,
    ".css": _BLOCK, ".sql": _DASH,
}
# A line that must stay first: the interpreter line, the XML/HTML preamble, and the
# `@charset` a CSS file is only allowed to open with.
_MUST_STAY_FIRST = ("#!", "<?xml", "<?php", "<!doctype", "@charset")


def tag_comment_for(rel, role, cap):
    # implements: ARCH-EXTRACT-008  # implements: REQ-INITTAG-1008
    """The membership tag line to write into `rel`, or None when its type has no known
    line-comment form. `role` is `implements` or `tested-by`."""
    fn = os.path.basename(rel)
    marker = _MARKER_BY_EXT.get(os.path.splitext(fn)[1].lower())
    if marker is None and (fn in BASENAME_CODE_FILES or fn.startswith("Dockerfile.")):
        marker = _HASH          # Dockerfile, Makefile, git hooks: all `#`
    if marker is None:
        return None
    body = "{}: {}".format(role, cap)
    return _TAG_COMMENT.get(marker, marker + " {}").format(body)


def tag_insert_index(lines):
    # implements: ARCH-EXTRACT-008  # implements: REQ-INITTAG-1008
    """Where a tag may be inserted: after any line that must stay first (shebang, XML/HTML
    preamble, `@charset`), else at the top. A UTF-8 BOM rides on line 0, so inserting after
    it — never before — keeps the BOM the first bytes of the file."""
    i = 0
    while i < len(lines):
        s = lines[i].lstrip("﻿").strip().lower()
        if s and s.startswith(_MUST_STAY_FIRST):
            i += 1
            continue
        break
    return i
