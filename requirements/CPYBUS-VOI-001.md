---
id: CPYBUS-VOI-001
status: confirmed
layer: bus
owner: human
depends_on: []
---

# Voice dispatch — prompt loading, API call, JSON extraction

The foundational I/O primitive shared by all deliberation modes. Loads a voice's system prompt from disk, calls the Anthropic Messages API, and extracts the first JSON object from the response text.

## WHAT — Contract

- `load_prompt(name)` shall read `prompts/voices/{name}.md` relative to the package root and return its full text.
- `call_voice(_voice_name, system_prompt, user_msg, model)` shall call `client.messages.create` with `max_tokens=4096` and return the text of the first `TextBlock` in the response. If no `TextBlock` is present, it returns an empty string. When `"/" in model`, it routes to `litellm.completion()` instead (see CPYEXT-LTL-001); the Anthropic path is unchanged. No retry logic exists — retry is the caller's responsibility.
- `extract_json(text)` shall return the first valid JSON object found in `text`. It checks, in order: (1) a fenced code block ` ```json … ``` ` or ` ``` … ``` `; (2) the first `{…}` span in the raw text matched by brace depth. On failure it returns `{}`.
- The Anthropic client shall be created lazily (on first call) so importing the package does not require `ANTHROPIC_API_KEY` to be set at import time.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given a prompt file exists at `prompts/voices/conservator.md`, when `load_prompt("conservator")` is called, then the returned string equals the file's content.
- Given a response containing ` ```json {"key": 1} ``` `, when `extract_json` is called, then `{"key": 1}` is returned.
- Given a response containing `{"key": 1}` with no fence, when `extract_json` is called, then `{"key": 1}` is returned.
- Given a response with no JSON, when `extract_json` is called, then `{}` is returned.

## WHERE — Current implementation

- `src/consilium/voices.py`
