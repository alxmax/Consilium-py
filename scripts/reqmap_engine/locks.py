"""The committed baselines: _reqlock, _memberlock, the drift log, the clarify lock, member hashes
and the engine-staleness probe.
"""
import ast, hashlib, json, os, re

from . import MAP_ENGINE_VERSION
from .git import _git
from .sections import binding_hash


def lock_path(reqs_dir):  # implements: ARCH-DRIFT-003  # implements: REQ-DRIFT-842
    """The path of the drift baseline, `requirements/_reqlock.json`."""
    return os.path.join(reqs_dir, "_reqlock.json")


def load_lock(reqs_dir):  # implements: ARCH-DRIFT-003  # implements: REQ-DRIFT-842
    """The drift baseline as `{id: hash}`, or an empty dict when it is missing or
    unreadable — a corpus with no lock yet must still gate."""
    p = lock_path(reqs_dir)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            # a valid-JSON-but-non-object lock ([], null, 42) must also fail open —
            # consumers call lock.get(rid); fail open like load_memberlock/_load_scancache
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            # empty / corrupt / merge-conflicted / non-UTF-8 lock: treat as no lock.
            # ValueError covers both json.JSONDecodeError and UnicodeDecodeError, so
            # a binary-garbage lock fails open here instead of crashing the gate.
            return {}
    return {}


