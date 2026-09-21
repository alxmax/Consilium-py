"""`ask --design`, Python side: ast-driven shape, fields, cohesion and metrics."""
import ast

from . import config as cfg
from .design import (
    _design_chain_findings, _design_finding, _design_shape_findings, _design_standards
)


# ---- Python, through ast
def _param_names_of(fn):
    a = fn.args
    return [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs if x.arg not in ("self", "cls")]


_DESIGN_NESTING_NODES = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor, ast.AsyncWith)
_DESIGN_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _nesting_depth(node, depth=0):
    """Deepest block nesting under `node`. Iterative on purpose: a generated
    1,000-term expression or a 1,000-branch `elif` chain parses fine but sits deeper
    than the interpreter's recursion limit, and a RecursionError here escaped every
    handler and killed `gate` and `sync` (advisory pass, fatal exit)."""
    best, stack = depth, [(node, depth)]
    while stack:
        n, d = stack.pop()
        for child in ast.iter_child_nodes(n):
            if isinstance(child, _DESIGN_NESTING_NODES):
                best = max(best, d + 1)
                stack.append((child, d + 1))
            elif not isinstance(child, _DESIGN_SCOPE_NODES):
                stack.append((child, d))
    return best


def _branch_test_kind(test):
    """('type', name) for isinstance(name, ...), ('eq', name) for name == <constant>, else None."""
    if (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
            and test.func.id == "isinstance"
            and test.args and isinstance(test.args[0], ast.Name)):
        return ("type", test.args[0].id)
    if (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.left, ast.Name) and isinstance(test.comparators[0], ast.Constant)):
        return ("eq", test.left.id)
    return None


