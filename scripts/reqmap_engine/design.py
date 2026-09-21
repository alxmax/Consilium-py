"""`ask --design`: the shared vocabulary — pillars, advice, thresholds, the finding
record and the language-neutral shape/standards checks.
"""
import os, re

from . import config as cfg
from .orphans import ORPHAN_CODE_EXTS


DESIGN_PILLARS = ("encapsulation", "abstraction", "inheritance", "polymorphism",
                  "metrics", "standards")
# Printed whenever the metrics pillar renders, and when the review renders empty.
# An absent finding must never be readable as a measured pass on something that was
# never computed — that is the reassuring-wrong-count failure ADR-0016 rejected.
DESIGN_METRICS_SCOPE = (
    "metrics reads Python classes only and reports 1 of Chidamber & Kemerer's 6: RFC. "
    "WMC and LCOM1 were measured and dropped — across 65 classes in 7 corpora neither "
    "ever fired without RFC, and an independent review confirmed 0 of their flags. "
    "DIT, NOC and CBO are not measured, so silence says nothing about inheritance "
    "depth, subclass count or coupling. RFC is a proxy for a class that mixes "
    "toolchains; it over-reports routers, GUI callback classes and builder DSLs, whose "
    "call count is library calls rather than collaborators."
)
DESIGN_EXTS = ORPHAN_CODE_EXTS          # program-logic files; prose/config/styling are not reviewed
DESIGN_BRACE_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts",
                     ".vue", ".svelte", ".c", ".cc", ".cpp", ".h", ".hpp", ".java",
                     ".cs", ".go", ".rs", ".kt", ".kts", ".swift", ".scala", ".dart", ".php")
_DESIGN_ADVICE = {
    "global-state": "module state mutated from inside a function has no owner: hold it in an "
                    "object, or pass it in and return it",
    "long-parameter-list": "a parameter list this long is an object waiting to be named: group "
                           "the parameters that travel together",
    "high-response": "a class that reaches this many distinct methods is hard to test alone, "
                     "because its collaborators are part of its interface: narrow them",
    "data-clump": "the same parameters travel through several functions: make them one object "
                  "with those functions as methods",
    "long-function": "a function this long hides several steps: extract each step under a name "
                     "that says what it does",
    "deep-nesting": "nesting this deep hides the main path: return early, or extract the inner "
                    "block",
    "prefix-family": "functions sharing a prefix are a namespace: a class (or module) with that "
                     "name makes the boundary explicit",
    "shared-methods": "unrelated classes with the same method names describe one interface: name "
                      "a base class or protocol",
    "duplicate-method": "the same method body in two classes is one method: pull it up into a "
                        "shared base",
    "isinstance-chain": "a chain of type tests dispatches by hand: give each type the method and "
                        "let the call dispatch",
    "type-switch": "a chain of equality tests on one value is a dispatch table: a dict of "
                   "handlers, or a method per case",
    "file-too-long": "a file this long is several modules sharing a name: split it along the "
                     "prefix families it already shows",
    "line-too-long": "lines wider than the limit hide their tail in every diff and side-by-side "
                     "view: wrap them",
    "missing-docstring": "a public name without a docstring makes every caller read the body: one "
                         "sentence saying what it returns is enough",
    "too-many-definitions": "this many top-level definitions in one file is a package, not a "
                            "module: group them",
}
_DESIGN_PILLAR_OF = {
    "global-state": "encapsulation", "long-parameter-list": "encapsulation",
    "data-clump": "encapsulation",
    "high-response": "metrics",
    "long-function": "abstraction", "deep-nesting": "abstraction", "prefix-family": "abstraction",
    "shared-methods": "inheritance", "duplicate-method": "inheritance",
    "isinstance-chain": "polymorphism", "type-switch": "polymorphism",
    "file-too-long": "standards", "line-too-long": "standards",
    "missing-docstring": "standards", "too-many-definitions": "standards",
}


def _design_finding(kind, rel, line, name, detail):  # implements: ARCH-DESIGN-061
    return {"pillar": _DESIGN_PILLAR_OF[kind], "kind": kind, "file": rel, "line": line,
            "name": name, "detail": detail, "advice": _DESIGN_ADVICE[kind]}


def _design_prefix(name):
    """The family token of a function name: `_scan_tags` -> `scan`, `scanTags` -> `scan`."""
    core = name.strip("_")
    if "_" in core:
        return core.split("_", 1)[0]
    m = re.match(r"[a-z]{3,}(?=[A-Z])", core)
    return m.group(0) if m else ""


