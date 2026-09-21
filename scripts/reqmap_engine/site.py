"""`site`: engine-owned regions injected into a presentation page."""
import os, re

from . import MAP_ENGINE_VERSION
from .git import _git_remote_web_url, _git_root, _repo_name
from .mapdata import _build_map_data
from .site_template import SITE_TEMPLATE


# implements: ARCH-SITE-026  (commands/layers deferred to a follow-up)
SITE_REGIONS = ("nav", "stats")


def _region_markers(name):  # implements: ARCH-SITE-026
    key = name.upper()
    return "<!--##REQMAP:{}##-->".format(key), "<!--##/REQMAP:{}##-->".format(key)


def _inject_region(html, name, inner, anchor="<body>"):
    # implements: ARCH-SITE-026  # implements: REQ-SITE-924
    """Replace the content between the paired markers for `name` with `inner`
    (idempotent). Markers absent -> insert a fresh marked block right after the
    first `anchor`; anchor absent too -> append. Only the marked block is
    written; surrounding (authored) bytes are untouched."""
    open_m, close_m = _region_markers(name)
    block = open_m + "\n" + inner + "\n" + close_m
    # find the close that belongs to THIS open (search after it) so a stray close
    # before the open isn't mistaken for the region end, which would append a
    # duplicate block on re-run instead of rewriting in place
    i = html.find(open_m)
    j = html.find(close_m, i + len(open_m)) if i != -1 else -1
    if i != -1 and j != -1:
        return html[:i] + block + html[j + len(close_m):]
    # `<body class="...">` is still the body tag: a literal find appended the
    # block after `</html>` on any authored page whose body carries attributes
    m = (re.search(r"<body\b[^>]*>", html, re.I) if anchor == "<body>" else None)
    a = m.end() if m else html.find(anchor)
    if a != -1:
        a += 0 if m else len(anchor)
        return html[:a] + "\n" + block + html[a:]
    return html + "\n" + block


def _extract_region(html, name):  # implements: ARCH-SITE-026
    """Inner text between the paired markers for `name`, or None when absent.
    Lets the freshness gate diff only engine-owned regions (prose is exempt)."""
    open_m, close_m = _region_markers(name)
    i = html.find(open_m)
    if i == -1:
        return None
    i += len(open_m)
    j = html.find(close_m, i)
    return html[i:j].strip("\n") if j != -1 else None


def _html_escape(s):  # implements: ARCH-SITE-026
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _site_context_from_data(data, repo_url, map_ok, diagram_rel):  # implements: ARCH-SITE-026
    """Deterministic region inputs derived from the map graph + already-resolved
    link facts. No wall-clock, no filesystem here — callers resolve repo_url /
    map_ok / diagram_rel, so a re-run with no change reproduces byte-identically."""
    nodes = data.get("nodes", [])
    layers = {n.get("layer", "feature") for n in nodes}
    return {
        "repo_url": repo_url,
        "map_ok": map_ok,
        "diagram_rel": diagram_rel,
        "counts": {
            "requirements": len(nodes),
            "confirmed": sum(1 for n in nodes if n.get("status") == "confirmed"),
            "layers": len(layers),
            "edges": len(data.get("edges", [])),
        },
    }


def _render_region(name, ctx):  # implements: ARCH-SITE-026  # implements: REQ-SITE-924
    """Inner HTML for an engine-owned region. NAV: plain target=_blank anchors,
    each emitted only when its target resolves (graceful degradation). STATS:
    deterministic stat cards from the graph counts + engine version."""
    if name == "nav":
        links = []
        if ctx.get("map_ok"):
            links.append('<a href="map.html" target="_blank" rel="noopener">Live Map ↗</a>')
        if ctx.get("diagram_rel"):
            links.append('<a href="{}" target="_blank" rel="noopener">Diagram ↗</a>'
                         .format(_html_escape(ctx["diagram_rel"])))
        if ctx.get("repo_url"):
            links.append('<a href="{}" target="_blank" rel="noopener">GitHub ↗</a>'
                         .format(_html_escape(ctx["repo_url"])))
        return '<nav class="nav-links">' + "".join(links) + '</nav>'
    if name == "stats":
        c = ctx["counts"]
        cells = [("requirements", c["requirements"]), ("confirmed", c["confirmed"]),
                 ("layers", c["layers"]), ("edges", c["edges"]),
                 ("engine", MAP_ENGINE_VERSION)]
        items = "".join('<div class="stat"><b>{}</b><span>{}</span></div>'.format(v, k)
                        for k, v in cells)
        return items
    return ""




