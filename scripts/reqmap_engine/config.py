"""Tunable constants (the `_config.json` surface) and the loader that applies a repo's overrides.
Read them as `cfg.NAME` so an override made at startup is what every reader sees.
"""
import json, os, sys



CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".cpp", ".h", ".hpp",
             ".cc", ".java", ".go", ".rs", ".html", ".css", ".sql", ".yaml", ".yml",
             ".sh", ".tf",
             # schema files: a consumer tagged schema.prisma and nothing read it
             ".prisma", ".graphql", ".proto",
             # frontend run: excalidraw's ONLY stylesheet format was .scss
             ".scss", ".sass", ".less", ".vue", ".svelte", ".mjs", ".cjs", ".mts", ".cts",
             # infra/backend runs
             ".cs", ".php", ".rb", ".kt", ".kts", ".swift", ".scala", ".ex", ".exs",
             ".dart", ".toml",
             # .md scanned for tags so prose capabilities (prompts/specs) can be members
             ".md")

# A repo whose source language the default set doesn't cover can declare extra
# scannable extensions via the REQMAP_EXTRA_CODE_EXTS env var — comma-separated,
# leading dot optional (e.g. "REQMAP_EXTRA_CODE_EXTS=.foo,bar"). Merged here so
# every scan site (endswith(CODE_EXTS)) picks them up without forking the engine.
_extra_exts = tuple(
    (e if e.startswith(".") else "." + e)
    for e in (x.strip() for x in os.environ.get("REQMAP_EXTRA_CODE_EXTS", "").split(","))
    if e.strip()
)
if _extra_exts:
    CODE_EXTS = CODE_EXTS + _extra_exts
# Hierarchy breadth on the `satisfies:` graph: a parent normally carries between these many
# children. Warn-only, and silent on a leaf — a requirement nothing satisfies is not a
# malformed parent, it is simply not a parent.
LINT_FANOUT_MIN = 5
LINT_FANOUT_MAX = 20
# Per-level CEILINGS, keyed on the PARENT's `level:`. `None` means no floor at that level.
# One band for the whole hierarchy was wrong in both directions: an architecture requirement
# groups detailed design, where a dozen children is ordinary, while a system need groups
# architecture, where ten is already a lot.
#
# The floor is gone because the corpus's own shape refutes it (ADR-0023 — read it before
# restoring one). Measured at b0ce92b over the `satisfies:` graph, the old uniform band
# produced 10 findings: 7 below the floor and 3 above the ceiling. The floor is
# anti-correlated with corpus quality — several of those 7 appeared *because* commits
# e254a34 and 72213fc folded away leaves that should not have existed, dropping their
# parents from 5 children to 4. A check that gets louder as the corpus gets better is
# measuring the wrong thing. In this corpus a child count is also a CLAUSE count, since the
# `satisfies:` children were derived roughly one per Description bullet, so the floor
# measures what `ac-count-high` already measures on the other axis. And the distribution
# has no floor to find: 3:1, 4:6, 5:5, 6:8, 7:5, 8:9 is continuous. ADR-0019 pre-committed
# the response: "the band is wrong for this shape of corpus and should be widened or
# dropped — not lived with."
#
# NOTE: an earlier version of this comment claimed "a blind review confirmed 0 of 9 as
# real". That figure was withdrawn — no commit ever produced 9 FLOOR findings (4, then 6,
# then 7 as the corpus changed), and the one flag it called plausibly real, ARCH-CHECK-006,
# is a CEILING finding. The floor rests on the distribution and the anti-correlation above,
# both of which reproduce from a sha and a filter.
#
# The ceiling stays: the distribution DOES break at 19 -> 22 -> 23 -> 32, and the single
# finding above it is ARCH-CHECK-006 at 32, which is real and left standing.
# Measured after this change: 1 finding over 72 lintable requirements.
# A parent with no `level:` keeps the uniform 5-20 band — the level axis stays doubly
# opt-in (ADR-0019), so a repo that never declares it sees exactly what it saw before, and
# this corpus's evidence is not silently imposed on a corpus shaped differently.
#
# `system`'s ceiling is ten again (ADR-0025 restores the 3-tier split ADR-0024 had
# collapsed): a system need is satisfied by a handful of architecture capabilities, and
# the grouping nodes that briefly sat at `level: system` are back at `architecture`,
# whose own (None, 30) never moved.
LINT_FANOUT_BANDS = {"system": (None, 10), "architecture": (None, 30)}  # implements: REQ-FANOUT-852
# System Map declutter: hide depends_on edges into a node this many capabilities
# depend on (a hub) — the bus is hidden regardless of count. Full graph stays in
# the Dependency Map tab.
SYSTEM_HUB_FANIN = 8


