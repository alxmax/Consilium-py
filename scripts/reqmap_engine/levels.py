"""`clarify --levels`: propose and write a V-model rung."""

from .acceptance import _labeled_acs
from .groups import _contract_groups
from .model import _as_list
from .pyramid import (_apply_frontmatter_edit, _insert_frontmatter_key, apply_edges,
                      plan_edges, plan_is_empty, report_edges)


# ---------------------------------------------------------------------------
# Level retrofit — implements: ARCH-LEVELRETROFIT-066
#
# ADR-0030 gives a corpus the three rungs at `init`, and only for a requirement
# `init` EXTRACTED from an untagged source file: the architecture and system rungs
# are minted from those drafts, so a repo whose files already carry tags proposes
# zero drafts and gets zero pyramid. Its requirements were authored before the axis
# existed, and no shipped command could give the axis to them.
#
# This is the explicit, human-invoked half. It reads the corpus, proposes one rung
# per requirement that declares none, prints the reason for each, and writes nothing
# without `--apply`. Every write carries `level_source: auto` (ADR-0030's marker), and
# the footprint is those two lines: delete `level:` and `level_source:` and the corpus
# reads as it did. ADR-0030's reversibility is cleaner than this one, because there the
# whole FILE was engine-written; here a field is added to a file a human wrote, which is
# exactly why the write is opt-in and marked. It is deliberately NOT reachable from
# `sync`, which the pre-commit hook runs on every commit.
# ---------------------------------------------------------------------------

def _propose_levels(reqs, members=None, ac_cover=None):
    # implements: ARCH-LEVELRETROFIT-066  # implements: REQ-LEVELRETROFIT-985
    """{rid: (level, reason)} for every requirement that declares no `level:`.

    Four rules, first match wins, each carrying the sentence it will print. A
    requirement that already declares a level is absent from the result: the retrofit
    proposes onto silence and never overrules an author.

    `code` is the default for a requirement bound to code (ADR-0038): one file, one
    behaviour group, however well or badly specified — under-specification is lint's
    finding, not a rung. `architecture` is proposed only where the engine has evidence of
    a GROUP: two or more contract groups (the bold labels `clarify --decompose` splits on)
    or an over-scope exemption. On the first real corpus the older rule — `code` only with
    a `verifies:` tag — put 193 behaviour groups one rung too high and 0 at `code`."""
    members = members or {}
    ac_cover = ac_cover or {}
    out = {}
    for rid in sorted(reqs):
        r = reqs[rid]
        meta = r["meta"]
        if meta.get("level"):
            continue                       # an author's declaration is never overruled
        layer = meta.get("layer", "feature")
        if layer == "need":
            out[rid] = ("system", "layer: need already says stakeholder need")
            continue
        if layer == "aggregate":
            out[rid] = ("architecture",
                        "layer: aggregate has no code of its own, covered by depends_on")
            continue
        groups = len(_contract_groups(r["body"]))
        exempt = _as_list(meta.get("lint_exempt"))
        over = "over-scoped" in exempt or "ac-count-high" in exempt
        if groups >= 2 or over:
            why = "{} contract group(s)".format(groups)
            if over:
                why += " + over-scope exemption"
            out[rid] = ("architecture",
                        "{} — a group; `clarify {} --decompose --apply` builds its code rung"
                        .format(why, rid))
            continue
        impls = sum(1 for (role, _fp, _ln) in members.get(rid, ()) if role == "implements")
        labels = _labeled_acs(r["body"])
        covered = [ac for ac in labels if ac in (ac_cover.get(rid) or {})]
        out[rid] = ("code",
                    "one behaviour group: {} case(s), {} linked to a test, {} implementing "
                    "member(s)".format(len(labels), len(covered), impls))
    return out


def _insert_frontmatter_level(text, level):
    # implements: ARCH-LEVELRETROFIT-066  # implements: REQ-LEVELRETROFIT-986
    """Add `level:` and `level_source: auto` right after `status:`, where the template puts
    them. Returns (text, 0) when there is no frontmatter to edit or a `level:` is already
    declared, so the caller reports a miss instead of writing a corrupt file."""
    text2, n = _insert_frontmatter_key(text, "level", level, after=("status",))
    if n == 0:
        return text, 0
    text3, _n = _insert_frontmatter_key(text2, "level_source", "auto", after=("level",))
    return text3, 1