def save_lock(reqs_dir, lock):  # implements: ARCH-DRIFT-003  # implements: REQ-DRIFT-842
    """Write the drift baseline, creating the directory if needed."""
    os.makedirs(reqs_dir, exist_ok=True)
    with open(lock_path(reqs_dir), "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, sort_keys=True)


# ---------- member-hash drift (reverse direction) ----------
# _reqlock.json keeps ONE hash per requirement = the contract; drift in that file only
# fires prose-ahead-of-code. The reverse — a MEMBER's content changed while the contract
# stayed put (behaviour shipped, spec not updated) — is invisible there. Member hashes
# live in a SEPARATE, versioned sidecar so _reqlock.json stays a byte-stable cross-repo
# contract: an older seeded engine never reads _memberlock.json and is wholly unaffected.
MEMBERLOCK_SCHEMA = 2   # 2: keys may be `file#definition`, not only `file`
MEMBER_ROLES = ("implements", "generated-from")   # roles that bind code/doc content to a contract


def _memberlock_path(reqs_dir):
    # implements: ARCH-MEMBERDRIFT-027  # implements: REQ-MEMBERDRIFT-879
    return os.path.join(reqs_dir, "_memberlock.json")


def load_memberlock(reqs_dir):
    # implements: ARCH-MEMBERDRIFT-027  # implements: REQ-MEMBERDRIFT-879
    """Return {rid: {relfile: sha}} from the sidecar, or {} when absent/corrupt or
    written by a NEWER schema than this engine knows — fail open (no false drift) the
    same way load_lock and the scan cache do, so a forward-incompatible sidecar degrades
    to 'reverse-drift off this run' rather than crashing or mis-comparing."""
    try:
        with open(_memberlock_path(reqs_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("_schema") != MEMBERLOCK_SCHEMA:
        return {}
    members = data.get("members")
    return members if isinstance(members, dict) else {}


def save_memberlock(reqs_dir, member_hashes):
    # implements: ARCH-MEMBERDRIFT-027  # implements: REQ-MEMBERDRIFT-879
    """Write the member-hash sidecar for reverse-direction drift, versioned by
    `_schema` and kept out of `_reqlock.json` so that file stays a byte-stable
    cross-repo contract an older seeded engine still reads."""
    os.makedirs(reqs_dir, exist_ok=True)
    payload = {"_schema": MEMBERLOCK_SCHEMA, "members": member_hashes}
    with open(_memberlock_path(reqs_dir), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


DRIFTLOG_SCHEMA = 1


def _driftlog_path(reqs_dir):  # implements: REQ-DRIFT-988
    return os.path.join(reqs_dir, "_driftlog.json")


def load_driftlog(reqs_dir):  # implements: REQ-DRIFT-988
    """Return {rid: {"hash": ..., "reason": ...}} for every contract whose drift was
    accepted, or {} when absent/corrupt or written by a NEWER schema — fail open like
    the other sidecars, so a forward-incompatible file degrades to 'no reasons on
    record' rather than crashing a gate."""
    try:
        with open(_driftlog_path(reqs_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    schema = data.get("_schema", 0) if isinstance(data, dict) else None
    if not isinstance(schema, int) or schema > DRIFTLOG_SCHEMA:
        return {}
    got = data.get("accepted")
    return got if isinstance(got, dict) else {}


def save_driftlog(reqs_dir, accepted):  # implements: REQ-DRIFT-988
    """Write the accepted-drift record, versioned by `_schema` and kept OUT of
    `_reqlock.json` — that file is the byte-stable cross-repo contract an older seeded
    engine still reads (ADR-0003), so nothing new may be added to it."""
    os.makedirs(reqs_dir, exist_ok=True)
    payload = {"_schema": DRIFTLOG_SCHEMA, "accepted": accepted}
    with open(_driftlog_path(reqs_dir), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def record_accepted_drift(reqs_dir, accepted_ids, new_lock, reason,
                          live_ids):  # implements: ARCH-DRIFT-003  # implements: REQ-DRIFT-988
    """Record who waived the drift check and why, where a reviewer reads it: the diff.

    `--accept-drift` advances the baseline on a contract nobody re-validated. That is
    the one escape hatch in the gate, and until now it left no trace at all — the lock
    hash moved and the reason lived in someone's head. The record is a file, not a log
    line, precisely so it shows up in the pull request beside the hash it excuses.

    A bare `--accept-drift` still works and is still recorded, with `reason: null`:
    silence is a legible answer, and hiding it would make the unexplained waiver the
    invisible one. Entries for requirements that have left the corpus are dropped, the
    same way the lock prunes its own."""
    if not accepted_ids:
        return {}
    log = {rid: e for rid, e in load_driftlog(reqs_dir).items()
           if rid in live_ids and isinstance(e, dict)}
    for rid in accepted_ids:
        log[rid] = {"hash": new_lock.get(rid), "reason": reason}
    save_driftlog(reqs_dir, log)
    return log


CLARIFYLOCK_SCHEMA = 1


def _clarifylock_path(reqs_dir):  # implements: REQ-CLARIFY-975
    return os.path.join(reqs_dir, "_clarifylock.json")


def load_clarifylock(reqs_dir):  # implements: REQ-CLARIFY-975
    """Return {rid: [rule, ...]} of the blocking questions each requirement had at the
    last sync, or {} when absent/corrupt or written by a NEWER schema — fail open, the
    same way the other sidecars do, so a forward-incompatible file degrades to
    'everything looks new' rather than crashing."""
    try:
        with open(_clarifylock_path(reqs_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    schema = data.get("_schema", 0) if isinstance(data, dict) else None
    if not isinstance(schema, int) or schema > CLARIFYLOCK_SCHEMA:
        return {}   # fail-open like the other sidecars — a hand-edited `"1"` was a TypeError
    got = data.get("questions")
    return got if isinstance(got, dict) else {}


def save_clarifylock(reqs_dir, snapshot):  # implements: REQ-CLARIFY-975
    """Write the `clarify` answer snapshot, versioned by `_schema`."""
    os.makedirs(reqs_dir, exist_ok=True)
    payload = {"_schema": CLARIFYLOCK_SCHEMA, "questions": snapshot}
    with open(_clarifylock_path(reqs_dir), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def untracked_locks(reqs_dir):  # implements: ARCH-CHECK-006  # implements: REQ-CHECK-830
    """Lock sidecars (`_reqlock.json`, `_memberlock.json`) are committed-by-design: an
    uncommitted one silently disables drift detection on a fresh CI checkout (no baseline
    to compare against). Return the paths of any that exist on disk but are NOT git-tracked.
    Fail-open: returns [] when git is unavailable or the tree is not a work tree, so the
    gate never breaks on a non-git consumer — the same discipline the map's git-derived
    `repo` field uses."""
    paths = [p for p in (lock_path(reqs_dir), _memberlock_path(reqs_dir)) if os.path.isfile(p)]
    if not paths:
        return []
    root = os.path.dirname(os.path.abspath(reqs_dir)) or "."
    inside = _git(["-C", root, "rev-parse", "--is-inside-work-tree"], timeout=3)
    if (inside or "").strip() != "true":
        return []
    return [p for p in paths
            if _git(["-C", root, "ls-files", "--error-unmatch", os.path.abspath(p)],
                    timeout=3) is None]


def _file_sha(path):  # implements: ARCH-MEMBERDRIFT-027
    """SHA-256 of a member file with line endings normalized to LF, so the hash is identical
    whether the tree was checked out LF (Linux/CI) or CRLF (Windows core.autocrlf=true).
    Without this, a lock generated on one platform shows spurious whole-repo member drift on
    the other — under `gate --strict` that turns every member into a false error. Mirrors the
    contract hash, which is already LF-normalized via the text-mode body parse."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _py_def_spans(path):  # implements: ARCH-MEMBERDRIFT-027  # implements: REQ-MEMBERDRIFT-982
    """`[(first_line, last_line, name)]` for the top-level definitions of a Python file,
    or None when it is not Python or does not parse. Nesting is deliberately not
    descended: a tag inside a method belongs to the class a reader opens, and per-method
    spans would split one contract's implementation across several keys."""
    if not path.lower().endswith(".py"):
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return None
    return [(n.lineno, getattr(n, "end_lineno", n.lineno), n.name) for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]


def _span_sha(path, lo, hi):  # implements: REQ-MEMBERDRIFT-982
    """SHA-256 of one line span, LF-normalized exactly as `_file_sha` normalizes a whole
    file — for the same reason: a CRLF checkout must not read as drift."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    lines = data.split(b"\n")
    return hashlib.sha256(b"\n".join(lines[lo - 1:hi])).hexdigest()


def _member_span_key(spans, fp, ln, path):
    # implements: ARCH-MEMBERDRIFT-027  # implements: REQ-MEMBERDRIFT-879
    """(key, span) for one tag hit: `fp#name` / (path, lo, hi) when `ln` falls inside a
    top-level definition span, else the whole-file key `fp` with span None."""
    if spans:
        for lo, hi, name in spans:
            if lo <= ln <= hi:
                return "{}#{}".format(fp, name), (path, lo, hi)
    return fp, None


def compute_member_hashes(code_root, members):
    # implements: ARCH-MEMBERDRIFT-027  # implements: REQ-MEMBERDRIFT-879
    """`{rid: {key: sha}}` for the members one requirement owns alone, where a key is
    `relfile#definition` for a tag inside a Python top-level definition and `relfile` for
    anything else.

    Ownership is what makes a hash attributable, and the unit of ownership is the unit the
    tag sits in. Keyed per file, a file tagged by several requirements had to be dropped
    entirely — a change in it cannot be blamed on one contract — which excluded this
    engine's own 9k-line file and its 205 requirements from reverse drift altogether.
    Keyed per definition, each requirement owns the definitions tagged with it and the
    ambiguity is gone; a definition tagged by SEVERAL requirements is still ambiguous and
    still dropped, at that finer granularity.

    Python only, because a wrong span is a wrong drift signal: the brace languages are
    read by heuristics elsewhere in this engine and keep the whole-file hash. The key says
    which was used, so the lock is self-describing."""
    owners = {}   # key -> set(rid);  where -> (path, lo, hi) or None for whole-file
    where = {}
    spans_by_file = {}
    for rid, hits in members.items():
        for role, fp, ln in hits:
            if role not in MEMBER_ROLES:
                continue
            path = os.path.join(code_root, fp)
            if fp not in spans_by_file:
                spans_by_file[fp] = _py_def_spans(path)
            key, span = _member_span_key(spans_by_file[fp], fp, ln, path)
            owners.setdefault(key, set()).add(rid)
            where[key] = span
    out = {}
    for key, rids in owners.items():
        if len(rids) != 1:
            continue          # shared: a change here names no single contract
        span = where[key]
        sha = _span_sha(*span) if span else _file_sha(os.path.join(code_root, key))
        if sha is not None:
            out.setdefault(next(iter(rids)), {})[key] = sha
    return out


def member_drift(reqs, members, lock, memberlock, code_root, current=None):
    # implements: ARCH-MEMBERDRIFT-027  # implements: REQ-MEMBERDRIFT-880
    """Sorted (rid, relfile) where a confirmed requirement's dedicated member changed
    since the member-lock while the requirement's OWN contract did not. A requirement
    whose contract also drifted is skipped — that is forward drift (the spec WAS
    re-touched) and the contract-drift warning already owns it. A member with no recorded
    baseline is skipped, so a freshly-tagged file is baselined on the next sync, not nagged.

    `current` lets a caller that already computed `compute_member_hashes(code_root, members)`
    (e.g. to also rebaseline `_memberlock.json` from the same member set) pass it in instead
    of paying for a second identical hash pass; omit it to compute it here as before."""
    if current is None:
        current = compute_member_hashes(code_root, members)
    out = []
    for rid, r in reqs.items():
        if r["meta"].get("status") != "confirmed":
            continue
        if lock.get(rid) and lock[rid] != binding_hash(r["body"]):
            continue   # forward drift owns this requirement
        recorded = memberlock.get(rid, {})
        for rel, sha in current.get(rid, {}).items():
            old = recorded.get(rel)
            if old and old != sha:
                out.append((rid, rel))
    return sorted(out)


def _engine_version_at(path):
    """Best-effort MAP_ENGINE_VERSION of the engine whose CLI is the reqmap.py at `path`;
    None on any failure. Since the split into a package the constant lives in
    `reqmap_engine/__init__.py` beside that file; a single-file engine (any copy
    seeded before v7.0.0) still carries it in reqmap.py itself, so both are read."""
    for candidate in (path, os.path.join(os.path.dirname(path), "reqmap_engine", "__init__.py")):
        try:
            with open(candidate, encoding="utf-8") as f:
                # whole file + line-anchored: a bounded read() silently returned None
                # once the header outgrew the bound, and an unanchored search could
                # match a docstring mention before the real assignment.
                m = re.search(r'(?m)^MAP_ENGINE_VERSION\s*=\s*"([^"]+)"', f.read())
            if m:
                return m.group(1)
        except Exception:  # fail open — never let the staleness probe break the gate
            continue
    return None


def _ver_key(v):  # implements: ARCH-CHECK-006
    """Sortable key for a MAP_ENGINE_VERSION (`YYYY-MM-DD` + optional `.N` suffix).
    Compares the numeric suffix as an int so `.10` sorts after `.9` (lexicographic
    string compare gets that wrong)."""
    date, _, n = (v or "").partition(".")
    return (date, int(n) if n.isdigit() else 0)


def warn_if_stale():  # implements: ARCH-CHECK-006
    """Print a non-fatal notice when this vendored copy is older than the installed
    plugin's. Silent in CI: only runs when CLAUDE_PLUGIN_ROOT is set. Never raises,
    never affects the exit code."""
    try:
        root = os.environ.get("CLAUDE_PLUGIN_ROOT")
        if not root:
            return
        plugin_ver = _engine_version_at(os.path.join(root, "scripts", "reqmap.py"))
        if plugin_ver and _ver_key(plugin_ver) > _ver_key(MAP_ENGINE_VERSION):
            print(f"WARN  vendored reqmap.py is stale ({MAP_ENGINE_VERSION} < plugin "
                  f"{plugin_ver}) - re-seed: cp -r \"$CLAUDE_PLUGIN_ROOT/scripts/reqmap.py\" "
                  f"\"$CLAUDE_PLUGIN_ROOT/scripts/reqmap_engine\" scripts/")
    except Exception:
        return