def _site_pages_bootstrap(docs_dir):  # implements: ARCH-SITE-026  # implements: REQ-SITE-924
    """Ensure docs/ carries a GitHub Pages signal so ARCH-PAGES-021 publishes and
    the page is servable: write .nojekyll and an index.html redirect when absent.
    Idempotent — never clobbers an existing index.html."""
    os.makedirs(docs_dir, exist_ok=True)
    nojekyll = os.path.join(docs_dir, ".nojekyll")
    if not os.path.exists(nojekyll):
        open(nojekyll, "w").close()
    index = os.path.join(docs_dir, "index.html")
    if not os.path.exists(index):
        with open(index, "w", encoding="utf-8") as f:
            f.write('<!doctype html><meta charset="utf-8">'
                    '<meta http-equiv="refresh" content="0; url=./architecture.html">'
                    '<link rel="canonical" href="./architecture.html">'
                    '<title>Project site</title>'
                    '<p>Redirecting to <a href="./architecture.html">the project site</a>…</p>\n')


def _site_diagram_ok(target_path, diagram_rel):  # implements: ARCH-SITE-026
    """True when `diagram_rel` (relative to the page's directory) names an existing
    file — so the Diagram link is emitted only when the artifact is actually there."""
    if not diagram_rel:
        return False
    return os.path.isfile(os.path.join(os.path.dirname(target_path) or ".", diagram_rel))


def _site_default_target(root):  # implements: ARCH-SITE-026
    """docs/architecture.html at the git root (so running from plugin/ still finds
    the project-root docs/), or None when there is no docs/.

    The site page is the ONE thing the engine writes into docs/. The map used to be
    copied there too; it is not any more — `requirements/_map.html` is the only
    rendered viewer, and a published copy is built where it is published."""
    git_root = _git_root(root)
    docs = os.path.join(git_root, "docs")
    return os.path.join(docs, "architecture.html") if os.path.isdir(docs) else None


def cmd_site(ws, root=".", attach=None,  # implements: REQ-SITE-924
             regions=None, diagram=None, detect=False):  # implements: ARCH-SITE-026
    """Inject engine-owned regions into a presentation page (attach mode) or write
    a default page when the target is absent (scaffold mode). Deterministic and
    headless-safe: never prompts, never raises on missing git/files. `detect`
    prints findings + the suggested command and writes nothing."""
    reqs, members = ws.reqs, ws.members
    regions = regions or ["nav"]
    data = _build_map_data(reqs, members)
    repo_url = _git_remote_web_url(root)

    if detect:
        default = _site_default_target(root)
        cands = [p for p in (default,) if p and os.path.isfile(p)]
        print("repo: {}".format(repo_url or "(no remote)"))
        print("presentation candidates: {}".format(", ".join(cands) or "(none)"))
        tgt = default or os.path.join(root, "docs", "architecture.html")
        print("suggested: reqmap sync --attach {}".format(tgt))
        return 0

    if not attach:
        print("usage: reqmap sync --attach <page.html>")
        print("  the nav and stats regions are refreshed together; `init` scaffolds "
              "the page when it does not exist yet")
        return 0

    map_ok = os.path.isfile(os.path.join(os.path.dirname(attach) or ".", "map.html"))
    diagram_rel = diagram if _site_diagram_ok(attach, diagram) else None
    ctx = _site_context_from_data(data, repo_url=repo_url, map_ok=map_ok, diagram_rel=diagram_rel)

    if os.path.isfile(attach):
        with open(attach, encoding="utf-8") as f:
            html = f.read()
        mode = "refreshed"
    else:                                   # scaffold mode
        os.makedirs(os.path.dirname(attach) or ".", exist_ok=True)
        # escape before substituting — a repo dir name or remote URL with < > " &
        # would otherwise break out of the title/href sinks in the scaffold template
        html = (SITE_TEMPLATE.replace("%%REPO_NAME%%", _html_escape(_repo_name(root) or "this \
project"))
                             .replace("%%REPO_URL%%", _html_escape(repo_url or "#")))
        mode = "scaffolded"

    for name in regions:
        if name in SITE_REGIONS:
            html = _inject_region(html, name, _render_region(name, ctx))

    with open(attach, "w", encoding="utf-8") as f:
        f.write(html)
    print("{} {} (regions: {})".format(mode, attach, ",".join(regions)))
    return 0
