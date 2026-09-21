"""`ask --design`: per-file dispatch, the summary record and cmd_design."""
import json

from .design import (
    DESIGN_BRACE_EXTS, DESIGN_EXTS, DESIGN_METRICS_SCOPE, DESIGN_PILLARS, _DESIGN_ADVICE,
    _design_standards
)
from .design_brace import _design_brace
from .design_python import _cohesion_skipped_in, _python_findings
from .scan import _walk_code
from .tags import _is_test_path


def _design_file(rel, src):
    # implements: ARCH-DESIGN-061  # implements: REQ-DESIGN-950  # implements: REQ-DESIGN-951
    # implements: REQ-DESIGN-953  # implements: REQ-DESIGN-955
    """All findings for one source file, in source order: Python through `ast`, a brace
    language through the masked-text heuristics, anything else standards only."""
    low = rel.lower()
    try:
        if low.endswith(".py"):
            out = _python_findings(rel, src)
        elif low.endswith(DESIGN_BRACE_EXTS):
            out = _design_brace(rel, src)
        else:
            out = _design_standards(rel, src, 0, [])
    except RecursionError:
        # `ast.dump` on a pathological class body is recursive too. This review is
        # advisory and never the gate; a file it cannot measure is a file with no
        # candidates, not a crashed commit hook.
        return []
    out.sort(key=lambda f: (f["line"], f["kind"]))
    return out


def _design_files(code_root, reqs_dir=None):
    """(abs_path, rel) for every non-test program-logic file the scanner would walk."""
    for fp, rel in _walk_code(code_root, reqs_dir):
        if rel.lower().endswith(DESIGN_EXTS) and not _is_test_path(rel):
            yield fp, rel


def _design_summary(code_root, reqs_dir=None, with_findings=False):
    # implements: ARCH-DESIGN-061  # implements: REQ-DESIGN-954  # implements: REQ-DESIGN-976
    """The design health of the repo's code as one small record, or None when the tree
    holds no non-test program-logic file: `files`, `clean_files` (no candidate at all),
    `score` (clean files as a percentage — the same "green on every axis" reading `health`
    uses for requirements), `candidates` (count per group). Deterministic, so it can live
    in the committed `_map.json` and be checked for freshness.

    `with_findings` adds the candidates themselves, for the one caller that lists them
    (`map`, whose viewer shows them in their own tab). It is off by default because
    `health --json` is a CI badge payload: a caller reading a score must keep getting
    the same small object, not a few hundred rows it never asked for. The advice text
    is emitted once per kind rather than repeated on every row — it is a property of
    the rule, not of the occurrence."""
    files = clean = 0
    per = {p: 0 for p in DESIGN_PILLARS}
    rows = []
    for fp, rel in _design_files(code_root, reqs_dir):
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except OSError:
            continue
        files += 1
        found = _design_file(rel, src)
        if not found:
            clean += 1
        for x in found:
            per[x["pillar"]] += 1
        if with_findings:
            rows.extend(found)
    if not files:
        return None
    out = {"files": files, "clean_files": clean, "score": round(100 * clean / files),
           "candidates": per}
    if with_findings:
        out["findings"] = [{"pillar": x["pillar"], "kind": x["kind"], "file": x["file"],
                            "line": x["line"], "name": x["name"], "detail": x["detail"]}
                           for x in rows]
        out["advice"] = {k: _DESIGN_ADVICE[k] for k in sorted({x["kind"] for x in rows})}
    return out


def cmd_design(code_root, reqs_dir=None, as_json=False):
    # implements: ARCH-DESIGN-061  # implements: REQ-DESIGN-952
    """Print (or emit as JSON) the design candidates found in every non-test program-logic
    file under `code_root`, grouped by pillar. Read-only, always exit 0: this is advice a
    reader weighs, not a gate a build fails on."""
    findings, n_files, skipped = [], 0, 0
    for fp, rel in _design_files(code_root, reqs_dir):
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                src = f.read()
        except OSError:
            continue
        n_files += 1
        findings.extend(_design_file(rel, src))
        if rel.lower().endswith(".py"):
            skipped += _cohesion_skipped_in(src)
    if as_json:
        # The machine surface carries the same caveats as the text one. A consumer
        # dashboard reading `findings` and nothing else would otherwise render an empty
        # metrics group as a clean bill of health on metrics that were never computed.
        print(json.dumps({"files": n_files, "findings": findings,
                          "metrics_scope": DESIGN_METRICS_SCOPE,
                          "cohesion_skipped": skipped}, indent=2, ensure_ascii=False))
        return 0
    if not findings:
        print("No design candidates in {} source file(s) at the current thresholds."
              .format(n_files))
        print("note: " + DESIGN_METRICS_SCOPE)
        if skipped:
            print("note: cohesion not measured for {} class(es) with 2+ methods and no "
                  "field this engine can see.".format(skipped))
        return 0
    for pillar in DESIGN_PILLARS:
        mine = [f for f in findings if f["pillar"] == pillar]
        if not mine:
            continue
        print("{} ({})".format(pillar.capitalize(), len(mine)))
        for f in mine:
            print("  {}:{}  {:<20} {}".format(f["file"], f["line"], f["kind"], f["detail"]))
        print("  -> " + "; ".join(dict.fromkeys(_DESIGN_ADVICE[f["kind"]] for f in mine)))
        if pillar == "metrics":
            print("  note: " + DESIGN_METRICS_SCOPE)
            if skipped:
                print("  note: cohesion not measured for {} class(es) with 2+ methods and no "
                      "field this engine can see.".format(skipped))
        print("")
    print("{} candidate(s) in {} source file(s). Advisory only: a candidate is a shape worth a "
          "look, never a defect, and this never enters the gate.".format(len(findings), n_files))
    return 0
