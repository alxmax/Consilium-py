---
id: CPYBUS-CLI-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-API-001]
---

# CLI interface — deliberate and check commands

Exposes the deliberation engine as a terminal command (`consilium`) with two subcommands: `deliberate` (for a free-text proposal) and `check` (for deliberating on a git diff).

## WHAT — Contract

- `consilium deliberate "<proposal>"` shall call `deliberate()` with the given proposal and print verdict, confidence, mode, and recommendation in text format, or full JSON with `--output json`.
- For an actionable verdict (`GO` or `MODIFY`) whose `Report` carries a `chosen_sketch`, text output shall print a "How to implement (`<chosen>`)" block: the `chosen_summary` (when present), the `chosen_sketch`, and the `chosen_rationale` prefixed "Why:". A `STOP`/`BLOCK` verdict carries no chosen approach, so the block is suppressed.
- Bounded clarify on a non-proposal: when `deliberate()` returns `reason == "not_a_proposal"`, output is `text`, and stdin is a TTY (an interactive session — guarded by `_stdin_is_tty()`, which tests patch), the CLI shall print the `BLOCK` report and then prompt ONCE for a concrete rephrase. A non-empty rephrase is re-deliberated (same `mode`/`model`/flags) and its report printed; an empty response leaves the original `BLOCK` guidance standing. Non-interactive (piped/CI) callers and `--output json` skip the prompt entirely and keep the `BLOCK` sentinel unchanged — so the human, never an LLM, supplies the proposal that gets deliberated.
- `--context <path>` (repeatable) shall read each file and concatenate its content into the `context` argument. Multiple `-c` flags are supported.
- `--mode` shall accept `sequential` (default), `dialectic`, `trias`, and `langgraph`.
- `--model` shall default to `claude-sonnet-4-6` and also read the `CONSILIUM_MODEL` env var (Click `envvar=`), making `export CONSILIUM_MODEL=openai/gpt-4o` equivalent to `--model openai/gpt-4o`.
- `--skeptic-can-override` (flag, Dialectic only) shall set `skeptic_can_override=True`.
- `--rag` (flag) shall pass `rag=True` to `deliberate()`, enabling RAG context injection.
- `consilium check --diff <ref>` shall run `git diff <ref>`, use the diff as context, and deliberate with the proposal `"Review this diff (git diff <ref>)"`.
- `consilium check` (no `--diff`) shall run `git diff --staged` and deliberate on staged changes.
- If the diff is empty, `check` shall exit with an error ("No diff found.") rather than calling the API. Deliberating an empty diff has no meaningful output.
- Non-zero exit codes from `git diff` shall propagate as `ClickException`.
- `consilium index` shall index all runs in `~/.consilium/runs/` into the ChromaDB vector store (requires `[rag]` extra).

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `--output json`, when `deliberate_cmd` runs, then output is valid JSON parseable as a `Report`.
- Given `--diff HEAD~1` with a real git repo, when `check_cmd` runs, then `deliberate` is called with the diff as context.
- Given an empty diff, when `check_cmd` runs, then a `ClickException` is raised with "No diff found."
- Given a `GO` verdict carrying a `chosen_sketch` in text mode, when `deliberate_cmd` runs, then output contains "How to implement (`<chosen>`)", the sketch, and "Why:"; given a `STOP` verdict, no such block is printed.
- Given `reason == "not_a_proposal"` on a non-TTY stdin, when `deliberate_cmd` runs, then `deliberate` is called once and the `BLOCK` guidance is printed with no prompt; on a TTY with a non-empty rephrase, `deliberate` is called twice, the second call with the rephrased proposal (tested-by `tests/test_cli_io.py`).

## WHERE — Current implementation

- `src/consilium/cli.py`