DOC_BUNDLE_MIN_BYTES = 50_000   # a docs/ HTML doc this big is a generated bundle, not a stub


ORPHAN_CODE_MIN_LOC = 150   # a program file this big with no tag is a coverage hole, not a stub
DRIFT_SEVERITY = "warn"          # or "error", per repo, via `_config.json`
BUS_FANIN_THRESHOLD = 5      # a module this many capabilities depend on is bus-like
SPLIT_LOC_THRESHOLD = 300    # oversize file -> flag for human split, do not auto-split
                           # translation at once (the `translate` verb that wrote the
                           # cache was removed 2026-09-05; the reader below stays)


# The repository's declared requirements language: `en`, `ro`, or `both`. Set in
# `requirements/_config.json` as `"LANGUAGE": "ro"`. It changes what the engine EXPECTS,
# never what it writes: with `ro` or `both` a requirement without a fresh Romanian entry
# is a gap `sync` reports and `ask --i18n` lists, and the viewer opens in Romanian
# (`ro`) or offers both (`both`). The engine still translates nothing — that is
# REQ-TRANSLATE-937, and it holds because the emitter hands the source text and the
# cache key to whoever does.
LANGUAGE = "en"          # implements: REQ-TRANSLATE-996
LINT_STACKED_CONNECTORS = 3    # a normative line with this many 'and'/'or' joins (warn)
LINT_CLAUSE_SENTENCES = 3      # a Contract bullet spanning MORE sentences than this is
                               # flagged by `statement-too-long` (warn). Sentence count is
                               # the only dimension this check measures; words per clause
                               # belong to `statement-size`. A clause may hold two or three
                               # sentences — the extra ones state the first's consequence.
                               # A per-SENTENCE word ceiling was dropped on 2026-09-03: see
                               # ARCH-LINTCHECKS-025's notes for what that gave up.
LINT_STATEMENT_WORDS = 150     # a Contract CLAUSE — continuation lines joined — over this
                               # many words is reported by `statement-size`. Advisory only:
                               # ARCH-ATOMICITY-049 makes atomicity the normative rule and this
                               # threshold an explicit heuristic, so a longer clause stays valid.
LINT_AC_MIN = 3                # fewer ACs than this suggests under-specified (warn)
LEVEL_FAMILY_MIN = 3           # `clarify --levels --apply` mints one ARCH-<FAMILY>-001 capability
                               # per id-prefix family with at least this many code members;
                               # smaller families share ARCH-NEEDS-A-NAME-001 (ADR-0038)
LINT_AC_MAX = 7                # more ACs than this suggests over-scoped — split candidate (warn)
                               # `- ` facts before it is no longer one obligation (warn,
                               # 'atomic-story-overlong'); each fact under the ceiling needs
                               # its own `Then` line or 'atomic-bullet-then-mismatch' fires
LINT_CONTRACT_MAX = 10         # contract clauses over this, COMBINED with AC over LINT_AC_MAX,
                               # is the composite 'over-scoped' cohesion signal (warn)
LINT_FILE_SPREAD_MAX = 3       # implements members spanning >= this many distinct DIRECTORIES
                               # is a 'file-spread' diffuseness signal (warn) — auto-off below
                               # it; the name predates ADR-0042, which moved it off files
LINT_BUS_FANOUT_MIN = 3        # a `layer: bus` with ZERO dependents and this many dependencies


# ---------- similar (duplicate-capability detection) ----------
# Flags requirement pairs whose contracts overlap, so a human can catch a divergent
# re-implementation before it lands. Stdlib TF-IDF + cosine over the normative text
# (title + intent + Contract); Notes is excluded as too dense/noisy.
SIMILAR_THRESHOLD = 0.35       # cosine above this -> reported as a probable-duplicate pair


