"""_map.html: the vendored single-file viewer, and the viewer fixture sync check."""
import json, os

from . import ENGINE_DIR
from .mapjson import _build_json_text


def _vds_normalize(strings):
    return sorted(" ".join(s.split()) for s in strings)


def _vds_parse_baked(path):
    """{id: [contract strings]} from the viewer's `baked.json` fixture, or None when the
    file is missing, unreadable or not a JSON list.

    An entry marked `demoOnly: true` is skipped. The fixture INVENTS a fake orphan and a
    fake deprecated capability so the Risk and Problems tabs have something to show with
    no engine present; those ids cannot exist in any registry, so comparing them reported
    permanent drift about data doing its job. An UNMARKED id missing from the registry
    still reports, because that is a requirement renamed out from under the fixture."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):   # ValueError covers UnicodeDecodeError and bad JSON
        return None
    if not isinstance(data, list):
        return None
    return {e["id"]: [str(c) for c in e.get("contract") or []]
            for e in data
            if isinstance(e, dict) and isinstance(e.get("id"), str) and not e.get("demoOnly")}


def check_viewer_data_sync(baked_path, map_nodes):  # implements: ARCH-VIEWER-007
    """Compare the viewer's hand-authored fallback fixture, `app/src/lib/baked.json`,
    against the live registry (map_nodes: [{"id":..., "contract":[...]}, ...]).
    Returns a sorted list of requirement IDs where the two disagree — a baked id missing
    from the live registry, or a whitespace-normalized mismatch in its `contract`
    bullets. Warn-only. The fixture was a JavaScript literal read by a bracket-counting
    scanner; as JSON it is read as data, so no bullet text can confuse the reader.
    Returns None (not []) when the file is missing, unreadable or not a JSON list —
    fail-open, matching load_ignore()'s convention for an optional file."""
    baked = _vds_parse_baked(baked_path)
    if baked is None:
        return None
    live = {n["id"]: n.get("contract", []) for n in map_nodes}
    drift = [rid for rid, contract in baked.items()
             if rid not in live or _vds_normalize(contract) != _vds_normalize(live[rid])]
    return sorted(drift)


# A pre-built, single-file React viewer ships next to this engine as
# `_map_viewer.html`. It carries the marker `<!--REQMAP_DATA-->`; the engine
# swaps that for a <script> assigning this repo's graph to window.__REQMAP_DATA__,
# producing a self-contained `_map.html` that opens by double-click (no server).
VIEWER_TEMPLATE = "_map_viewer.html"
_REQMAP_DATA_MARKER = "<!--REQMAP_DATA-->"


def _viewer_template_path():  # implements: ARCH-VIEWER-007  # implements: REQ-VIEWER-940
    return os.path.join(ENGINE_DIR, VIEWER_TEMPLATE)


def _inject_viewer(template_text, data):
    # implements: ARCH-VIEWER-007  # implements: REQ-VIEWER-941
    """Replace the data marker with an inline <script> assigning the graph to
    window.__REQMAP_DATA__. Three sequences are escaped so the HTML5 parser
    never changes state mid-blob:
      `</`   → `<\\/`  prevents `</script>` from closing the element early
      `<!--` → `<\\!--` prevents entering "script data escaped" state
      `-->`  → `-\\->`  closes "script data escaped" state prematurely if unclosed
    All three are valid JS string escapes (backslash ignored for `/`, `!`, `-`)."""
    blob = (
        _build_json_text(data)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("-->", "-\\->")
        # U+2028/U+2029 are LINE TERMINATORS in JavaScript but ordinary characters
        # in JSON, so ensure_ascii=False emits them raw and any engine older than
        # ES2019 reads the blob as an unterminated string - one character in one
        # requirement title kills the whole viewer. The escaped forms are valid JSON
        # for the same characters, so the parsed value is unchanged.
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    script = "<script>window.__REQMAP_DATA__=" + blob + ";</script>"
    return template_text.replace(_REQMAP_DATA_MARKER, script, 1)


def render_html(data, reqs_dir):  # implements: ARCH-VIEWER-007  # implements: REQ-VIEWER-940
    """Write the self-contained viewer `_map.html` by injecting `data` into the
    vendored template. Returns the path, or None when no template is present
    (the engine still emits _map.md + _map.json — the viewer is optional)."""
    tpl = _viewer_template_path()
    if not os.path.exists(tpl):
        return None
    with open(tpl, encoding="utf-8") as f:
        template_text = f.read()
    out = os.path.join(reqs_dir, "_map.html")
    os.makedirs(reqs_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_inject_viewer(template_text, data))
    return out
