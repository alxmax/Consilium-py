"""The gate verdict: cmd_check, over the rules and the workspace."""
import json, os, sys

from . import ENGINE_DIR, config as cfg
from .author import _write_frontmatter_status
from .clarify import blocking_question_rules
from .findings import collect_findings
from .locks import (
    compute_member_hashes, load_clarifylock, record_accepted_drift, save_clarifylock, save_lock,
    save_memberlock, warn_if_stale
)
from .mapjson import _path_key, _since_changed_files
from .model import Finding, GATE_RULES
from .registry import _check_integration_fresh
from .rules import DRIFT_RULES
from . import axis  # noqa: F401 — registers RM032 after every rule in `rules`
from . import docclaims  # noqa: F401 — registers RM035, same reason as `axis`
from .sections import _legacy_schema_ids
from .workspace import GateContext, Workspace


def run_gate_rules(ctx, strict=False):
    # implements: ARCH-RULES-059  # implements: REQ-RULES-947
    # implements: REQ-RULES-948  # implements: REQ-RULES-989
    """Run every registered rule over `ctx` -> (errors, warns) as Finding lists, in
    registry order. A rule's `strict` flag promotes its findings to errors under
    `--strict`, except RM012 on a non-confirmed requirement, which stays a plain warn
    so a draft-heavy consumer's strict CI cannot start failing on it. A requirement
    whose `gate_exempt:` names the rule's code is skipped for that rule.

    `DRIFT_SEVERITY: "error"` in a repo's `_config.json` promotes the two drift rules
    for THAT repo without `--strict` and without moving anyone else's default. The
    promotion is resolved here, per run, and never written back onto the Rule: the
    registry is module state shared by two `cmd_check` calls inside `audit`, and a
    mutation would leak from the first into the second. `gate_exempt:` is checked
    before any of this, so a requirement's own written-down exemption still wins —
    a repo-wide dial must not silently overrule a decision made per requirement."""
    errors, warns = [], []
    for rule in GATE_RULES:
        if rule.only_source_repo and not ctx.source_repo:
            continue
        for rid, msg in rule.fn(ctx):
            if rid is not None and ctx.req(rid).exempt_from(rule.id):
                continue
            sev = rule.severity
            if rule.strict and strict:
                confirmed = rid is None or ctx.req(rid).status == "confirmed"
                if rule.id != "RM012" or confirmed:
                    sev = "error"
            if sev != "error" and rule.id in DRIFT_RULES and cfg.DRIFT_SEVERITY == "error":
                sev = "error"
            (errors if sev == "error" else warns).append(Finding(rule.id, sev, rid, msg))
    return errors, warns


def _scope_members_since(since, code_root, members):
    # implements: ARCH-CHECK-006  # implements: ARCH-RULES-059  # implements: REQ-CHECK-832
    # implements: REQ-CHECK-833  # implements: REQ-RULES-948
    """Narrow `members` to files changed since `since`, WARN-ing and falling back to the
    full set if git is unavailable or the ref is invalid."""
    if not since:
        return members, []
    changed = _since_changed_files(since, code_root)
    if changed is None:
        warn = Finding("RM000", "warn", None,
                       f"--since {since!r}: git diff failed or ref not found; "
                       "falling back to full scan")
        return members, [warn]
    filtered = {}
    for cap, entries in members.items():
        kept = [(role, fp, ln) for role, fp, ln in entries
                if _path_key(os.path.join(code_root, fp)) in changed]
        if kept:
            filtered[cap] = kept
    return filtered, []


def _demote_drifted_confirmed(reqs, confirmed_drift, full_members):
    # implements: ARCH-CHECK-006  # implements: ARCH-RULES-059  # implements: REQ-CHECK-832
    # implements: REQ-CHECK-833  # implements: REQ-RULES-948
    """Demote each drifted confirmed/implemented requirement back to draft, printing why
    and which member files to re-check."""
    print("Contract changed on %d confirmed requirement(s) — status back to "
          "`draft`, because nobody has re-validated them:" % len(confirmed_drift))
    for rid in confirmed_drift:
        r = reqs.get(rid) or {}
        was = r.get("meta", {}).get("status")
        if r and _write_frontmatter_status(r, "draft"):
            r["meta"]["status"] = "draft"   # keep this run's own report honest
            print("  demoted: %s  %s -> draft" % (rid, was))
            # Name the code, not just the requirement: a changed contract is a
            # question about whether the code still matches it, and the answer
            # lives in these files. Without them the demotion says what happened
            # and not what to do about it.
            locs = ["%s:%s" % (fp, ln) for (_role, fp, ln) in full_members.get(rid, ())]
            if locs:
                print("      re-check %d member(s): %s" % (len(locs), ", ".join(locs)))
            else:
                print("      no members tagged — add an `implements:` tag")
        else:
            print("  WARN  %s: no `status:` line to change" % rid)
    print("  These no longer gate. Re-read the code above against the new contract,")
    print("  change whichever is wrong, then set the status back by hand — or re-run")
    print("  with --accept-drift if the edit did not change what the code must do.")