# ---------- design: advisory design review of the repo's code ----------
# Reads the consumer's code and names candidates against the four OOP pillars, the
# per-class C&K metrics, plus a
# few house standards. It is advice: read-only, never part of the gate, exit 0, and a
# finding asserts a SHAPE worth a look ("these six functions share five parameters"),
# never a defect. Python is read through `ast`; the brace languages (JS/TS, C/C++,
# Java, C#, Go, Rust, Kotlin, Swift, Scala, Dart, PHP) through heuristics over the
# source with comments and strings masked out — the engine ships no parser for them
# and must stay stdlib-only. Every threshold is a CONFIG_KEYS entry.
DESIGN_FUNC_MAX_LINES = 80      # abstraction: a function longer than this is a split candidate
DESIGN_NESTING_MAX = 4          # abstraction: blocks nested deeper than this
DESIGN_PARAMS_MAX = 6           # encapsulation: a parameter list longer than this wants an object
DESIGN_CLUMP_MIN = 3            # encapsulation: this many parameters travelling together ...
DESIGN_CLUMP_FUNCS = 3          # ... through this many functions is a data clump
# abstraction: top-level functions sharing a name prefix -> namespace
DESIGN_PREFIX_GROUP = 6
DESIGN_SHARED_METHODS = 3       # inheritance: unrelated classes sharing this many method names
DESIGN_ISINSTANCE_CHAIN = 3     # polymorphism: type tests on one name in one if/else-if chain
# polymorphism: `x == literal` branches (or switch cases) on one name
DESIGN_BRANCH_CHAIN = 4
DESIGN_FILE_MAX_LINES = 500     # standards: a source file longer than this
DESIGN_LINE_MAX = 100           # standards: a physical line wider than this
DESIGN_FILE_MAX_FUNCS = 30      # standards: top-level functions/classes in one file
# standards (Python): 1 = public defs/classes need a docstring, 0 = off
DESIGN_DOCSTRING_PUBLIC = 1
# Chidamber & Kemerer, per class, Python only (see `_class_metrics` for what is absent
# and why). C&K (1994) proposed the metrics and NO thresholds; these are the conventional
# textbook numbers, and there is no primary source to cite for them. Calibrated once, on
# 65 unique classes across 7 Python corpora with an independent review of every flag —
# see REQ-DESIGN-980. Retune per repo through CONFIG_KEYS like every other threshold.
DESIGN_RFC_MAX = 50             # metrics: own methods + distinct methods it calls (C&K RFC)


# Prose documents `RM035` re-measures the marked corpus counts in, relative to the scan
# root. A LIST, not a tuple, because `_config.json` hands JSON lists to `apply_config`
# and a tuple default would reject every override on a type mismatch. Set it to `[]` to
# turn the rule off outright; a file that carries no marker already costs one failed open.
DOC_CLAIM_FILES = ["CLAUDE.md"]

# The files a repository declares its version in, relative to the code root. Empty means
# probe the usual names (`versions.VERSION_FILE_CANDIDATES`); a repo whose version lives
# anywhere else names it here. A LIST for the same reason as DOC_CLAIM_FILES.
VERSION_FILES = []

