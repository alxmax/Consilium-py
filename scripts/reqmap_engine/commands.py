"""The COMMANDS registry: the CLI's single source of truth, one entry per command (data only).
"""



# ---------------------------------------------------------------------------
# COMMANDS registry — single source of truth for the CLI command set.
# Each entry describes one user-facing command: its summary, the positional
# argument it accepts (or None), and the flags it owns (subset of the shared
# argparse flag pool; global flags --root/--reqs/--code/--cache are omitted).
# Later tasks will derive argparse choices, tool_definition.json, and a
# markdown command table from this registry — do NOT add behaviour here.
# ---------------------------------------------------------------------------
# implements: ARCH-CMDREGISTRY-033  # implements: REQ-NEWGONE-1034
COMMANDS = {
    "init": {
        "summary": (
            "First-use bootstrap: scaffold requirements/ and .reqmapignore if missing, "
            "draft requirements from existing code and prose, build the lock and map, and "
            "print guided next steps. Idempotent — safe to re-run; never clobbers an "
            "existing .reqmapignore. --plan emits the extraction plan as JSON and writes no "
            "requirement files, for looking before authoring. "
       
        ),
        "arg": None,
        "params": [
            {
                "name": "plan",
                "flag": "--plan",
                "type": "bool",
                "help": (
                    "Emit the extraction plan as JSON instead of writing requirement files."
                ),
            },
            {
                "name": "out",
                "flag": "--out",
                "type": "str",
                "help": (
                    "With --plan: write the plan JSON here ('-' or omitted = stdout)."
                ),
            },
            {
                "name": "md_glob",
                "flag": "--md-glob",
                "type": "str",
                "help": (
                    "With --plan: also scan these non-code globs for capabilities (repeatable)."
                ),
            },
            {
                "name": "wipe",
                "flag": "--wipe",
                "type": "bool",
                "help": (
                    "Hard-reset: delete all non-generated requirements and strip "
                    "membership tags from source files before re-extracting."
                ),
            },
            {
                "name": "no_site",
                "flag": "--no-site",
                "type": "bool",
                "help": "Skip the final site step (scaffolding docs/architecture.html).",
            },
        ],
    },
    "gate": {
        "summary": (
            "The commit/CI verdict. Bare, it verifies that every code tag resolves to a real "
            "requirement, that every confirmed requirement has at least one implements: "
            "member, and that drift has not been introduced since the last sync, then checks "
            "requirement readability and map freshness. Exits non-zero on link-sync errors "
            "only. Never writes anything. Three mode flags report on the verdict's own "
            "subject instead of running it: --audit for the whole problem report, --risk for "
            "what to do next, --show for one requirement's dossier. Every other question is "
            "`ask`. "
        ),
        "arg": None,
        "params": [
            {
                "name": "mode_audit",
                "flag": "--audit",
                "type": "bool",
                "help": (
                    "Print every pass that discovers a problem as one report: the gate, corpus "
                    "risk, duplicate contracts, design signals and tag coverage. The exit code "
                    "still comes from the gate alone."
                ),
            },
            {
                "name": "mode_risk",
                "flag": "--risk",
                "type": "bool",
                "help": (
                    "Print the corpus risk snapshot and the actionable signals, most urgent first."
                ),
            },
            {
                "name": "mode_show",
                "flag": "--show",
                "type": "str",
                "help": (
                    "Print one requirement's dossier: intent, contract, dependencies both ways, "
                    "code members with file:line, open questions and risk signals."
                ),
            },
            {
                "name": "show_all",
                "flag": "--all",
                "type": "bool",
                "help": (
                    "With --risk: expand every bucket instead of the top few."
                ),
            },
            {
                "name": "untagged",
                "flag": "--untagged",
                "type": "bool",
                "help": (
                    "With --risk: report membership-tag coverage per directory."
                ),
            },
            {
                "name": "as_badge",
                "flag": "--badge",
                "type": "bool",
                "help": (
                    "With --risk: print the coherence score as a badge string."
                ),
            },
            {
                "name": "strict",
                "flag": "--strict",
                "type": "bool",
                "help": (
                    "Promote drift and test-link integrity warnings to errors. "
                    "Useful in CI when all requirements are confirmed."
                ),
            },
            {
                "name": "json",
                "flag": "--json",
                "type": "bool",
                "help": "Emit structured JSON output instead of human-readable text.",
            },
            {
                "name": "since",
                "flag": "--since",
                "type": "str",
                "help": (
                    "Scope the gate to requirements whose member files changed since "
                    "this git ref (e.g. 'main', 'HEAD~1')."
                ),
            },
            {
                "name": "no_lint",
                "flag": "--no-lint",
                "type": "bool",
                "help": "Skip the requirement readability check.",
            },
            {
                "name": "no_map_check",
                "flag": "--no-map-check",
                "type": "bool",
                "help": "Skip the committed-map freshness check.",
            },
        ],
    },
    "ask": {
        "summary": (
            "Ask the corpus a question without running the verdict. Read-only, never "
            "writes, and its exit code is the question's, never the gate's: --search ranks "
            "requirements by relevance, --dupes ranks overlapping contracts, --design reviews "
            "the code, --review emits the machine-readable review plan, --i18n lists missing "
            "translations. Exactly one mode per call. Since v8.0.0, `gate` refuses these "
            "flags and names `ask`. "
        ),
        "arg": None,
        "params": [
            {
                "name": "mode_search",
                "flag": "--search",
                "type": "str",
                "help": (
                    "Rank requirements by lexical relevance to a free-text query."
                ),
            },
            {
                "name": "mode_dupes",
                "flag": "--dupes",
                "type": "bool",
                "help": (
                    "Rank requirement pairs whose contracts overlap, most similar first."
                ),
            },
            {
                "name": "mode_design",
                "flag": "--design",
                "type": "bool",
                "help": (
                    "Print the advisory design review of the code. Never part of the verdict."
                ),
            },
            {
                "name": "mode_review",
                "flag": "--review",
                "type": "str",
                "help": (
                    "Emit the deterministic review plan as JSON: for one requirement, or "
                    "with no id for the whole corpus."
                ),
            },
            {
                "name": "mode_i18n",
                "flag": "--i18n",
                "type": "bool",
                "help": (
                    "List the translations the configured LANGUAGE (en | ro | both, in "
                    "requirements/_config.json) expects and does not have, missing or stale. "
                    "--json emits each entry's source fields and cache key for whoever translates."
                ),
            },
            {
                "name": "top",
                "flag": "--top",
                "type": "int",
                "help": (
                    "With --search or --dupes: how many results to print."
                ),
            },
            {
                "name": "threshold",
                "flag": "--threshold",
                "type": "str",
                "help": (
                    "With --dupes: override the similarity threshold."
                ),
            },
            {
                "name": "json",
                "flag": "--json",
                "type": "bool",
                "help": "Emit structured JSON output instead of human-readable text.",
            },
        ],
    },
    "sync": {
        "summary": (
            "The write path. Rescan code members, advance the drift baseline, and "
            "regenerate the map, the findings file and the generated integration artifacts "
            "in one step. Run after editing requirement files or tagging new code members. "
            "--accept-drift is required when a confirmed or implemented contract changed. "
       
        ),
        "arg": None,
        "params": [
            {
                "name": "mode_retire",
                "flag": "--retire",
                "type": "list",
                "help": (
                    "Take these requirements out of service instead of confirming them. Accepts "
                    "one id or many; a batch retires in an order computed from the graph, under "
                    "one working-tree check. Prints the blast radius; writes nothing without "
                    "--apply."
                ),
            },
            {
                "name": "mode_release",
                "flag": "--release",
                "type": "str",
                "help": (
                    "Cut a release instead of syncing: the next version planned in "
                    "_planning.json above what is already declared, or the vX.Y.Z named "
                    "here. Prints the plan - version files to bump, the CHANGELOG entry, "
                    "the milestone the plan drops - and writes nothing without --apply. "
                    "With --json it also reports the declared version, whether its tag "
                    "exists and its notes, which is what a release workflow reads."
                ),
            },
            {
                "name": "delete",
                "flag": "--delete",
                "type": "bool",
                "help": (
                    "With --retire: also remove the block, its lock entries and its membership "
                    "tags. Never a function body."
                ),
            },
            {
                "name": "do_apply",
                "flag": "--apply",
                "type": "bool",
                "help": (
                    "With --retire or --release: actually write the change. Without it, "
                    "the run is a dry report."
                ),
            },
            {
                "name": "force",
                "flag": "--force",
                "type": "bool",
                "help": (
                    "With --retire: proceed even though dependents still point at this "
                    "requirement, or the working tree is dirty. Dependents that are already "
                    "deprecated, and those retired in the same call, never block."
                ),
            },
            {
                "name": "findings",
                "flag": "--findings",
                "type": "bool",
                "help": (
                    "Also regenerate the aggregated open-questions file."
                ),
            },
            {
                "name": "attach",
                "flag": "--attach",
                "type": "str",
                "help": (
                    "Target HTML to inject the site's engine-owned regions into "
                    "(scaffolds it if absent)."
                ),
            },
            {
                "name": "accept_drift",
                "flag": "--accept-drift",
                "type": "str",
                "help": (
                    "Explicitly advance the baseline when a confirmed or implemented "
                    "contract changed. Required when those contracts differ from the "
                    "lock; sync exits non-zero without it. Takes an optional reason, "
                    "recorded in requirements/_driftlog.json so the waiver and its "
                    "justification land in the diff."
                ),
            },
            {
                "name": "strict",
                "flag": "--strict",
                "type": "bool",
                "help": "Promote drift and test-link integrity from warn to error.",
            },
            {
                "name": "json",
                "flag": "--json",
                "type": "bool",
                "help": "With --retire or --release: emit the plan as JSON.",
            },
        ],
    },
    "clarify": {
        "summary": (
            "Ask what a requirement has not answered yet: vague terms with no threshold, "
            "numbers with no unit, unbounded quantities, clauses with no case, a missing "
            "failure path. Read-only, always exit 0, never a gate rule. --decompose is the "
            "write half of the same question: it splits a requirement into code-rung "
            "children along the bold group labels in its Description (--apply writes), or "
            "scaffolds one draft per over-long clause when it has none. Run it before "
            "implementing, so the ambiguity is resolved in the requirement instead of "
            "guessed in code. "
       
        ),
        "arg": "AREA-NAME-NNN",
        "params": [
            {
                "name": "decompose",
                "flag": "--decompose",
                "type": "bool",
                "help": (
                    "Split a requirement into code-rung children along the bold group labels "
                    "its author wrote in the Description; --apply writes them and rewrites the "
                    "parent. With no id, every requirement carrying groups. A requirement with "
                    "no groups falls back to one draft per over-long clause."
                ),
            },
            {
                "name": "levels",
                "flag": "--levels",
                "type": "bool",
                "help": (
                    "Propose a V-model rung for every requirement that declares no `level:`, "
                    "plus the rungs above: one draft `ARCH-<FAMILY>-001` per id-prefix family, "
                    "`SYS-NEEDS-A-NAME-001` at the apex, and the `satisfies:` edges between "
                    "them. --apply writes all of it, each line marked `level_source: auto`."
                ),
            },
            {"name": "as_json", "flag": "--json", "type": "bool",
             "help": "Emit the questions as JSON for an agent to answer."},
            {"name": "do_apply", "flag": "--apply", "type": "bool",
             "help": "With --decompose or --levels: write the proposal instead of printing it."},
        ],
    },
    # `tool: False` — a server is not a function to call, so the generated function-calling
    # schema leaves it out; the help text and SKILL.md still document it.
    "mcp": {
        "summary": (
            "Serve this repository's requirements to an AI assistant over the Model Context "
            "Protocol (stdio). Each tool is one reqmap invocation in a fresh process. "
            "Read-only unless --allow-writes."
        ),
        "arg": None,
        "tool": False,
        "params": [
            {
                "name": "allow_writes",
                "flag": "--allow-writes",
                "type": "bool",
                "help": "Also offer the tools that write: sync, new and release.",
            },
        ],
    },
}


# Which moment of the workflow each verb belongs to. The registry is the CLI's
# single source of truth, so the grouping the help text and the viewer both show is
# declared here once rather than restated in each surface.
COMMAND_GROUPS = (
    ("author", ("init", "clarify")),
    ("build", ("sync",)),
    ("read", ("gate", "ask", "mcp")),
)
