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
- When the report's verdict is `ANSWER` — a non-deliberation input (greeting / chit-chat) answered directly, see CPYBUS-API-001 — text output shall print only the reply (`recommendation`), with no verdict / confidence / mode header and no how-to-implement block.
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
- A transient model-provider failure (an exception whose root module is `litellm` or `openai`, or an `anthropic.APIError` — e.g. a `503` / rate limit / timeout) shall surface as a clean `ClickException` suggesting a retry or a model switch, not a raw traceback. A non-provider exception propagates unchanged so real bugs are never masked.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `--output json`, when `deliberate_cmd` runs, then output is valid JSON parseable as a `Report`.
- Given `--diff HEAD~1` with a real git repo, when `check_cmd` runs, then `deliberate` is called with the diff as context.
- Given an empty diff, when `check_cmd` runs, then a `ClickException` is raised with "No diff found."
- Given a `GO` verdict carrying a `chosen_sketch` in text mode, when `deliberate_cmd` runs, then output contains "How to implement (`<chosen>`)", the sketch, and "Why:"; given a `STOP` verdict, no such block is printed.
- Given a report with verdict `ANSWER`, when `deliberate_cmd` runs in text mode, then output contains the reply and no `Verdict:` / `Confidence:` header (tested-by `tests/test_cli_io.py::TestAnswerOutput`).
- Given `deliberate()` raises a provider error (exception module `litellm`/`openai`, or `anthropic.APIError`), when `deliberate_cmd` runs, then the CLI exits non-zero with a message naming the provider and no traceback; a non-provider exception is not masked (tested-by `tests/test_cli_io.py::TestProviderError`).

## WHERE — Current implementation

- `src/consilium/cli.py`