# ---- shared shape checks over abstract "function" and "class" records, so the Python
# and the brace analyzers report the same kinds with the same thresholds.
# fn record: {name, line, n_lines, depth, params:[names], top:bool}
# class record: {name, line, bases:set, methods:{name: body_key}}
def _design_shape_findings(rel, fns, classes):
    # implements: REQ-DESIGN-950  # implements: REQ-DESIGN-951
    out = []
    for f in fns:
        if len(f["params"]) > cfg.DESIGN_PARAMS_MAX:
            out.append(_design_finding("long-parameter-list", rel, f["line"], f["name"],
                                       "`{}` takes {} parameters (over {})".format(
                                           f["name"], len(f["params"]), cfg.DESIGN_PARAMS_MAX)))
        if f["n_lines"] > cfg.DESIGN_FUNC_MAX_LINES:
            out.append(_design_finding("long-function", rel, f["line"], f["name"],
                                       "`{}` is {} lines (over {})".format(
                                           f["name"], f["n_lines"], cfg.DESIGN_FUNC_MAX_LINES)))
        if f["depth"] > cfg.DESIGN_NESTING_MAX:
            out.append(_design_finding("deep-nesting", rel, f["line"], f["name"],
                                       "`{}` nests {} levels deep (over {})".format(
                                           f["name"], f["depth"], cfg.DESIGN_NESTING_MAX)))
    seen = set()
    plist = [(f, frozenset(f["params"])) for f in fns]
    for i in range(len(plist)):
        for j in range(i + 1, len(plist)):
            common = plist[i][1] & plist[j][1]
            if len(common) < cfg.DESIGN_CLUMP_MIN or common in seen:
                continue
            carriers = [f for f, ps in plist if common <= ps]
            if len(carriers) >= cfg.DESIGN_CLUMP_FUNCS:
                seen.add(common)
                first = min(carriers, key=lambda f: f["line"])
                out.append(_design_finding("data-clump", rel, first["line"], first["name"],
                                           "{} travel together through {} functions: {}".format(
                                               ", ".join(sorted(common)), len(carriers),
                                               ", ".join(sorted(f["name"] for f in carriers)[:6]))))
    families = {}
    for f in fns:
        if f["top"]:
            p = _design_prefix(f["name"])
            if p:
                families.setdefault(p, []).append(f)
    for prefix, group in sorted(families.items()):
        if len(group) >= cfg.DESIGN_PREFIX_GROUP:
            first = min(group, key=lambda f: f["line"])
            names = ", ".join(sorted(f["name"] for f in group)[:6])
            out.append(_design_finding("prefix-family", rel, first["line"], prefix,
                                       "{} top-level functions start with `{}`: {}".format(
                                           len(group), prefix, names)))
    for i in range(len(classes)):
        for j in range(i + 1, len(classes)):
            a, b = classes[i], classes[j]
            if a["bases"] & b["bases"] or a["name"] in b["bases"] or b["name"] in a["bases"]:
                continue
            shared = sorted(n for n in a["methods"] if n in b["methods"] and not n.startswith("__"))
            if len(shared) >= cfg.DESIGN_SHARED_METHODS:
                pair = "{}/{}".format(a["name"], b["name"])
                out.append(_design_finding("shared-methods", rel, a["line"], pair,
                                           "`{}` and `{}` share {} method names with no common "
                                           "base: {}".format(a["name"], b["name"], len(shared),
                                                              ", ".join(shared[:6]))))
            for n in shared:
                if a["methods"][n] == b["methods"][n]:
                    dup = "{}.{}".format(b["name"], n)
                    out.append(_design_finding("duplicate-method", rel, b["line"], dup,
                                               "`{}.{}` is byte-for-byte `{}.{}`".format(
                                                   b["name"], n, a["name"], n)))
    return out


def _design_chain_findings(rel, chains):  # implements: REQ-DESIGN-951
    """chains: [(line, [(kind, name), ...])] where kind is 'type' or 'eq'."""
    out = []
    for line, tests in chains:
        for kind, floor, label in (("type", cfg.DESIGN_ISINSTANCE_CHAIN, "isinstance-chain"),
                                   ("eq", cfg.DESIGN_BRANCH_CHAIN, "type-switch")):
            names = [n for k, n in tests if k == kind]
            for name in sorted(set(names)):
                if names.count(name) >= floor:
                    out.append(_design_finding(label, rel, line, name,
                                               "{} branches test `{}` in one chain".format(
                                                   names.count(name), name)))
    return out


def _design_standards(rel, src, n_top, undocumented):  # implements: REQ-DESIGN-953
    out = []
    lines = src.split("\n")
    base = os.path.basename(rel)
    if len(lines) > cfg.DESIGN_FILE_MAX_LINES:
        out.append(_design_finding("file-too-long", rel, 1, base,
                                   "{} lines (over {})".format(len(lines),
                                                               cfg.DESIGN_FILE_MAX_LINES)))
    wide = [i for i, l in enumerate(lines, 1) if len(l.rstrip("\r")) > cfg.DESIGN_LINE_MAX]
    if wide:
        out.append(_design_finding("line-too-long", rel, wide[0], base,
                                   "{} line(s) wider than {} columns, first at line {}".format(
                                       len(wide), cfg.DESIGN_LINE_MAX, wide[0])))
    if n_top > cfg.DESIGN_FILE_MAX_FUNCS:
        out.append(_design_finding("too-many-definitions", rel, 1, base,
                                   "{} top-level definitions (over {})".format(
                                       n_top, cfg.DESIGN_FILE_MAX_FUNCS)))
    if cfg.DESIGN_DOCSTRING_PUBLIC and undocumented:
        names = ", ".join(n for n, _l in undocumented[:6])
        out.append(_design_finding("missing-docstring", rel, undocumented[0][1], undocumented[0][0],
                                   "{} public definition(s) without a docstring: {}".format(
                                       len(undocumented), names)))
    return out
