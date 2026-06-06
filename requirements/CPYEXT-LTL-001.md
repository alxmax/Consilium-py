---
id: CPYEXT-LTL-001
status: confirmed
layer: feature
owner: human
depends_on: [CPYBUS-VOI-001, CPYBUS-API-001, CPYBUS-CLI-001]
---

# Provider-agnostic voice dispatch via LiteLLM

Optional `[litellm]` extra that makes every voice call provider-agnostic. When the model string contains `"/"` (the LiteLLM convention for `"provider/model"`), `call_voice()` routes to `litellm.completion()` instead of the Anthropic SDK. The env var `CONSILIUM_MODEL` lets callers override the model globally without changing code.

## WHAT — Contract

- `call_voice()` shall detect the routing at call time: if `"/" in model`, use `litellm.completion()`; otherwise use the existing Anthropic SDK path. Both paths coexist in the same function; no existing call site changes.
- The LiteLLM call shall use `model=model`, `max_tokens=4096`, and a `messages` list with `{"role": "system", "content": system_prompt}` followed by `{"role": "user", "content": user_msg}`.
- The return value from the LiteLLM path shall be `response.choices[0].message.content or ""`.
- When `litellm` is not installed and model contains `"/"`, `call_voice()` shall raise `ImportError` with a `pip install 'consilium-py[litellm]'` hint.
- `deliberate()` shall read `CONSILIUM_MODEL` from the environment before any voice runs. When set, it overrides the `model` parameter for that call.
- The CLI `--model` option shall read `CONSILIUM_MODEL` via Click's `envvar=` parameter, making `export CONSILIUM_MODEL=openai/gpt-4o` equivalent to `--model openai/gpt-4o`.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `call_voice("g", sys, usr, "openai/gpt-4o")` with litellm mocked, when called, then `litellm.completion` is called with `model="openai/gpt-4o"`.
- Given `call_voice("g", sys, usr, "openai/gpt-4o")` with litellm absent from sys.modules, when called, then `ImportError` is raised containing `"consilium-py[litellm]"`.
- Given `call_voice("c", sys, usr, "claude-sonnet-4-6")` (no `"/"`), when called, then the Anthropic SDK path is used and litellm is not imported.
- Given `CONSILIUM_MODEL=claude-haiku-4-5` in the environment, when `deliberate("test", model="claude-sonnet-4-6")` is called, then all voice calls receive `claude-haiku-4-5` as the model.

## WHERE — Current implementation

- `src/consilium/voices.py` (slash-dispatch in `call_voice()`)
- `src/consilium/__init__.py` (`CONSILIUM_MODEL` env var in `deliberate()`)
- `src/consilium/cli.py` (`envvar="CONSILIUM_MODEL"` on `--model` options)
- `pyproject.toml` (`[litellm]` extra: `litellm>=1.0`)
