"""_map.md: the Mermaid diagrams, stale-artifact detection and `map --check`."""
import os, re

from . import MAP_ENGINE_VERSION, config as cfg
from .mapjson import _utf8_safe
from .model import ENFORCED, RISK_ADVICE, _area_of
from .risk import _risk_signals


# ---------- mermaid generators ----------
def _safe_id(rid):
    """Mermaid-safe node ID: replace non-alphanumeric chars with underscores."""
    return re.sub(r"[^A-Za-z0-9]", "_", rid)


def _mlabel(text):
    """Make free text safe inside a quoted Mermaid node label.

    Even inside quotes, Mermaid's parser chokes on backticks, brackets,
    braces, pipes and backslashes; under securityLevel:loose, angle
    brackets would also be rendered as HTML. Neutralize all of them.
    """
    text = text or "—"
    for a, b in (('"', "'"), ("`", "'"), ("[", "("), ("]", ")"),
                 ("{", "("), ("}", ")"), ("|", "/"), ("\\", "/"),
                 ("<", "‹"), (">", "›")):
        text = text.replace(a, b)
    return text


def _node_label(n):
    """Two-line node label: human title big, capability id small below.

    The `<br>`/`<small>` tags are added outside `_mlabel` (which would
    otherwise neutralize the angle brackets); only the title text is
    passed through the sanitizer.
    """
    title = _mlabel(n.get("title") or n["id"])
    return "{}<br><small>{}</small>".format(title, _mlabel(n["id"]))


def _node_area(n):  # implements: ARCH-MAP-007
    """Grouping key for a node: an explicit `area:` frontmatter field wins (lets a
    repo group e.g. several standalone capabilities under one ANALYSIS box without
    renaming ids); otherwise fall back to the id prefix."""
    return (n.get("area") or "").strip() or _area_of(n["id"])


def _grouped_areas(nodes):  # implements: ARCH-MAPDIAGRAMS-055  # implements: REQ-MAPDIAGRAMS-876
    """Order nodes into [(area_label, [node,...]), ...]: multi-node areas first
    (sorted), then one 'misc' bucket of every single-node area. Shared by the
    System / Dependency / Risk diagrams so a 40+ node map stays navigable
    (Miller 7+-2 / C4 levels — split a big diagram by meaningful boundary)."""
    areas = {}
    for n in nodes:
        areas.setdefault(_node_area(n), []).append(n)
    groups = [(a, areas[a]) for a in sorted(areas) if len(areas[a]) > 1]
    singles = [n for a in sorted(areas) if len(areas[a]) == 1 for n in areas[a]]
    if singles:
        # fold the singletons into any pre-existing real "misc" multi-node group
        # rather than appending a second ("misc", …) tuple — two subgraphs with
        # the same _safe_id would break the Mermaid render
        existing = next((i for i, (a, _) in enumerate(groups) if a == "misc"), None)
        merged = sorted(singles, key=lambda n: n["id"])
        if existing is not None:
            groups[existing] = ("misc", groups[existing][1] + merged)
        else:
            groups.append(("misc", merged))
    return groups


def _emit_area_subgraphs(lines, nodes, label_fn=None):
    """Append per-area `subgraph` blocks (singletons collapse into 'misc')."""
    label_fn = label_fn or _node_label
    sg_used = {}
    for area, ns in _grouped_areas(nodes):
        base = _safe_id(area)
        k = sg_used.get(base, 0) + 1
        sg_used[base] = k
        # suffix on collision so two areas that sanitize to the same id (my-area /
        # my_area) don't emit duplicate `subgraph` ids and break the Mermaid render
        sg = base if k == 1 else "{}_{}".format(base, k)
        lines.append('  subgraph sg_{}["{}"]'.format(sg, _mlabel(area)))
        for n in ns:
            lines.append('    {}["{}"]'.format(_safe_id(n["id"]), label_fn(n)))
        lines.append("  end")


def _bus_ids(nodes):
    return [n["id"] for n in nodes if n.get("layer") == "bus"]


def _hub_targets(data, bus_ids):
    """Bus nodes + any node with fan-in >= SYSTEM_HUB_FANIN (the hub hairball)."""
    fanin = {}
    for _src, tgt in data["edges"]:
        fanin[tgt] = fanin.get(tgt, 0) + 1
    return set(bus_ids) | {nid for nid, c in fanin.items() if c >= cfg.SYSTEM_HUB_FANIN}


def _mermaid_system(data):  # implements: ARCH-MAPDIAGRAMS-055  # implements: REQ-MAPDIAGRAMS-876
    # Per-area subgraphs + hide edges into bus/hubs (the hairball); the full graph
    # is in the Dependency Map. Bus nodes keep a thick stroke.
    lines = ["graph LR"]   # left-right fills a wide/landscape area better than top-down
    bus_ids = _bus_ids(data["nodes"])
    _emit_area_subgraphs(lines, data["nodes"])
    hubs = _hub_targets(data, bus_ids)
    for a, b in data["edges"]:
        if b not in hubs:
            lines.append("  {} --> {}".format(_safe_id(a), _safe_id(b)))
    for bid in bus_ids:
        lines.append("  style {} stroke-width:3px".format(_safe_id(bid)))
    return "\n".join(lines)


