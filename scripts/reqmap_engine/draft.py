"""Drafting requirements from untagged code (`init`'s draft step, `plan`)."""
import os, re

from .candidates import SYS_PLACEHOLDER_ID, _assign_arch_ids, _draft_id, _file_facts
from .parse import parse_frontmatter
from .scan import _walk_files, read_source_text
from .tags import (
    PROSE_EXTS, TAG_RE, _is_code_file, _is_test_path, classify_prose, tag_comment_for,
    tag_insert_index, tagged_files
)


def _prose_facts(src):  # implements: ARCH-PROSE-024  # implements: REQ-PROSE-901
    """(title, [headings]) from markdown/HTML prose, for a draft scaffold.
    Title: markdown frontmatter `title:`, else first `# ` H1, else <title>/<h1>.
    Headings: markdown `## ` H2 lines, else <h2>. Returns (None, []) when absent.
    The scaffold lists headings as an authoring hint — never the contract."""
    meta, body = parse_frontmatter(src)
    title = meta.get("title") or None
    headings, h1_sections = [], []
    for line in body.splitlines():
        s = line.strip()
        if title is None:
            m = re.match(r"#\s+(.+)", s)                      # markdown H1
            if m:
                title = m.group(1).strip()
                continue
            m = re.search(
                r"<(?:title|h1)[^>]*>(.*?)</(?:title|h1)>", s, re.I)
            if m:
                title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                # no continue: a line may carry both <title> and <h2> (see test_html_title_and_h2)
        m = re.match(r"##\s+(.+)", s)                         # markdown H2 (not H3)
        if m:
            headings.append(m.group(1).strip())
            continue
        m = re.match(r"#\s+(.+)", s)   # a further H1: flat, single-level prose
        if m:
            h1_sections.append(m.group(1).strip())
            continue
        for inner in re.findall(r"<h2[^>]*>(.*?)</h2>", s, re.I):  # html H2
            headings.append(re.sub(r"<[^>]+>", "", inner).strip())
    # A prompt corpus (fabric: 255 files) writes every section as `# `: with no H2 at
    # all, the later H1s ARE the sections, and the hint would otherwise be empty.
    return title, (headings or h1_sections)


def _write_sys_placeholder(reqs_dir, arch_ids):
    # implements: ARCH-EXTRACT-008  # implements: REQ-EXTRACT-981
    """The apex, written as an explicit hole.

    A stakeholder need is not in the source — nothing in a repository says why a user
    wants the thing — so the engine refuses to guess one and mints a node whose title
    says so. Skipped only when this file already exists (a second `init` never
    overwrites it). A hand-named need elsewhere in the corpus does NOT suppress it:
    every architecture draft is written pointing at this id, and the engine will not
    guess which real need those drafts satisfy — that is the author's edit, and the
    placeholder's title says so."""
    dest = os.path.join(reqs_dir, SYS_PLACEHOLDER_ID + ".md")
    if os.path.exists(dest) or not arch_ids:
        return 0
    with open(dest, "w", encoding="utf-8") as f:
        f.write("---\nid: {}\nstatus: draft\nlevel: system\nlayer: need\n"
                "owner: auto\nlevel_source: auto\n---\n\n"
                "# NAME THIS NEED\n\n"
                "> The engine cannot read a stakeholder need out of source code, so it "
                "left this hole rather than invent one. Replace the title and the clause "
                "below with the outcome a user actually wants, then rename the file and "
                "the id. Every architecture draft points here until you do.\n\n"
                "## Description\n"
                "Every bullet below is binding.\n"
                "- TODO: the outcome a user wants, in their words, not the system's.\n\n"
                "## Cases\n"
                "CASE-1\n"
                "  Given  TODO\n"
                "  When   TODO\n"
                "  Then   TODO\n".format(SYS_PLACEHOLDER_ID))
    return 1


