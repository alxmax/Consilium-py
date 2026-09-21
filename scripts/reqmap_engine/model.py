"""Corpus vocabulary (statuses, layers, levels) and the record types the rules read: Requirement,
Finding, Rule, plus the GATE_RULES registry.
"""
import re



VALID_STATUS = {"draft", "baseline", "in-progress", "implemented", "confirmed", "deprecated"}
# 'need'      = an upstream stakeholder need, satisfied-by (not implemented-by)
# 'aggregate' = a requirement whose implementation IS its dependencies' — it adds no
#               behavior of its own, it asserts that N capabilities work together
#               (an MVP acceptance requirement is the archetype). Covered by its
#               depends_on edges, the mirror of how a need is covered by satisfies.
VALID_LAYER = {"bus", "feature", "need", "aggregate"}
# The V-model specification level, an axis ORTHOGONAL to `layer:` and deliberately not a
# rename of it. `layer:` says how a requirement sits in the dependency graph (a `bus` is
# defined by fan-in; a `need`/`aggregate` is covered by an edge instead of a tag, which is
# what IMPL_EXEMPT_LAYERS keys on). `level:` says how abstract it is. They are independent:
# an `architecture` requirement OWNS code, so it must stay gate-checked, whereas `aggregate`
# is exempt precisely because it owns none — which is why `architecture` cannot be an alias
# of `aggregate`. Optional and absent by default: a corpus that never adopts it behaves
# exactly as before.
VALID_LEVEL = {"system", "architecture", "code"}   # implements: ARCH-LEVEL-051
# The rungs of the V: the verification level that discharges each specification level.
# Left arm `level:` <-> right arm `tested-by: <ID> @<level>`. Read only when the author has
# declared BOTH sides — a requirement with no `level:`, or with no levelled test link, is
# never judged, so the rule is silent on arrival in every existing corpus.
LEVEL_TEST_PAIR = {"system": "system", "architecture": "integration", "code": "unit"}
# roadmap milestone shape: v1, v1.0, v1.14 — validated (warn) in the gate
MILESTONE_RE = re.compile(r"^v\d+(\.\d+)*$")
ENFORCED = {"in-progress", "implemented", "confirmed"}

# Scripted, deterministic guidance per risk signal — surfaced in the Risk tab,
# the detail panel, and the _map.md risk table so a flagged requirement comes
# with a concrete next action, not just a color.
RISK_ADVICE = {
    "unimplemented": "Confirmed but no code linked: tag the implementing code "
                     "`# implements: <ID>`, or drop status back to in-progress/draft "
                     "until it is built. A confirmed requirement must point to code.",
    "unreviewed": "Draft/baseline, not yet validated: review the contract, wire its "
                  "`tested-by` tests, then promote to `confirmed`. Until then it is "
                  "tracked, not enforced.",
    "untested": "Implemented but no `tested-by` member: write an acceptance test and tag "
                "it `# tested-by: <ID>`, or set `test_exempt: <reason>` in the frontmatter "
                "to acknowledge it intentionally and silence this signal.",
    "unverified-intent": "Has open `## Verify intent` question(s): run "
                         "`reqmap.py sync`, resolve each in `requirements/_findings.md`, "
                         "then fold the answer into the Contract or delete the bullet.",
}


# ---------- core types: the records every command reads ----------
# The engine passed bare dicts around for its whole life: a requirement was
# {"meta", "body", "path", "block"}, a gate finding was a formatted string. Every
# caller then re-derived the same facts its own way — which is how `gate`, `health`,
# `next` and `confirm` came to disagree about who is exempt (ADR-0015) and which
# requirement is oversize (v3.1.0). These two classes are dict subclasses on purpose:
# every existing `r["meta"]` and `f["check"]` keeps working, and the derived facts
# gain exactly one home.
class Requirement(dict):  # implements: ARCH-PARSE-001
    """One requirement block as loaded from disk. Behaves as the dict it always was
    (`r["meta"]`, `r["body"]`, `r["path"]`, `r["block"]`) and adds the facts every
    rule used to recompute from `meta` by hand."""
    __slots__ = ()

    @property
    def meta(self):
        return self.get("meta") or {}

    @property
    def body(self):
        return self.get("body", "")

    @property
    def id(self):
        return self.meta.get("id")

    @property
    def status(self):
        return self.meta.get("status")

    @property
    def layer(self):
        return self.meta.get("layer")

    @property
    def level(self):
        return self.meta.get("level")

    @property
    def enforced(self):
        return self.status in ENFORCED

    @property
    def confirmed(self):
        return self.status == "confirmed"

    @property
    def impl_exempt(self):
        return _impl_exempt(self.meta)

    def list(self, key):
        """A frontmatter field as a list (`depends_on`, `satisfies`, `lint_exempt`...)."""
        return _as_list(self.meta.get(key))

    def exempt_from(self, rule_id):
        """True when `gate_exempt:` names this rule's code (`gate_exempt: [RM016]`)."""
        return rule_id in set(self.list("gate_exempt"))


