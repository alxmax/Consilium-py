"""Workspace (the loaded repo), GateContext (what every rule reads), the source-repo predicate and
the test-link probe.
"""
import os, re

from .locks import load_lock
from .mapcmd import _assemble_map_data
from .model import Requirement, _as_list
from .parse import load_requirements
from .scan import scan_ac_verifies, scan_all, scan_test_levels
from .sections import binding_hash


# Unambiguous test markers, trusted in ANY file: Python `def test…(`, JS/TS
# `function test…(`, Go `func TestX/Benchmark/Example/Fuzz(`, Rust `#[test]` /
# `#[tokio::test]`. Used only to confirm a tested-by file holds tests — not to count.
# Case-insensitive for Python/JS/Rust idioms, but the Go branch stays
# case-sensitive: `go test` only runs exported TestXxx/BenchmarkXxx/ExampleXxx/
# FuzzXxx — a private `func testHelper(` is NOT a test and must not satisfy a link.
_DEF_TEST_RE = re.compile(
    r"(?i:def\s+test\w*\s*\()|(?i:function\s+test\w*\s*\()|"
    r"func\s+(?:Test|Benchmark|Example|Fuzz)\w*\s*\(|"
    r"(?i:#\[\s*(?:[\w:]+::)?test\b)")
# The bare Jest/Mocha `it(` / `test(` call is too common a word to trust in prose or
# config (e.g. "it (the parser) returns None" in a .md), so it is honored ONLY in a
# JS/TS source file, where it is a genuine test idiom.
_CALL_TEST_RE = re.compile(r"\b(?:it|test)\s*\(", re.IGNORECASE)
_CALL_TEST_EXTS = (".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs")

# A stdlib-only Python suite often exposes no `def test…` — it drives its checks from a
# runnable entry point (`run` / `run_tests` / `main`) under an `if __name__ == "__main__"`
# guard, signalling pass/fail via the process exit code. Honored ONLY for a `tested-by`
# target (the author has already declared the file a test) and ONLY in a `.py` file, so a
# non-test module that merely defines a `main()` is never mistaken for a test elsewhere.
_PY_TEST_ENTRY_RE = re.compile(r"^\s*def\s+(?:run|run_tests|main)\s*\(", re.MULTILINE)
_PY_MAIN_GUARD_RE = re.compile(r"""if\s+__name__\s*==\s*["']__main__["']""")

# A shell suite declares a test as a bash function (`test_x() {`, `function test_x {`)
# or a bats case (`@test "…" {`) — none of which match the Python/JS/Go/Rust idioms
# above, so four real bash suites warned permanently in a consumer repo. The filename
# conventions are honored too: naming a file `*.test.sh` AND tagging it `tested-by`
# are two independent declarations that it is a test.
_SH_TEST_EXTS = (".sh", ".bash", ".zsh", ".bats")
_SH_TEST_NAME_RE = re.compile(r"(?:^|[._-])test[._-]|[._-]test$|^test[._-]|^tests?$", re.I)
_SH_TEST_RE = re.compile(
    r"(?m)^\s*(?:@test\b"
    r"|(?:function\s+)?(?:test|assert|check|expect|should)[\w:.-]*\s*\(\s*\)"
    r"|function\s+(?:test|assert|check|expect|should)[\w:.-]*\b)", re.I)


def _test_link_problem(path):
    # implements: ARCH-TESTLINK-018  # implements: REQ-TESTLINK-930
    # implements: REQ-TESTLINK-931  # implements: REQ-TESTLINK-932
    """Return a short reason a `tested-by` file fails the behavior-sync check, or ''
    when it is fine. A file that is missing, unreadable, or holds no recognizable
    test function means the link asserts coverage it does not have. Deterministic
    and warn-only — it never proves per-criterion coverage, only that real tests
    exist at the link target (per-AC mapping needs a per-AC tag, deferred)."""
    if not os.path.isfile(path):
        return "does not exist (broken tested-by link)"
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            src = f.read()
    except OSError:
        return "is unreadable"
    if _DEF_TEST_RE.search(src):
        return ""
    if path.lower().endswith(_CALL_TEST_EXTS) and _CALL_TEST_RE.search(src):
        return ""
    if (path.lower().endswith(".py")
            and _PY_TEST_ENTRY_RE.search(src) and _PY_MAIN_GUARD_RE.search(src)):
        return ""
    if path.lower().endswith(_SH_TEST_EXTS):
    # implements: ARCH-TESTLINK-018  # implements: REQ-TESTLINK-932
        stem = os.path.splitext(os.path.basename(path))[0]
        if _SH_TEST_NAME_RE.search(stem) or _SH_TEST_RE.search(src):
            return ""
    return ("contains no test function "
            "(def test.../func TestX.../#[test]/it()/bash test_x()/py run|main under __main__)")