def _mermaid_deps(data):  # implements: ARCH-MAPDIAGRAMS-055  # implements: REQ-MAPDIAGRAMS-877
    # Area-level coupling overview (C4 'container' zoom-out): one box per area, an
    # edge A->B when ANY capability in A depends on one in B. Aggregating the
    # per-capability edges here kills the bus hub hairball; the System Map keeps
    # the per-capability detail and the detail panel lists each node's deps.
    groups = _grouped_areas(data["nodes"])
    if not groups:
        return 'graph LR\n  none["(no requirements)"]'
    label_of, counts, bus_areas = {}, {}, set()
    for label, ns in groups:
        counts[label] = len(ns)
        for n in ns:
            label_of[n["id"]] = label
            if n.get("layer") == "bus":
                bus_areas.add(label)
    edges = set()
    for a, b in data["edges"]:
        la, lb = label_of.get(a), label_of.get(b)
        if la and lb and la != lb:
            edges.add((la, lb))
    # suffix on collision so two areas that sanitize to the same id (my-area /
    # my_area) don't collapse into one Mermaid node -- mirrors _emit_area_subgraphs,
    # which already guards its own sg_ ids the same way.
    id_used, id_of = {}, {}
    for label in sorted(counts):
        base = _safe_id(label)
        k = id_used.get(base, 0) + 1
        id_used[base] = k
        id_of[label] = "a_" + (base if k == 1 else "{}_{}".format(base, k))

    lines = ["graph LR"]
    for label in sorted(counts):
        lines.append('  {}["{}<br><small>{} caps</small>"]'.format(
            id_of[label], _mlabel(label), counts[label]))
    for la, lb in sorted(edges):
        lines.append("  {} --> {}".format(id_of[la], id_of[lb]))
    for label in sorted(bus_areas):
        lines.append("  style {} stroke-width:3px".format(id_of[label]))
    return "\n".join(lines)


def _mermaid_req_to_code(data):
    # implements: ARCH-MAPDIAGRAMS-055  # implements: REQ-MAPDIAGRAMS-877
    lines = ["graph LR"]
    loc_sid, sid_used = {}, {}        # distinct file:line locs must get distinct node ids
    for n in data["nodes"]:
        if n.get("level") == "code":
            # Counted, never drawn: a corpus with its behaviour
            # groups split out carries hundreds of code-level nodes and their members
            # at function granularity — the block passed 83,000 characters, past what
            # GitHub renders. The viewer has that detail; this diagram is the overview.
            continue
        rid = n["id"]
        sid = _safe_id(rid)
        lines.append('  {}["{}"]'.format(sid, _node_label(n)))
        if not n["members"]:
            # enforced-but-unlinked is a real gap (red); a baseline/draft not yet
            # tagged is expected, so render it muted grey rather than alarming red
            if n.get("status") in ENFORCED:
                lines.append("  style {} fill:#fee,stroke:#c66".format(sid))
            else:
                lines.append("  style {} fill:#eee,stroke:#bbb,color:#888".format(sid))
            continue
        # group by role+file, compute min/max line numbers
        groups = {}
        for m in n["members"]:
            c = m["loc"].rfind(":")
            f, ln = m["loc"][:c], int(m["loc"][c + 1:])
            k = m["role"] + "|" + f
            if k not in groups:
                groups[k] = {"role": m["role"], "f": f, "min": ln, "max": ln}
            else:
                groups[k]["min"] = min(groups[k]["min"], ln)
                groups[k]["max"] = max(groups[k]["max"], ln)
        for g in groups.values():
            loc = "{}:{}".format(g["f"], g["min"]) if g["min"] == g["max"] \
                  else "{}:{}-{}".format(g["f"], g["min"], g["max"])
            if loc in loc_sid:
                file_sid = loc_sid[loc]
            else:
                base = "f_" + re.sub(r"[^A-Za-z0-9]", "_", loc)
                k = sid_used.get(base, 0) + 1
                sid_used[base] = k
                # suffix on collision so two different locs that sanitize to the same
                # id (e.g. a-b.py vs a_b.py) don't merge into one mislabeled node
                file_sid = base if k == 1 else "{}_{}".format(base, k)
                loc_sid[loc] = file_sid
            lines.append('  {}["{}"]'.format(file_sid, _mlabel(loc)))
            lines.append("  {} -->|{}| {}".format(sid, g["role"], file_sid))
    return "\n".join(lines)