def _advance_lock_and_report(ctx, accept_drift, drift_reason):
    # implements: ARCH-CHECK-006  # implements: ARCH-RULES-059  # implements: REQ-CHECK-832
    # implements: REQ-CHECK-833  # implements: REQ-RULES-948
    """Print the lock diff, accept or demote drifted confirmed contracts, then save the
    lock, memberlock and clarify baselines. Reads `reqs`/`reqs_dir`/`code_root`/
    `full_members`/`lock`/`new_lock`/`full_member_hashes` off `ctx` — everything a
    gate rule can already read, so the caller passes nothing it did not already put
    there."""
    reqs, reqs_dir, code_root = ctx.reqs, ctx.reqs_dir, ctx.code_root
    full_members, lock, new_lock = ctx.full_members, ctx.lock, ctx.new_lock
    full_member_hashes = ctx.full_member_hashes
    changed = [(rid, lock.get(rid), h)
               for rid, h in sorted(new_lock.items()) if lock.get(rid) != h]
    removed = [rid for rid in sorted(lock) if rid not in new_lock]
    for rid, old_h, new_h in changed:
        old_short = old_h[:8] if old_h else "new"
        print(f"  lock update: {rid} hash changed ({old_short}->{new_h[:8]})")
    for rid in removed:
        print(f"  lock update: {rid} removed from lock")
    # sync drift guard: refuse to silently re-baseline an EDITED confirmed/implemented
    # contract unless the caller explicitly accepts it (accept_drift). A brand-new
    # requirement (old hash None) is not drift.
    confirmed_drift = [rid for (rid, old_h, _h) in changed
                       if old_h is not None
                       and reqs.get(rid, {}).get("meta", {}).get("status")
                       in ("confirmed", "implemented")]
    if confirmed_drift and accept_drift:
        record_accepted_drift(reqs_dir, confirmed_drift, new_lock,
                              drift_reason, set(new_lock))
        print("  accepted drift on %d confirmed contract(s), reason: %s"
              % (len(confirmed_drift), drift_reason or "(none given)"))
    if confirmed_drift and not accept_drift:  # implements: REQ-PROMOTE-974
        _demote_drifted_confirmed(reqs, confirmed_drift, full_members)
    save_lock(reqs_dir, new_lock)
    save_memberlock(reqs_dir, full_member_hashes
                     if full_member_hashes is not None
                     else compute_member_hashes(code_root, full_members))
    print("lock updated.")
    # Clarifying one requirement can raise questions the previous text never had —
    # a new clause with an unbounded quantity, a case with no failure path. Nobody
    # re-reads the whole corpus after an edit, so the diff is reported here, where
    # every edit already passes.  # implements: REQ-CLARIFY-975
    _q_now = blocking_question_rules(reqs)
    _q_before = load_clarifylock(reqs_dir)
    _fresh = sorted((rid, sorted(set(rules) - set(_q_before.get(rid, []))))
                    for rid, rules in _q_now.items())
    _fresh = [(rid, rules) for rid, rules in _fresh if rules and rid in _q_before]
    if _fresh:
        print("")
        print("New open question(s) since the last sync — an edit raised them:")
        for rid, rules in _fresh:
            print("  %s: %s" % (rid, ", ".join(rules)))
        print("  Read them with `reqmap.py clarify <ID>`.")
    save_clarifylock(reqs_dir, _q_now)


def _stale_integration_artifacts():
    # implements: ARCH-CHECK-006  # implements: ARCH-RULES-059  # implements: REQ-CHECK-832
    # implements: REQ-CHECK-833  # implements: REQ-RULES-948
    """Check this plugin repo's generated integration artifacts for staleness, if this
    tree is the plugin repo itself (skipped silently for a vendored/consumer copy)."""
    # Only inside the plugin package itself: two directories above a VENDORED engine
    # (`<consumer>/scripts/reqmap.py`) is the consumer's repo root, and a consumer that
    # ships its own `tool_definition.json` there was failing its gate on ours.
    plugin_root = os.path.dirname(ENGINE_DIR)
    if os.path.exists(os.path.join(plugin_root, ".claude-plugin", "plugin.json")):
        return _check_integration_fresh(plugin_root)
    return []


