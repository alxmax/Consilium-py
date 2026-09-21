"""Requirement files on disk: frontmatter, multi-block files, load_requirements."""
import os, re, sys

from .model import Requirement


def _scalar_value(v):  # implements: ARCH-PARSE-001
    """One frontmatter scalar value. If it opens with a matching quote, take the
    quoted span verbatim — a '#' inside is DATA, and any text after the closing
    quote (e.g. an inline comment) is dropped. Otherwise drop a ' #' / leading '#'
    comment, preserving an embedded '#' with no leading space (issue#123)."""
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'":
        end = v.find(v[0], 1)
        if end != -1:
            return v[1:end]                       # quoted: inner '#' is data
    return re.split(r'(?:^|\s)#', v, 1)[0].strip()




def _parse_meta_lines(lines):  # implements: ARCH-PARSE-001  # implements: REQ-PARSE-891
    """The frontmatter key/value reader: scalars, inline `[a, b]` lists, and the
    block form (`key:` then indented `- item` lines). Takes the lines between the
    fences, so it never has to know where the block began."""
    meta = {}
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
            meta[k] = [x for x in (_scalar_value(x) for x in inner.split(",")) if x]
        elif not v:
            # block-style list: consume following indented `- item` lines.
            # No items -> keep the empty scalar (e.g. an unset superseded_by).
            items = []
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                items.append(_scalar_value(lines[i].lstrip()[2:]))
                i += 1
            meta[k] = [x for x in items if x] if items else ""
        else:
            # A quoted value keeps an inner '#' verbatim; a bare value treats
            # '#' as a comment only at the start or after whitespace (so
            # "issue#123" is preserved). See _scalar_value.
            meta[k] = _scalar_value(v)
    return meta


def parse_frontmatter(text):
    # implements: ARCH-PARSE-001  # implements: REQ-PARSE-891  # implements: REQ-PARSE-892
    """Return (meta_dict, body). Minimal YAML: scalars, inline [a, b] lists, and the
    block form (`key:` then indented `- item` lines). An inline list missing its
    closing `]` is parsed leniently rather than silently kept as a literal string."""
    meta, body = {}, text.lstrip("﻿")  # tolerate a stray UTF-8 BOM
    if not body.startswith("---"):
        return meta, body
    end = body.find("\n---", 3)
    if end == -1:
        return meta, body
    block = body[3:end]
    body = body[end + 4:].lstrip("\r\n")   # tolerate a CRLF close (\r\n--- )
    return _parse_meta_lines(block.splitlines()), body


# A requirement file may hold SEVERAL requirements, one per frontmatter block — a module
# in the DOORS sense: the architecture requirement, then the code requirements beneath it.
# A block begins at a `---` line immediately followed by `id:`. That lookahead is what makes
# the split unambiguous: a bare `---` is a markdown horizontal rule and a frontmatter close,
# both of which appear inside a body, and neither is followed by an id line.
_REQ_BLOCK_RE = re.compile(r"(?m)^---[ \t]*\r?\n(?=id:)")   # implements: REQ-MODULEFILE-056


def split_requirement_blocks(text):  # implements: REQ-MODULEFILE-056
    """Split one file's text into its requirement blocks, each ready for
    `parse_frontmatter`. A single-requirement file yields exactly one block, byte-identical
    to the whole text, so nothing about the existing corpus changes."""
    text = text.lstrip("\ufeff")
    parts = _REQ_BLOCK_RE.split(text)
    if len(parts) <= 1:
        return [text]
    out = []
    if parts[0].strip():                 # anything before the first block is a file preamble
        out.append(parts[0])
    for chunk in parts[1:]:
        out.append("---\n" + chunk)
    return out or [text]


def load_requirements(reqs_dir):
    # implements: ARCH-PARSE-001  # implements: REQ-MODULEFILE-056
    # implements: REQ-PARSE-890  # implements: REQ-PARSE-892
    """Every requirement in the directory, keyed by id: `{id: {meta, body, path, ...}}`.
    One file may hold several blocks (REQ-MODULEFILE-056); an unreadable or
    id-less file is skipped rather than raising, so one bad file cannot blind
    the whole corpus."""
    reqs = {}
    if not os.path.isdir(reqs_dir):
        return reqs
    for name in sorted(os.listdir(reqs_dir)):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        path = os.path.join(reqs_dir, name)
        try:
            with open(path, encoding="utf-8-sig") as f:  # tolerate a UTF-8 BOM
                text = f.read()
        except (OSError, ValueError) as exc:   # ValueError covers UnicodeDecodeError
            print("WARNING: skipping unreadable requirement file {!r}: {}".format(name, exc),
                  file=sys.stderr)
            continue
        for _i, _blk in enumerate(split_requirement_blocks(text)):
            meta, body = parse_frontmatter(_blk)
            # only the FIRST block may fall back to the filename; a later block without an
            # explicit id is a malformed block, not a second requirement named after the file.
            # A file preamble (REQ-MODULEFILE-056) can also land at index 0 when the real
            # block 0 is preceded by prose — but a preamble never starts with the frontmatter
            # delimiter '---' (parse_frontmatter's own test for "this text has frontmatter"),
            # so gating the fallback on that same test keeps prose from minting a synthetic id
            # that can collide with (and silently shadow) the real block 0's own id.
            rid = meta.get("id") or (
                os.path.splitext(name)[0] if _i == 0 and _blk.startswith("---") else None)
            if not rid:
                continue
            if rid in reqs:
                # two blocks claim the same id: keep the first (sorted) and warn, rather
                # than let the later one silently shadow it (the gate can't catch this —
                # the id still resolves, just to the wrong block).
                print("WARNING: duplicate requirement id {!r} in {!r} — keeping {!r}".format(
                    rid, name, os.path.basename(reqs[rid]["path"])), file=sys.stderr)
                continue
            reqs[rid] = Requirement(meta=meta, body=body, path=path, block=_i)
    return reqs
