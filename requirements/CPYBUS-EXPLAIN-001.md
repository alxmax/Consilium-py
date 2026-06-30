---
id: CPYBUS-EXPLAIN-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-VOI-001]
---

# Codebase explanation — explain_module and the explain CLI command

Stateless, single-call_voice-dispatch summary of a Python file or directory: what it does,
its public API, dependencies, data flow, and gotchas — exposed as `consilium explain <path>`.

## WHAT — Contract

- `explain_module(path, model)` shall accept either a single `.py` file or a directory; for a
  directory it shall collect Python files via `rglob("*.py")`, sorted, capped at `_MAX_FILES`
  (20) files and `_MAX_CHARS` (40,000) combined characters — truncating with a
  `[truncated — char limit reached]` marker rather than overflowing the model's context window.
- If no Python files are found at `path`, `explain_module` shall return an `ExplainReport` whose
  `summary` states `No Python files found at <path>.`, without dispatching to `call_voice`.
- Otherwise it shall concatenate each file's source (prefixed with a `# <path>` header) into one
  user message, load the `explain` system prompt via `load_prompt("explain")`, and dispatch a
  single `call_voice("explain", system_prompt, combined, model)` call.
- The voice response shall be parsed with `extract_json`; the resulting `ExplainReport` populates
  `summary`, `public_api`, `dependencies`, `data_flow`, and `gotchas` from the parsed JSON (each
  defaulting to `[]`/`""` when absent).
- If the voice response is not valid JSON (no `summary` key extracted), `explain_module` shall
  fall back to using the first 300 characters of the raw response, stripped, as `summary` —
  never raise on a parse failure.
- `consilium explain <path>` shall call `explain_module(path, model)` and print, in text mode,
  the summary followed by `Public API` / `Dependencies` / `Data flow` / `Gotchas` sections (each
  omitted when empty); with `--output json`, it shall print `report.model_dump()` as JSON.
- A provider error raised by `explain_module` (per the CLI's shared `_is_provider_error` check,
  see CPYBUS-CLI-001) shall surface as a `ClickException`, not a raw traceback; a non-provider
  exception propagates unchanged.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given a directory with one `.py` file and a voice response containing valid JSON, when
  `explain_module` is called, then the returned `ExplainReport.summary` is non-empty and matches
  the JSON's `summary` field.
- Given a directory with no `.py` files, when `explain_module` is called, then `summary` contains
  "No Python files" and `call_voice` is never invoked.
- Given a voice response that is plain prose (no JSON), when `explain_module` is called, then
  `summary` equals the prose response.
- Given a directory with more than `_MAX_FILES` Python files, when `explain_module` is called,
  then the user message sent to `call_voice` contains at most `_MAX_FILES` `# <path>.py` headers.
- Given `consilium explain <file>` with a mocked valid JSON response, when invoked via the CLI,
  then exit code is 0 and the summary text appears in stdout; with `--output json`, stdout parses
  as JSON containing a `summary` key.

## WHERE — Current implementation

- `src/consilium/explain.py`
- `src/consilium/cli.py` (`explain_cmd`)