# ---------- the workspace a command runs against ----------
class Workspace(object):  # implements: ARCH-RULES-059
    """One repo, scanned once: the requirement corpus, the membership scan, the
    two roots every command resolves paths against, and the two coverage views
    the same walk produced.

    These six values are computed together in `main` and were then passed
    together to fifteen command functions, which is why `ask --design` reported
    the clump fifteen times. Naming the bundle is the whole point: a command now
    asks for the workspace it operates on, not for six positional arguments a
    caller can transpose.

    `reqs_dir` and `code_root` stay optional because two commands are defined for
    a caller that has neither: `health` skips the sections that need a code root
    rather than failing, and `next` does the same.
    """

    __slots__ = ("reqs", "members", "reqs_dir", "code_root", "ac_cover", "level_cover",
                 "_map_data")

    def __init__(self, reqs, members=None, reqs_dir=None, code_root=None,
                 ac_cover=None, level_cover=None):
        self.reqs, self.members = reqs, members
        self.reqs_dir, self.code_root = reqs_dir, code_root
        self.ac_cover, self.level_cover = ac_cover, level_cover
        self._map_data = None

    def map_data(self, root=".", members=None):
        """The assembled map document, built once per (members, root) and reused.
        `gate` asked for it twice — the RM027 freshness rule and the explicit
        `map --check` that follows — and each assembly re-ran the design review,
        the health record and the TODO parse (about a tenth of a gate's wall time)."""
        members = self.members if members is None else members
        cached = self._map_data
        if cached is None or cached[0] is not members or cached[1] != root:
            data = _assemble_map_data(self.reqs, members, self.reqs_dir, root, self.ac_cover)
            self._map_data = cached = (members, root, data)
        return cached[2]

    @classmethod
    def load(cls, reqs_dir, code_root, cache=False):
        """Parse the corpus and walk the code once — the startup path `main`
        takes before dispatching to any command."""
        members, ac_cover, level_cover = scan_all(code_root, reqs_dir, cache=cache)
        return cls(load_requirements(reqs_dir), members, reqs_dir, code_root,
                   ac_cover, level_cover)

    def levels(self):
        """The per-requirement test levels, walking for them only if the cached
        members-only scan skipped them (see `scan_all`'s docstring)."""
        if self.level_cover is None:
            self.level_cover = scan_test_levels(self.code_root, self.reqs_dir)
        return self.level_cover


# ---------- gate rules ----------
class GateContext(object):  # implements: ARCH-RULES-059  # implements: REQ-RULES-947
    """Everything a gate rule may read, computed once per run. `members` is the view
    `--since` may have narrowed; `full_members` is always the whole scan, because an
    existence check ("does an implements tag exist AT ALL") must never be answered
    from a filtered view."""
    # Set by `cmd_check` when a full scan already hashed every member; any other
    # caller of run_gate_rules leaves it None and the member-drift rule hashes
    # for itself. Defaulted here so a second caller cannot trip over its absence.
    full_member_hashes = None


    def __init__(self, ws, since=None, full_members=None, update_lock=False):
        reqs, members = ws.reqs, ws.members
        reqs_dir, code_root = ws.reqs_dir, ws.code_root
        self.ws = ws
        self.reqs = reqs
        self.members = members
        self.full_members = members if full_members is None else full_members
        self.reqs_dir, self.code_root, self.since = reqs_dir, code_root, since
        self.update_lock = update_lock
        self.cap_ids = set(reqs)
        self.ac_cover = (scan_ac_verifies(code_root, reqs_dir)
                         if ws.ac_cover is None else ws.ac_cover)
        self.level_cover = (scan_test_levels(code_root, reqs_dir)
                            if ws.level_cover is None else ws.level_cover)
        # the FULL scan, not the --since-narrowed one: whether this repo has adopted
        # `validated-against:` at all is a property of the repo, not of one diff. Read
        # narrowed, a push that happened to touch one validation file switched the rule
        # on for every OTHER need — half a pair is not a corpus-wide opt-in.
        self.any_validation = any(x[0] == "validated-against"
                                  for hits in self.full_members.values() for x in hits)
        self.satisfied_by = {rid: [] for rid in reqs}
        self.dependents = {}
        for rid, r in reqs.items():
            for up in _as_list(r["meta"].get("satisfies")):
                if up in self.satisfied_by:
                    self.satisfied_by[up].append(rid)
            for dep in _as_list(r["meta"].get("depends_on")):
                self.dependents.setdefault(dep, set()).add(rid)
        self.lock = load_lock(reqs_dir)
        self.new_lock = {rid: binding_hash(r["body"]) for rid, r in reqs.items()}
        self.source_repo = _is_source_repo(code_root)

    def req(self, rid):
        r = self.reqs[rid]
        return r if isinstance(r, Requirement) else Requirement(r)

    def in_scope(self, rid):
        """--since scoping: an already-true finding is reported only when the
        requirement's members are in the diff, or when there is no --since at all."""
        return rid in self.members or not self.since

    def roles(self, rid):
        """Tag roles a requirement carries, always over the FULL scan. A rule asks
        `--since` for its SCOPE (`in_scope`), never for its FACTS: the narrowed member
        set is missing every unchanged file, so reading a fact from it reports the
        absence of a tag that is sitting in the tree."""
        return [x[0] for x in self.full_members.get(rid, [])]


def _is_source_repo(code_root):
    """True inside the requirement-manager repository itself (the one that dogfoods
    the engine), never in a consumer: the plugin manifest and the viewer's source
    both sit under `code_root`. Rules about this repo's own artifacts key on it."""
    return (os.path.exists(os.path.join(code_root, "plugin", ".claude-plugin", "plugin.json"))
            and os.path.exists(os.path.join(code_root, "app", "src", "lib", "data.js")))