class Finding(dict):  # implements: ARCH-RULES-059  # implements: REQ-RULES-948
    """One gate finding: `rule` (RMnnn), `severity` (error|warn), `rid` (or None for a
    corpus-wide finding) and `msg` — the exact text the gate printed before findings
    had a shape. `str(f)` is that text; the code goes in front of it on the printed
    line and travels as its own key in `--json`."""
    __slots__ = ()

    def __init__(self, rule, severity, rid, msg):
        super().__init__(rule=rule, severity=severity, rid=rid, msg=msg)

    def __str__(self):
        return self["msg"]


class Rule(object):  # implements: ARCH-RULES-059
    """A gate rule: a stable code, a default severity, whether `--strict` promotes it
    to an error, and the function that yields `(rid, msg)` pairs over a GateContext.
    `only_source_repo` marks a rule about this repository's own dogfooding (the
    viewer's baked fixture) — it never runs inside a consumer repo."""
    __slots__ = ("id", "severity", "strict", "fn", "only_source_repo")

    def __init__(self, id, severity, strict, fn, only_source_repo=False):
        self.id, self.severity, self.strict, self.fn = id, severity, strict, fn
        self.only_source_repo = only_source_repo


GATE_RULES = []   # the bus: every consumer of "what is wrong with this corpus" reads it


def gate_rule(rule_id, severity, strict=False, only_source_repo=False):
    # implements: ARCH-RULES-059  # implements: REQ-RULES-947
    """Register a gate rule. Codes are permanent identifiers (a consumer writes
    `gate_exempt: [RM016]`), so a retired rule's number is never reused."""
    def wrap(fn):
        if any(r.id == rule_id for r in GATE_RULES):
            raise ValueError("duplicate gate rule id " + rule_id)
        GATE_RULES.append(Rule(rule_id, severity, strict, fn, only_source_repo))
        return fn
    return wrap


def gate_rule_by_id(rule_id):
    """The registered rule with this code, or None — how a caller resolves the
    `RMnnn` in a finding back to the rule that produced it."""
    for r in GATE_RULES:
        if r.id == rule_id:
            return r
    return None


# ---------- parsing ----------
def _as_list(v):  # implements: ARCH-PARSE-001
    """Coerce a frontmatter value to a list: lists pass through, a bare scalar
    becomes a one-element list, empty/None becomes []. Guards callers that
    iterate list-valued keys (e.g. depends_on) against a string written without
    brackets being walked character-by-character."""
    if isinstance(v, list):
        return v
    return [v] if v else []


# A requirement whose implementation is not its own code. Both layers are covered by
# an EDGE instead of an `implements:` tag: a `need` by the `satisfies:` edges pointing
# up at it, an `aggregate` by its own `depends_on` edges pointing down.
IMPL_EXEMPT_LAYERS = ("need", "aggregate")


def _impl_exempt(meta):  # implements: ARCH-TRACE-020  # implements: REQ-TRACE-935
    """True when a requirement is exempt from the "confirmed code must exist" rule.

    One predicate, three callers (gate link-sync, `health`, the risk signals). They
    disagreed before, when `confirm` was a verb and a fourth caller: it alone did not
    exempt `layer: need`, so the layer's own reference case could not be promoted by
    the command that existed to promote it. `confirm` was removed in v5.0.0; the
    exemption it granted is now guarded by RM031 instead."""
    return (meta or {}).get("layer") in IMPL_EXEMPT_LAYERS


def _dependency_cycles(reqs):  # implements: ARCH-CHECK-006
    """Every `depends_on` cycle in the registry, as a list of id lists, each ending
    where it began (`A, B, C, A`). Deterministic: nodes and edges are walked in
    sorted order, so the same corpus always reports the same cycles in the same
    shape.

    A cycle means the layering claim is false — no requirement in it can be built
    before the others — and nothing looked for one. It surfaced as a rendering
    artifact instead: the viewer ranks by longest path, which never converges on a
    cycle, so a 59-requirement corpus with three cycles laid out 236 columns wide
    and drew its edges as endless horizontal lines. That is the symptom; this is
    the cause, and it belongs in the gate's report, not in a diagram."""
    adj = {rid: [d for d in sorted(_as_list(r["meta"].get("depends_on"))) if d in reqs]
           for rid, r in reqs.items()}
    state, stack, cycles, seen = {}, [], [], set()
    for root in sorted(adj):
        if state.get(root):
            continue
        # iterative DFS — a deep chain must not hit the interpreter's recursion limit
        work = [(root, iter(adj[root]))]
        state[root] = 1
        stack.append(root)
        while work:
            node, it = work[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                work.pop()
                continue
            if state.get(nxt) == 1:                      # closes a cycle
                cyc = stack[stack.index(nxt):] + [nxt]
                key = frozenset(cyc)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cyc)
            elif state.get(nxt) != 2:
                state[nxt] = 1
                stack.append(nxt)
                work.append((nxt, iter(adj[nxt])))
    return cycles


def _area_of(rid):  # implements: ARCH-MAP-007
    """Capability 'area' = the first id segment (BUS-PATHS-001 -> BUS). Used to
    cluster a large System Map into per-area subgraphs so 40+ nodes stay legible."""
    return rid.split("-", 1)[0] or rid
