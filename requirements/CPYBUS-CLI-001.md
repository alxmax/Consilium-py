---
id: CPYBUS-CLI-001
status: baseline
layer: bus
owner: human
depends_on: [CPYBUS-API-001]
---

# CLI interface — deliberate and check commands

Exposes the deliberation engine as a terminal command (`consilium`) with two subcommands: `deliberate` (for a free-text proposal) and `check` (for deliberating on a git diff).

## WHAT — Contract

- `consilium deliberate "<proposal>"` shall call `deliberate()` with the given proposal and print verdict, confidence, mode, and recommendation in text format, or full JSON with `--output json`.
- `--context <path>` (repeatable) shall read each file and concatenate its content into the `context` argument. Multiple `-c` flags are supported.
- `--mode` shall accept `sequential` (default), `dialectic`, or `trias`.
- `--skeptic-can-override` (flag, Dialectic only) shall set `skeptic_can_override=True`.
- `consilium check --diff <ref>` shall run `git diff <ref>`, use the diff as context, and deliberate with the proposal `"Review this diff (git diff <ref>)"`.
- `consilium check` (no `--diff`) shall run `git diff --staged` and deliberate on staged changes.
- If the diff is empty, `check` shall exit with an error message rather than calling the API.
- Non-zero exit codes from `git diff` shall propagate as `ClickException`.

## WHAT — Verify intent

- Should `consilium check` with an empty working tree and no staged changes succeed silently or error? Currently it errors with "No diff found."

## HOW — Acceptance

- Given `--output json`, when `deliberate_cmd` runs, then output is valid JSON parseable as a `Report`.
- Given `--diff HEAD~1` with a real git repo, when `check_cmd` runs, then `deliberate` is called with the diff as context.
- Given an empty diff, when `check_cmd` runs, then a `ClickException` is raised with "No diff found."

## WHERE — Current implementation

- `src/consilium/cli.py`