def _apply_level(r, level):
    # implements: ARCH-LEVELRETROFIT-066  # implements: REQ-LEVELRETROFIT-986
    """Write one requirement's proposed rung into its file, preserving the file's own
    line endings and every sibling block in a module file. Returns (ok, message)."""
    n = _apply_frontmatter_edit(r, lambda t: _insert_frontmatter_level(t, level))
    if n == 0:
        return False, "no editable frontmatter for {} in {}".format(
            r["meta"].get("id", "?"), r["path"])
    return True, "{}: level: {}".format(r["meta"].get("id", "?"), level)


def cmd_levels(ws, apply_it=False, only=None):
    # implements: ARCH-LEVELRETROFIT-066  # implements: REQ-LEVELRETROFIT-987
    """Propose the V-model rung for every requirement that declares none, and the two
    upper rungs plus the edges that make the whole a pyramid (ADR-0038), in the shape
    `init` writes for a fresh repo.

    Read-only unless `--apply`, always exit 0, and never a gate rule. The family is the
    id prefix the author typed into every id, never `depends_on`; the read-only run prints
    that plan beside the rung proposals, so a reader sees the whole write before making
    it."""
    reqs = ws.reqs
    if only and only not in reqs:
        print("no requirement with id {}".format(only))
        return 1
    scope = {only: reqs[only]} if only else reqs
    proposals = _propose_levels(scope, ws.members, ws.ac_cover)
    plan = plan_edges(scope, proposals)
    already = sum(1 for r in scope.values() if r["meta"].get("level"))
    if not proposals and plan_is_empty(plan):
        print("{} of {} requirement(s) already declare a `level:`, and every one satisfies "
              "the rung above it — nothing to propose.".format(already, len(scope)))
        return 0
    by_level = {}
    for rid, (lv, _why) in proposals.items():
        by_level.setdefault(lv, []).append(rid)
    if proposals:
        print("Proposed rungs for {} requirement(s) that declare none "
              "({} already declare one):\n".format(len(proposals), already))
        for lv in ("system", "architecture", "code"):
            for rid in by_level.get(lv, []):
                print("  {:<14} {:<26} {}".format(lv, rid, proposals[rid][1]))
    else:
        print("All {} requirement(s) already declare a `level:`.".format(len(scope)))
    grouped = sorted(rid for rid, r in scope.items() if len(_contract_groups(r["body"])) >= 2)
    if grouped:
        print("\n  {} requirement(s) carry contract groups — `clarify --decompose --apply` "
              "builds".format(len(grouped)))
        print("  their code rung: " + ", ".join(grouped[:6]) + (" …" if len(grouped) > 6 else ""))
    report_edges(plan)
    if not apply_it:
        print("\n  Nothing written. Re-run with --apply. The footprint is `level:` and")
        print("  `level_source: auto` per requirement, one `satisfies:` line per requirement")
        print("  below the apex, and one draft `ARCH-*`/`SYS-*` file per placeholder; delete")
        print("  them and the corpus reads exactly as it does now. The files are ones a human")
        print("  wrote, which is why the write is opt-in and every line says who put it there.")
        return 0
    ok = 0
    for rid in sorted(proposals):
        good, msg = _apply_level(reqs[rid], proposals[rid][0])
        print("  " + ("wrote  " if good else "SKIP   ") + msg)
        ok += 1 if good else 0
    n_arch, n_sys, n_edges = apply_edges(reqs, ws.reqs_dir, plan)
    print("\n{} requirement(s) updated, {} capability placeholder(s) and {} system "
          "placeholder written, {} `satisfies:` edge(s) added.".format(ok, n_arch, n_sys, n_edges))
    print("Run `reqmap.py sync` to rebuild the map, and review every proposal — the engine")
    print("  guessed a rung from shape, which is not the same as knowing what the requirement")
    print("  is for. Name the `ARCH-*`/`SYS-*` holes first; each title says what it groups.")
    return 0
