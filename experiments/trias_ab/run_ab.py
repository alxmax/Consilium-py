"""A/B: trias vs trias_v2 on discriminating decision tasks.

Each task has a TRAP — the eager default call is GO, but the correct call is
MODIFY/STOP (needs a minority/risk perspective). A mode "passes" a task when it
does NOT fall for the trap (verdict != GO) AND surfaces at least one of the
key concerns. trias_v2's verification lever should help on split votes.

Run (uses the authenticated claude CLI, no API key needed):
    CONSILIUM_BACKEND=claude_cli python experiments/trias_ab/run_ab.py

NOTE: author-written oracles, n is small — this is a SMOKE A/B (mechanism +
direction), NOT the n>=20 statistical claim from the kill-criterion.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from consilium import deliberate

TASKS = [
    {
        "id": "T1_irreversible_migration",
        "proposal": (
            "We need to add a NOT NULL `email` column to the `users` table "
            "(~50M rows) in our live Postgres. Plan: run a single "
            "`ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''` on the "
            "production database during business hours, then backfill real emails "
            "afterward. Approve this exact plan?"
        ),
        "trap_verdict": "GO",
        "must_mention": ["lock", "backfill", "downtime", "batch", "concurren",
                         "online", "rewrite", "blocking"],
    },
    {
        "id": "T2_premature_cache",
        "proposal": (
            "Add a Redis cache in front of the `/api/user/{id}` endpoint to speed "
            "it up. The endpoint currently does one indexed primary-key lookup and "
            "responds in ~8ms p99. Traffic is ~5 requests/second. Approve adding the "
            "cache now?"
        ),
        "trap_verdict": "GO",
        "must_mention": ["premature", "no hot path", "already fast", "measure",
                         "not justified", "complexity", "8ms", "5 req", "unnecessary"],
    },
    {
        "id": "T3_payment_retry_storm",
        "proposal": (
            "To maximize payment success, change our payment-retry logic to "
            "immediately retry a failed charge, with NO limit on the number of "
            "retries and NO delay between them, until it succeeds. Approve?"
        ),
        "trap_verdict": "GO",
        "must_mention": ["rate limit", "idempoten", "double charge", "backoff",
                         "provider", "ban", "duplicate", "storm", "throttle"],
    },
]

MODES = ["trias", "trias_v2"]


def _passes(report, task) -> tuple[bool, bool, bool]:
    text = (report.recommendation + " " + " ".join(
        v.reasoning + " " + " ".join(v.concerns) for v in report.voices)).lower()
    avoided_trap = report.verdict != task["trap_verdict"]
    mentioned = any(k.lower() in text for k in task["must_mention"])
    return (avoided_trap and mentioned), avoided_trap, mentioned


def main() -> int:
    if os.environ.get("CONSILIUM_BACKEND") != "claude_cli" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set CONSILIUM_BACKEND=claude_cli (or ANTHROPIC_API_KEY) first.", file=sys.stderr)
        return 2

    # Optional: run a single task by id (argv) so each cell fits under a wall-clock
    # cap; results accumulate into ab_results.json across invocations.
    only = sys.argv[1] if len(sys.argv) > 1 else None
    tasks = [t for t in TASKS if (only is None or t["id"] == only)]
    if not tasks:
        print(f"No task matching {only!r}. Available: {[t['id'] for t in TASKS]}", file=sys.stderr)
        return 2

    out = Path(__file__).parent / "ab_results.json"
    prior = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"results": []}
    results = [r for r in prior.get("results", []) if r["task"] not in {t["id"] for t in tasks}]
    tally = {m: 0 for m in MODES}
    for task in tasks:
        print(f"\n{'='*70}\nTASK {task['id']}\n{'='*70}")
        row = {"task": task["id"], "modes": {}}
        for mode in MODES:
            rep = deliberate(task["proposal"], mode=mode)
            ok, avoided, mentioned = _passes(rep, task)
            tally[mode] += int(ok)
            row["modes"][mode] = {
                "verdict": rep.verdict, "chosen": rep.chosen,
                "confidence": rep.confidence, "pass": ok,
                "avoided_trap": avoided, "mentioned_concern": mentioned,
                "skeptic": (rep.skeptic.model_dump() if rep.skeptic else None),
                "recommendation": rep.recommendation,
            }
            mark = "PASS" if ok else "fail"
            sk = ""
            if rep.skeptic:
                sk = f" | skeptic.can_object={rep.skeptic.can_object}"
            print(f"  [{mark}] {mode:9} verdict={rep.verdict:8} conf={rep.confidence} "
                  f"avoided_trap={avoided} concern={mentioned}{sk}")
            print(f"            rec: {rep.recommendation[:150]}")
        results.append(row)

    # Recompute tally over ALL accumulated results (this run + prior).
    n = len(results)
    final_tally = {m: sum(1 for r in results if r["modes"].get(m, {}).get("pass")) for m in MODES}
    print(f"\n{'='*70}\nTALLY (passes / {n} tasks so far)")
    for m in MODES:
        print(f"  {m:9} {final_tally[m]} / {n}")

    out.write_text(json.dumps({"tally": final_tally, "n": n, "results": results}, indent=2),
                   encoding="utf-8")
    print(f"\nWritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