def _drift_acceptance(accept_drift):
    # implements: ARCH-CHECK-006  # implements: REQ-PROMOTE-974
    """(accepted, reason) from the one `accept_drift` value a caller passes: True or False,
    or the reason string `--accept-drift REASON` yields.

    Read with `is not False`, never with truthiness: `--accept-drift ""` is a caller who
    passed the flag with an empty reason, and reading it as falsy would demote contracts
    they meant to keep."""
    if isinstance(accept_drift, str):
        return True, accept_drift.strip() or None
    return accept_drift is not False, None


def cmd_check(ws, update_lock, strict=False, as_json=False, since=None, accept_drift=True):
    # implements: ARCH-CHECK-006  # implements: ARCH-RULES-059  # implements: REQ-CHECK-832
    # implements: REQ-CHECK-833  # implements: REQ-RULES-948
    """The gate: run GATE_RULES, print findings with their codes, advance the lock when
    asked. Report-only unless `update_lock` (that is `sync`).

    `accept_drift` is True, False, or the reason string the flag carried; see
    `_drift_acceptance` for why an empty reason still accepts."""
    reqs, members, reqs_dir, code_root = ws.reqs, ws.members, ws.reqs_dir, ws.code_root
    code_root = code_root or "."   # a workspace built without one gates the cwd
    ac_cover, level_cover = ws.ac_cover, ws.level_cover
    warn_if_stale()
    full_members = members
    # --since: scope checks to requirements whose member files changed since ref.
    # Fail-open: fall back to full scan with WARN if git is unavailable or ref invalid.
    members, pre_warns = _scope_members_since(since, code_root, members)
    # built from the resolved locals, not from `ws` directly: `--since` narrowed
    # `members`, and `code_root` fell back to the cwd just above.
    ctx = GateContext(Workspace(reqs, members, reqs_dir, code_root,
                                ac_cover, level_cover),
                      since=since, full_members=full_members, update_lock=update_lock)
    # the CALLER's workspace carries the map-document cache, so the freshness rule and
    # the `map --check` that `gate` runs next share one assembly instead of two
    ctx.ws = ws
    # sync on a full scan re-baselines _memberlock below from this same hash set —
    # computed once and handed to the member-drift rule instead of hashing twice.
    _reuse_full_hashes = update_lock and members is full_members
    ctx.full_member_hashes = (compute_member_hashes(code_root, full_members)
                              if _reuse_full_hashes else None)
    errors, warns = run_gate_rules(ctx, strict=strict)
    warns = pre_warns + warns
    legacy = _legacy_schema_ids(reqs)

    if update_lock:
        _advance_lock_and_report(ctx, *_drift_acceptance(accept_drift))

    # Integration-artifact freshness must run BEFORE the as_json early-return so
    # --json also exits non-zero on it.
    _stale = _stale_integration_artifacts()
    if _stale:
        errors = list(errors) + [Finding("RM028", "error", None,
                                         "stale integration artifact(s): " + ", ".join(_stale))]
    # counted after the demotion loop above, so a `sync` that just demoted reports the
    # corpus it leaves behind rather than the one it found
    n_confirmed = sum(1 for r in reqs.values() if r["meta"].get("status") == "confirmed")

    if as_json:
        print(json.dumps({"ok": not errors,
                          "errors": [str(e) for e in errors],
                          "warnings": [str(w) for w in warns],
                          "findings": [dict(f) for f in errors + warns]}))
        return 1 if errors else 0

    for w in warns:
        print("WARN ", w["rule"], str(w))
    for e in errors:
        print("ERROR", e["rule"], str(e))
    if _stale:
        print("ERROR: stale generated integration artifact(s): " + ", ".join(_stale)
              + " — run `python scripts/reqmap.py sync` and commit.", file=sys.stderr)

    n_find = sum(len(items) for _rid, _t, items in collect_findings(reqs))
    if n_find:
        print(f"info  {n_find} open verify-intent finding(s) — run `reqmap.py sync`")

    # recompute: the demotion loop above may have flipped some status from
    # "confirmed" to "draft" since n_confirmed was first snapshotted.
    n_confirmed = sum(1 for r in reqs.values() if r["meta"].get("status") == "confirmed")
    print(f"\n{len(reqs)} requirements ({n_confirmed} confirmed, {len(legacy)} legacy-schema), "
          f"{sum(len(v) for v in members.values())} members, "
          f"{len(errors)} errors, {len(warns)} warnings.")
    return 1 if errors else 0