def _mermaid_risk(data):  # implements: ARCH-MAPDIAGRAMS-055  # implements: REQ-MAPDIAGRAMS-878
    risky = [(n, _risk_signals(n)) for n in data["nodes"]]
    risky = [(n, s) for n, s in risky if s]

    lines = ["graph LR"]
    if not risky:
        lines.append('  ok["No risk signals detected"]')
        return "\n".join(lines)

    # Grouped by area, colored by signal, NO edges — Risk answers "which
    # capabilities need attention", not topology (the Dependency Map has edges).
    sigs_by = {n["id"]: s for n, s in risky}
    _emit_area_subgraphs(lines, [n for n, _ in risky],
                         label_fn=lambda n: _node_label(n) + "<br>" + ", ".join(sigs_by[n["id"]]))
    for n, sigs in risky:
        sid = _safe_id(n["id"])
        if "unimplemented" in sigs:
            lines.append("  style {} fill:#fee,stroke:#c00,color:#900".format(sid))
        elif "unreviewed" in sigs:
            lines.append("  style {} fill:#fff3cd,stroke:#a66,color:#630".format(sid))
        else:
            lines.append("  style {} fill:#fff9c4,stroke:#aa0,color:#550".format(sid))
    return "\n".join(lines)


# Per-tab legends (parallel to the 4 diagrams emitted by _build_md_text, same
# order) so each view is self-explanatory. HTML uses colored swatches; markdown
# uses words.
_LEGEND_MD = [
    "Capabilities grouped by area; thick border = bus; arrows = `depends_on`. Edges into the "
        "bus/hubs are hidden (the Dependency Map shows area-level coupling).",
    "Each system/architecture requirement → its code; arrow label = role (`implements` / "
        "`tested-by`). Red = confirmed but no code linked (a gap); grey = baseline/draft, not "
        "linked yet (expected). Code-level requirements are omitted here (see the viewer).",
    "Area-level coupling: one box per area (N caps), arrow A->B = some capability in A depends on "
        "one in B. The System Map has the per-capability detail.",
    "Requirements needing attention: red = unimplemented (confirmed, no code); orange = "
        "unreviewed (promote after review); yellow = untested (implemented but no tested-by — set "
        "`test_exempt` to silence), or unverified-intent (open verify-intent question).",
]


def _build_md_text(data):  # implements: ARCH-MAPDIAGRAMS-055  # implements: REQ-MAPDIAGRAMS-874
    from datetime import datetime

    dep_count = {n["id"]: 0 for n in data["nodes"]}
    for _, b in data["edges"]:
        dep_count[b] = dep_count.get(b, 0) + 1

    diagrams = [
        ("System Map",          _mermaid_system(data)),
        ("Requirement-to-Code", _mermaid_req_to_code(data)),
        ("Dependency Map",      _mermaid_deps(data)),
        ("Risk & Unknowns",     _mermaid_risk(data)),
    ]

    lines = [
        "---",
        # The header is derived from content only. It used to carry a wall-clock
        # timestamp, which rewrote one line on every regeneration: two branches that
        # produced an identical graph still conflicted here, and the resolution was
        # always "regenerate", never "merge". Git already records when.
        "generated: {}".format(datetime.now().strftime("%Y-%m-%d")),
        "engine: {}".format(MAP_ENGINE_VERSION),
        "nodes: {}".format(len(data["nodes"])),
        "edges: {}".format(len(data["edges"])),
    ] + (["design pass-rate: {}% ({}/{} source files without a design candidate)".format(
        data["design"]["score"], data["design"]["clean_files"], data["design"]["files"])]
         if data.get("design") else []) + [
        "---",
        "",
        "# Requirement Map",
        "",
    ]
    for i, (title, diagram) in enumerate(diagrams):
        legend = _LEGEND_MD[i] if i < len(_LEGEND_MD) else ""
        lines += ["## {}".format(title), "", "_{}_".format(legend), "",
                  "```mermaid", diagram, "```", ""]

    # risk table — each flagged requirement with its scripted recommendation
    risk_rows = []
    for n in data["nodes"]:
        sigs = _risk_signals(n)
        if sigs:
            rec = " ".join(RISK_ADVICE[s] for s in sigs).replace("|", "/").replace("\n", " ")
            risk_rows.append((n["id"], n["status"],
                              len(n["members"]), dep_count.get(n["id"], 0),
                              ", ".join(sigs), rec))
    if risk_rows:
        lines += [
            "### Risk Table", "",
            "| ID | status | members | dependents | risks | recommendation |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row in risk_rows:
            lines.append("| {} | {} | {} | {} | {} | {} |".format(*row))
        lines.append("")

    return "\n".join(lines)


def render_md(data, reqs_dir):
    # implements: ARCH-MAPDIAGRAMS-055  # implements: REQ-MAPDIAGRAMS-874
    """Write `_map.md`, the four Mermaid diagrams that render without JavaScript."""
    out = os.path.join(reqs_dir, "_map.md")
    os.makedirs(reqs_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(_utf8_safe(_build_md_text(data)))
    return out
