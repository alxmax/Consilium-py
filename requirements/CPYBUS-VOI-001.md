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

- `load_prompt(name)` shall read `prompts/voices/{name}.md` from inside the installed `consilium` package (via `importlib.resources`), so prompts ship in the wheel and non-editable installs work.
- `call_voice(_voice_name, system_prompt, user_msg, model)` shall call `client.messages.create` with `max_tokens=4096` and return the text of the first `TextBlock` in the response. If no `TextBlock` is present, it returns an empty string. When `"/" in model`, it routes to `litellm.completion()` instead (see CPYEXT-LTL-001); the Anthropic path is unchanged. No retry logic exists — retry is the caller's responsibility.
- `extract_json(text)` shall return the first valid JSON object found in `text`. It checks, in order: (1) a fenced code block ` ```json … ``` ` or ` ``` … ``` `; (2) the first `{…}` span in the raw text matched by brace depth. On failure it returns `{}`.
- `looks_like_envelope(voice_name, parsed)` shall report whether a parsed dict is a voice's OUTER object rather than a fragment of one. `extract_json` alone cannot answer this: its brace-walk fallback retries `raw_decode` from each successive `{`, so on TRUNCATED output it skips the unclosed outer object and returns the first complete INNER one — a single candidate/score/verdict — which is truthy and therefore indistinguishable from success by a `bool()` check. The predicate accepts when any of the voice's registered envelope keys is present (`VOICE_ENVELOPE_KEYS`: generator `candidates`/`options`, conservator `scores`, control `verdicts`/`glossary`/`glossary_fail`/`disagreements`, skeptic `can_object` — several per voice because the aggregator genuinely tolerates more than one shape, e.g. Generator's legacy `options`), and otherwise rejects only dicts carrying a top-level `id`, the signature every list-element fragment has and no envelope has. It is deliberately permissive on unrecognised shapes so an unregistered voice degrades to the previous truthiness behaviour instead of hard-failing every run. Every voice in `_JSON_VOICES` shall have registered envelope keys.
- The `claude -p` CLI path shall gate its per-voice JSON retry on `looks_like_envelope`, not on truthiness, so a reply truncated into a nested fragment consumes a real retry attempt instead of counting as success on the first.
- Every prompt in `_JSON_VOICES` shall state its output discipline — reply with only the JSON object, no prose before or after, close the fence — in its own `## Output format` section, so the rule applies to the FIRST attempt. It was previously only appended by the CLI retry from attempt 2 on, which measurably cost an extra spawn per flaky reply: voices emit their JSON in a fence and then add prose commentary, and when the model flows into prose without closing the fence the fenced-block branch of `extract_json` fails (`stop_reason` was `end_turn`, so this is not a token cap). The clause is shared verbatim and shall stay **schema-neutral** — it must name no envelope key, because `skeptic`'s envelope (`can_object`) is not list-shaped like the other three. Prose voices (`assistant`, `explain`) shall NOT carry it.
- The Anthropic client shall be created lazily (on first call) so importing the package does not require `ANTHROPIC_API_KEY` to be set at import time.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given a prompt file exists at `src/consilium/prompts/voices/conservator.md`, when `load_prompt("conservator")` is called, then the returned string equals the file's content.
- Given a response containing ` ```json {"key": 1} ``` `, when `extract_json` is called, then `{"key": 1}` is returned.
- Given a response containing `{"key": 1}` with no fence, when `extract_json` is called, then `{"key": 1}` is returned.
- Given a response with no JSON, when `extract_json` is called, then `{}` is returned.
- Given a Generator reply truncated mid-string so its outer object never closes, when `extract_json` is called, then a nested candidate object is returned (unchanged behaviour) and `looks_like_envelope("generator", …)` is `False` (tested-by `tests/test_voices.py::test_extract_json_still_recovers_the_nested_fragment` and `test_envelope_gate_rejects_the_nested_fragment`).
- Given any voice in `_JSON_VOICES`, when `load_prompt(name)` is read, then it contains the no-trailing-prose clause, that clause names no envelope key, and the prose voices do not carry it (tested-by `tests/test_voices.py::test_json_voices_carry_the_output_discipline_clause_on_attempt_one`, `test_the_clause_is_schema_neutral`, `test_prose_voices_do_not_get_the_json_clause`).
- Given a complete voice output, when `looks_like_envelope` is called, then it is `True` — including an abstain-only Generator whose `candidates` list is empty (key presence, not non-emptiness) and a Generator using the legacy `options` key (tested-by `test_envelope_gate_tests_key_presence_not_emptiness` and `test_envelope_gate_accepts_the_shapes_the_aggregator_actually_tolerates`).

## WHERE — Current implementation

- `src/consilium/voices.py`