def _write_arch_drafts(reqs_dir, by_dir, id_of):
    # implements: ARCH-EXTRACT-008  # implements: REQ-EXTRACT-981
    """One architecture draft per source directory that produced code drafts.

    Returns the ids written, newest-corpus-first order irrelevant. Each is a proposal:
    `status: draft`, `owner: auto`, `level_source: auto`, and a title that names the
    directory rather than pretending to name a capability."""
    written = []
    for rel_dir in sorted(by_dir):
        aid = id_of[rel_dir]
        dest = os.path.join(reqs_dir, aid + ".md")
        if os.path.exists(dest):
            written.append(aid)
            continue
        kids = sorted(by_dir[rel_dir])
        with open(dest, "w", encoding="utf-8") as f:
            f.write("---\nid: {aid}\nstatus: draft\nlevel: architecture\n"
                    "layer: feature\nowner: auto\nlevel_source: auto\n"
                    "satisfies: [{sys}]\n---\n\n"
                    "# {label}\n\n"
                    "> PROPOSED grouping, not a capability. The engine had one structural "
                    "signal — the directory `{rel_dir}` — and a directory is not a "
                    "capability. Rename this to the thing these {n} behaviour group(s) "
                    "together let a user do, merge it with a sibling, or delete it and "
                    "re-point its children.\n\n"
                    "## Description\n"
                    "Every bullet below is binding.\n"
                    "{bullets}\n\n"
                    "## Cases\n"
                    "CASE-1\n"
                    "  Given  TODO\n"
                    "  When   TODO\n"
                    "  Then   TODO\n".format(
                        aid=aid, sys=SYS_PLACEHOLDER_ID, label=rel_dir or "root",
                        rel_dir=rel_dir or ".", n=len(kids),
                        bullets="\n".join(
                            "- TODO: one obligation this capability owes. [[{}]]".format(k)
                            for k in kids)))
        written.append(aid)
    return written


def _write_prose_draft(dest, cap, rel, fn, src, arch_id):
    # implements: ARCH-EXTRACT-008  # implements: ARCH-PROSE-024
    # implements: REQ-EXTRACT-849  # implements: REQ-EXTRACT-850
    # implements: REQ-EXTRACT-981
    """Write one DRAFT .md for a prose capability file; returns the review label."""
    title, headings = _prose_facts(src)
    review = "REVIEW"   # intent is unrecoverable from prose — always author
    hint = "\n".join("  - {}".format(h) for h in headings) \
        or "  - (no section headings detected)"
    # str.format (not f-string): the template embeds literal {cap}/{rel}
    # inside backticked instructions
    with open(dest, "w", encoding="utf-8") as f:
        f.write("---\nid: {cap}\nstatus: draft\nlevel: code\n"
                "layer: feature\nowner: auto\nlevel_source: auto\n"
                "satisfies: [{arch}]\ndepends_on: []\n"
                "risk: 2  # REVIEW — prose capability, author the contract "
                "before promoting\n---\n\n"
                "# {title}\n\n"
                "> DRAFT extracted from {rel} (prose capability). The source "
                "prose is NOT the contract — author the normative behavior "
                "below, then tag the source `# generated-from: {cap}` "
                "(HTML: `<!-- generated-from: {cap} -->`) and promote.\n\n"
                "## Description\n"
                "Every bullet below is binding.\n"
                "<!-- Name the subject, write in present tense, one statement per "
                "bullet, at most 3 sentences and 150 words. -->\n"
                "- TODO: the capability this prose defines (author from "
                "intent, do not copy the prose).\n\n"
                "## Verify intent (open questions for the human)\n"
                "- TODO: which source sections are normative vs illustrative?\n\n"
                "## Cases (= tests)\n"
                "- TODO: Given/When/Then checks for the contract above.\n\n"
                # the hint belongs in Context: bullets under Verify intent
                # are read back as open questions by `findings`
                "## Context (non-binding)\n**Current implementation**\n- {rel}\n\n"
                "**Source sections detected (authoring hint, not the contract)**\n"
                "{hint}\n".format(
                    cap=cap, title=(title or os.path.splitext(fn)[0]),
                    rel=rel, hint=hint, arch=arch_id))
    return review