def _class_fields(cls):  # implements: REQ-DESIGN-978
    """The class's real instance fields: every name assigned through `self.<name>`,
    plus whatever `__slots__` declares. Only these count as state — a class whose
    state lives somewhere else (a `dict` subclass keys its own data) has no field for
    two methods to share, and is skipped rather than scored as maximally incohesive."""
    out = set()
    for n in ast.walk(cls):
        targets = []
        if isinstance(n, ast.Assign):
            targets = list(n.targets)
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            targets = [n.target]
        for t in targets:
            if isinstance(t, ast.Tuple):
                targets.extend(t.elts)
            elif (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                    and t.value.id == "self"):
                out.add(t.attr)
    for st in cls.body:
        # A declarative class names its state in the class body instead of assigning it:
        # `@dataclass`, attrs and Pydantic all write `name: type`, and the assignment
        # this function looks for happens in an __init__ that is synthesised at runtime
        # and never appears in the tree. Without this branch cohesion was skipped in
        # silence for the commonest class shape in modern Python — and the skip was
        # indistinguishable from a class measured and found cohesive.
        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            out.add(st.target.id)
        if not (isinstance(st, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__slots__" for t in st.targets)):
            continue
        if isinstance(st.value, (ast.Tuple, ast.List)):
            out |= {e.value for e in st.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return out


def _lcom(methods, fields):  # implements: REQ-DESIGN-980
    """LCOM1 over the methods that actually touch state: pairs sharing no instance
    field, minus the pairs that share one, floored at zero.

    Methods that touch no field at all are excluded, not counted as disjoint from
    everything. A pure helper has no state to share, so pairing it with every other
    method measures nothing about how the class is split — it just adds one pair per
    sibling. An independent review found this dominating the score on two builder
    classes, and six field-less helpers on a one-field class scoring 26 against a
    threshold of 20 with no split anywhere in the class."""
    touched = []
    for m in methods:
        fs = {n.attr for n in ast.walk(m)
              if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
              and n.value.id == "self" and n.attr in fields}
        if fs:
            touched.append(fs)
    apart = together = 0
    for i in range(len(touched)):
        for j in range(i + 1, len(touched)):
            if touched[i] & touched[j]:
                together += 1
            else:
                apart += 1
    return max(0, apart - together)


def _cohesion_skipped(tree):  # implements: REQ-DESIGN-979
    """How many classes in this tree have two or more methods but no field the engine
    can see, so their cohesion was not measured.

    Reported rather than inferred: a class keeping its state somewhere `ast` cannot
    follow (a `dict` subclass, `setattr`, a metaclass) yields no `low-field-sharing`
    candidate, and an absent candidate is otherwise indistinguishable from a measured
    pass."""
    n = 0
    for cls in [x for x in ast.walk(tree) if isinstance(x, ast.ClassDef)]:
        methods = [m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(methods) >= 2 and not _class_fields(cls):
            n += 1
    return n


def _class_metrics(rel, tree):  # implements: ARCH-DESIGN-061  # implements: REQ-DESIGN-978
    """Chidamber & Kemerer per class, for the three of the six that say something here.

    WMC (methods), RFC (own methods plus the distinct methods they call) and LCOM1
    (methods sharing no field) each name a shape the function-level checks cannot see:
    they measure a CLASS, where everything else in this review measures a function or a
    file. DIT and NOC are left out because they measure an inheritance tree, and a repo
    that composes instead of subclassing has none to measure — they would report zero
    forever and teach a reader to ignore the pillar. CBO is left out because resolving
    which class a Python name refers to needs type inference this engine does not do,
    and a coupling number that is wrong is worse than no coupling number.

    Python only: these count methods and field access, which the brace-language
    heuristics cannot identify without parsing. `cmd_design` therefore prints what this
    pillar did NOT measure whenever it renders — an empty Metrics block on a
    subclass-heavy repo would otherwise read as "your classes are fine" when it means
    "the two metrics that would have spoken were never computed"."""
    out = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        methods = [m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not methods:
            continue
        called = set()
        for m in methods:
            for n in ast.walk(m):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if nm:
                    called.add(nm)
        rfc = len(methods) + len(called)
        if rfc > cfg.DESIGN_RFC_MAX:
            out.append(_design_finding("high-response", rel, cls.lineno, cls.name,
                                       "`{}` reaches {} methods (over {}): {} of its own "
                                       "plus {} it calls".format(cls.name, rfc, cfg.DESIGN_RFC_MAX,
                                                                 len(methods), len(called))))
    return out


def _cohesion_skipped_in(src):  # implements: REQ-DESIGN-979
    """The skipped-cohesion count for one file's source, 0 when it does not parse."""
    try:
        return _cohesion_skipped(ast.parse(src))
    except (SyntaxError, ValueError):
        return 0


def _python_findings(rel, src):  # implements: REQ-DESIGN-950  # implements: REQ-DESIGN-951
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    out = []
    top = {id(n) for n in tree.body}
    fns, classes = [], []
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = sorted({g for s in ast.walk(n) if isinstance(s, ast.Global) for g in s.names})
            if names:
                out.append(_design_finding("global-state", rel, n.lineno, n.name,
                                           "`{}` writes module state: {}".format(
                                               n.name, ", ".join(names))))
            end = getattr(n, "end_lineno", None) or n.lineno
            fns.append({"name": n.name, "line": n.lineno, "n_lines": end - n.lineno + 1,
                        "depth": _nesting_depth(n), "params": _param_names_of(n),
                        "top": id(n) in top})
        elif isinstance(n, ast.ClassDef):
            bases = {b.id if isinstance(b, ast.Name) else ast.dump(b) for b in n.bases}
            classes.append({"name": n.name, "line": n.lineno, "bases": bases,
                            "methods": {m.name: ast.dump(m) for m in n.body
                                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}})
    out += _design_shape_findings(rel, fns, classes)
    out += _class_metrics(rel, tree)
    chains, seen = [], set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.If) or id(n) in seen:
            continue
        tests, node = [], n
        while isinstance(node, ast.If):
            seen.add(id(node))
            t = _branch_test_kind(node.test)
            if t:
                tests.append(t)
            is_elif = len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
            node = node.orelse[0] if is_elif else None
        chains.append((n.lineno, tests))
    out += _design_chain_findings(rel, chains)
    defs = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    undocumented = [(n.name, n.lineno) for n in defs
                    if not n.name.startswith("_") and not ast.get_docstring(n)]
    return out + _design_standards(rel, src, len(defs), undocumented)