# ---------- per-repo configuration ----------
# Every threshold above is a module constant, and a consumer could change none of them
# without forking the engine. `requirements/_config.json` overrides the named ones —
# read fail-open, applied once at startup, a key of the wrong type or an unknown name
# is reported and ignored. Set constants without rewiring: the circuit network.
CONFIG_FILE = "_config.json"
CONFIG_KEYS = ("LINT_AC_MIN", "LINT_AC_MAX", "LINT_STATEMENT_WORDS", "LINT_CONTRACT_MAX",
               "LINT_FILE_SPREAD_MAX", "LINT_FANOUT_MIN", "LINT_FANOUT_MAX", "LINT_FANOUT_BANDS",
               "LINT_STACKED_CONNECTORS", "LINT_CLAUSE_SENTENCES", "LINT_BUS_FANOUT_MIN",
               "SIMILAR_THRESHOLD", "ORPHAN_CODE_MIN_LOC", "DOC_BUNDLE_MIN_BYTES",
               "SYSTEM_HUB_FANIN", "BUS_FANIN_THRESHOLD", "SPLIT_LOC_THRESHOLD",
               "DESIGN_FUNC_MAX_LINES", "DESIGN_NESTING_MAX", "DESIGN_PARAMS_MAX",
               "DESIGN_CLUMP_MIN", "DESIGN_CLUMP_FUNCS", "DESIGN_PREFIX_GROUP",
               "DESIGN_SHARED_METHODS",
               "DESIGN_ISINSTANCE_CHAIN", "DESIGN_BRANCH_CHAIN", "DESIGN_FILE_MAX_LINES",
               "DESIGN_LINE_MAX", "DESIGN_FILE_MAX_FUNCS", "DESIGN_DOCSTRING_PUBLIC",
               "DESIGN_RFC_MAX", "DRIFT_SEVERITY", "LANGUAGE", "DOC_CLAIM_FILES",
               "VERSION_FILES")

# A string-valued config key names a behaviour, so its accepted spellings are declared
# here and a value outside them is reported rather than applied. Without this, a repo
# that wrote `"eror"` would get the default back in silence — precisely the failure the
# whole config mechanism exists to avoid.
CONFIG_ENUMS = {"DRIFT_SEVERITY": ("warn", "error"), "LANGUAGE": ("en", "ro", "both")}


def load_config(reqs_dir):  # implements: ARCH-CONFIG-060  # implements: REQ-CONFIG-949
    """The parsed `requirements/_config.json`, or {} when absent, unreadable or not an object."""
    try:
        with open(os.path.join(reqs_dir, CONFIG_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_config(cfg, out=None):  # implements: ARCH-CONFIG-060  # implements: REQ-CONFIG-949
    """Apply `cfg` to the module constants. Returns the names applied. A key that is
    not in CONFIG_KEYS, or whose value has a different type than the default, is
    reported on `out` (stderr) and skipped — a typo must never silently change nothing."""
    global CODE_EXTS
    out = out or sys.stderr
    applied = []
    g = globals()
    for key, value in (cfg or {}).items():
        if key == "extra_code_exts":
            if isinstance(value, list) and all(isinstance(x, str) for x in value):
                extra = tuple(x if x.startswith(".") else "." + x for x in value if x)
                CODE_EXTS = CODE_EXTS + tuple(e for e in extra if e not in CODE_EXTS)
                applied.append(key)
            else:
                print("config: ignoring extra_code_exts (expected a list of strings)", file=out)
            continue
        if key not in CONFIG_KEYS:
            print("config: ignoring unknown key {!r}".format(key), file=out)
            continue
        default = g[key]
        # A string-valued key is an ENUM, never free text: every one of them names a
        # behaviour, so an unrecognised spelling is a typo that must be reported. The
        # numeric branch below would otherwise reject strings outright and a repo
        # could never set one at all.
        if isinstance(default, str):
            allowed = CONFIG_ENUMS.get(key, ())
            if not isinstance(value, str) or (allowed and value not in allowed):
                print("config: ignoring {} (expected one of {})".format(
                    key, ", ".join(allowed) or "a string"), file=out)
                continue
            g[key] = value
            applied.append(key)
            continue
        if isinstance(default, list):
            # A list default was declared for exactly this (see DOC_CLAIM_FILES) and then
            # fell through to the numeric branch, which rejected every override.
            if not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
                print("config: ignoring {} (expected a list of strings)".format(key), file=out)
                continue
            g[key] = list(value)
            applied.append(key)
            continue
        if isinstance(default, dict):
            if not isinstance(value, dict):
                print("config: ignoring {} (expected an object)".format(key), file=out)
                continue
            merged = dict(default)
            for k, v in value.items():
                merged[k] = tuple(v) if isinstance(v, list) else v
            g[key] = merged
        elif isinstance(default, bool) or not isinstance(default, (int, float)) \
                or isinstance(value, bool) or not isinstance(value, (int, float)):
            print("config: ignoring {} (expected {})".format(key, type(default).__name__), file=out)
            continue
        else:
            g[key] = type(default)(value)
        applied.append(key)
    return applied