def _write_code_draft(dest, cap, rel, fp, src, arch_id):
    # implements: ARCH-EXTRACT-008  # implements: ARCH-PROSE-024
    # implements: REQ-EXTRACT-849  # implements: REQ-EXTRACT-850
    """Write one DRAFT .md for a code file; returns the review label. `fp` is the
    file's full path (dirpath + fn folded into one, to keep the parameter count down)."""
    fn = os.path.basename(fp)
    risk = _risk(src)
    review = "REVIEW" if risk >= 2 else "auto-baseline"
    surface = _observed_surface(_file_facts(fp, rel))
    with open(dest, "w", encoding="utf-8") as f:
        # emission schema matches REQUIREMENT_TEMPLATE so a promoted draft
        # needs no reshaping
        f.write(f"---\nid: {cap}\nstatus: draft\nlevel: code\n"
                f"layer: feature\nowner: auto\nlevel_source: auto\n"
                f"satisfies: [{arch_id}]\n"
                f"depends_on: []\n"
                f"risk: {risk}  # {review} — author triage hint, not read by "
                f"the engine\n---\n\n"
                f"# {os.path.splitext(fn)[0]}\n\n"
                f"> DRAFT extracted from {rel}. Describes observed behavior, "
                f"not validated intent.\n\n"
                f"## Description\n"
                f"Every bullet below is binding.\n"
                f"<!-- Name the subject, write in present tense, one statement per "
                f"bullet, at most 3 sentences and 150 words. -->\n"
                f"- TODO: the observed behavior (characterization — "
                f"correctness UNVERIFIED).\n\n"
                f"## Verify intent (open questions for the human)\n"
                f"- TODO: anything that looks like an accident (swallowed error, magic "
                f"constant, dead branch) — intended, or a bug to fix?\n\n"
                f"## Cases (= tests)\n"
                f"- characterization: current behavior captured, correctness UNVERIFIED\n\n"
                f"## Context (non-binding)\n**Current implementation**\n- {rel}\n{surface}")
    return review


def _tag_the_source(fp, rel, cap, is_test):
    # implements: ARCH-EXTRACT-008  # implements: REQ-INITTAG-1008
    """Write the membership tag for `cap` into its own source file. True when written.

    Without this, `init` wrote a stub and left the source untagged, so the file stayed in
    the untagged bucket forever and `gate --risk` kept proposing the `init` that had
    already run — while the stub it produced had zero members. A consumer deleted eleven
    such orphans by hand before anyone noticed the loop.

    Reversible by `init --wipe`, which strips exactly the markers `tag_comment_for` writes.
    Skipped, never forced, when the file type has no comment form, when it is already
    tagged, or when it cannot be read as text — a file the scan cannot decode must not be
    rewritten from a half-decoding."""
    line = tag_comment_for(rel, "tested-by" if is_test else "implements", cap)
    if line is None:
        return False
    text, problem = read_source_text(fp)
    if text is None or problem:
        return False
    if TAG_RE.search(text):
        return False                     # already linked: never a second tag
    # `read_source_lines` normalises line endings (that is what a tag's line NUMBER means);
    # a rewrite must not, or every CRLF file silently converts to LF. `splitlines(keepends)`
    # round-trips exactly, so the bytes outside the inserted line are untouched.
    lines = text.splitlines(keepends=True)
    at = tag_insert_index(lines)
    eol = "\r\n" if "\r\n" in text else "\n"
    lines.insert(at, line + eol)
    if at and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += eol             # the preamble had no trailing newline
    try:
        with open(fp, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.writelines(lines)
    except OSError:
        return False
    return True


def cmd_extract(ws):
    # implements: ARCH-EXTRACT-008  # implements: ARCH-PROSE-024
    # implements: REQ-EXTRACT-849  # implements: REQ-EXTRACT-850
    """Propose DRAFT requirements for code files that have no member tag yet."""
    members, reqs_dir, code_root = ws.members, ws.reqs_dir, ws.code_root
    tagged = tagged_files(members)   # the same definition `plan` reports (REQ-PLANTAGGED-1005)
    proposed, tagged_n, used = 0, 0, set()
    jobs = []            # pending writes: (fp, rel, is_prose, dest, cap, rel_dir)
    os.makedirs(reqs_dir, exist_ok=True)
    for fp, rel in _walk_files(code_root, reqs_dir,
                               lambda fn, _r: _is_code_file(fn) or fn.endswith(PROSE_EXTS)):
        dirpath, fn = os.path.dirname(fp), os.path.basename(fp)
        is_prose = fn.endswith(PROSE_EXTS)
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
        rel_dir = os.path.relpath(dirpath, code_root).replace(os.sep, "/")
        jobs.append((fp, rel, is_prose, dest, cap, rel_dir))
    id_of = _assign_arch_ids({rel_dir for *_rest, rel_dir in jobs})
    by_dir = {}          # rel dir -> [code-level draft ids], for the ARCH rung
    for fp, rel, is_prose, dest, cap, rel_dir in jobs:
        dirpath, fn = os.path.dirname(fp), os.path.basename(fp)
        src, _problem = read_source_text(os.path.join(dirpath, fn))
        src = src or ""          # undecodable: draft the stub from its path, not from rubbish
        arch_id = id_of[rel_dir]
        if is_prose:
            review = _write_prose_draft(dest, cap, rel, fn, src, arch_id)
        else:
            review = _write_code_draft(dest, cap, rel, fp, src, arch_id)
        proposed += 1
        by_dir.setdefault(rel_dir, []).append(cap)
        linked = _tag_the_source(fp, rel, cap, _is_test_path(rel))
        tagged_n += linked
        print(f"{review:14} {cap}  <- {rel}{'' if linked else '   (source not tagged)'}")
    # The two rungs above the code level. Written last, so they know their children.
    arch_ids = _write_arch_drafts(reqs_dir, by_dir, id_of)
    n_sys = _write_sys_placeholder(reqs_dir, arch_ids)
    if arch_ids:
        print(f"\n{len(arch_ids)} architecture draft(s) proposed from directory names, and "
              f"{n_sys} system placeholder. Both carry `level_source: auto` — the engine "
              f"invented them and a directory is not a capability. Rename, merge or delete "
              f"them; the code level below is the only rung it can assert.")
    print(f"\n{proposed} draft requirements proposed. Review the REVIEW ones before promoting.")
    if proposed:
        print(f"{tagged_n} of {proposed} source file(s) were linked to their draft in place "
              f"(`init --wipe` removes those tags). The rest have no comment form the "
              f"engine writes, or were already linked — tag them by hand or they stay in "
              f"the untagged bucket.")
    return 0


def _observed_surface(facts, limit=12):  # implements: ARCH-EXTRACT-008
    """Authoring hint for a code draft's Context/Current-implementation group: the
    module docstring's first line and the top-level signatures `plan` already knows
    how to read. Empty string when the language has no parser. Non-binding by
    construction — it lives under Context, never in the Contract, so a promoted
    draft still needs an authored contract."""
    sigs = list(facts.get("signatures") or [])
    doc = (facts.get("docstrings") or {}).get("module")
    if not sigs and not doc:
        return ""
    lines = ["", "Observed surface (auto, non-binding — an authoring hint, not the contract):"]
    if doc:
        lines.append("- module: {}".format(doc))
    lines += ["- `{}`".format(s) for s in sigs[:limit]]
    if len(sigs) > limit:
        lines.append("- … {} more".format(len(sigs) - limit))
    return "\n".join(lines) + "\n"


def _risk(src):  # implements: ARCH-EXTRACT-008  # implements: REQ-EXTRACT-851
    score = 0
    if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", src): score += 1
    if "# noqa" in src or "eslint-disable" in src: score += 1
    if len(src.splitlines()) > 300: score += 1
    return score
