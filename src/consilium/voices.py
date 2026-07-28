"""Voice prompt loading, API dispatch, and JSON extraction."""
# implements: CPYBUS-VOI-001
# implements: CPYEXT-LTL-001
from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any, cast

import anthropic

# Prompts ship inside the package (src/consilium/prompts/) so a wheel install
# works; the old repo-root prompts/ path only existed in editable installs.
PROMPTS_DIR = files("consilium") / "prompts" / "voices"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def extract_json(text: str) -> dict[str, Any]:
    """Extract first JSON object from text, handling markdown fences.

    strict=False is deliberate: `claude -p` voices routinely emit LITERAL newlines
    (and tabs) inside string values — e.g. a multi-line `notes`/`assert` field in
    the Control verdict — which strict JSON rejects, collapsing the whole voice to
    {} ("unparseable") even though the structure is fine. strict=False accepts those
    control chars as data; it never accepts anything a strict parse would reject as
    malformed structure, so it only widens tolerance, never correctness.
    """
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1), strict=False)
        except json.JSONDecodeError:
            pass

    # Brace-depth counting on raw characters mis-tracks braces that appear
    # inside JSON string values (e.g. a "sketch" field containing pseudocode
    # like "if (x) { return y; }"), truncating the slice and silently
    # producing {}. raw_decode() uses the real JSON tokenizer, so it is
    # string-boundary aware; retry from each subsequent '{' if a given start
    # position isn't valid JSON (e.g. a brace in surrounding prose).
    decoder = json.JSONDecoder(strict=False)
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            start = text.find("{", start + 1)

    return {}


# Voices whose contract is a JSON object (parsed downstream by extract_json).
# The `assistant` (plain_answer/short_response) and `explain` voices return prose
# and must never be JSON-retried.
_JSON_VOICES = frozenset({"generator", "conservator", "control", "skeptic"})
_CLI_JSON_RETRIES = 2  # extra attempts (3 total) when a JSON voice drifts to prose


def call_voice(_voice_name: str, system_prompt: str, user_msg: str, model: str) -> str:
    if model == "claude-cli" or model.startswith("claude-cli:"):
        # Dispatch each voice through the Claude Code CLI (`claude -p`), reusing the
        # local subscription auth instead of an API key. Note: each call reloads the
        # full Claude Code harness, so this is a demo/no-key path — NOT the lean
        # direct-API dispatch that makes the LangGraph mode cheap.
        import shutil  # noqa: PLC0415
        import subprocess  # noqa: PLC0415

        # "claude-cli" runs Sonnet; "claude-cli:<name>" picks any model alias the
        # local CLI accepts (e.g. claude-cli:opus) — the user's choice is honored
        # instead of silently pinned.
        cli_model = model.partition(":")[2] or "sonnet"
        claude_bin = shutil.which("claude") or "claude"  # resolve .CMD/.exe shim on Windows
        # The <SUBAGENT-STOP> header tells the global using-superpowers skill to
        # skip its "invoke skills before responding" loop, so the voice gets a
        # clean completion instead of XML tool-call preambles.  --tools none
        # removes all built-in and MCP tools so Claude can't execute anything
        # from the prompt (anti-hijack), and with no tools available it never
        # burns turns on blocked attempts.
        base = f"<SUBAGENT-STOP>\nYou are a subagent dispatched to perform a specific evaluation. Respond with plain text only — no tool calls.\n</SUBAGENT-STOP>\n\n{system_prompt}\n\n{user_msg}"
        # `claude -p` (the full Claude Code harness, tuned to be conversational)
        # intermittently answers a JSON voice in prose/markdown instead of the
        # required schema (~10-25% per call). extract_json then yields {} and the
        # aggregator collapses the whole run to BLOCK. Since a 3-voice run compounds
        # this to ~30-50%, retry a JSON voice (only) when its output has no parseable
        # object, nudging harder each time. Prose voices (assistant/explain) skip this.
        expects_json = _voice_name in _JSON_VOICES
        last_out = ""
        for attempt in range(_CLI_JSON_RETRIES + 1):
            full = base
            if expects_json and attempt:
                full += (
                    "\n\nIMPORTANT: your previous reply was not valid JSON. Reply with "
                    "ONLY the JSON object required for your role, inside a ```json fence — "
                    "no prose, headings, or commentary before or after it."
                )
            proc = subprocess.run(
                [
                    claude_bin, "--model", cli_model, "--output-format", "text",
                    "--max-turns", "1",
                    "--tools", "none",
                    "-p",
                ],
                input=full, capture_output=True, text=True, encoding="utf-8", timeout=240,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"claude -p failed ({proc.returncode}): {proc.stderr[:300]}")
            last_out = proc.stdout
            if not expects_json or extract_json(last_out):
                return last_out
        return last_out  # exhausted retries — let the aggregator flag it, as before

    if "/" in model:
        import litellm  # noqa: PLC0415
        from litellm import ModelResponse  # noqa: PLC0415
        # Silence LiteLLM's "Give Feedback / Get Help" + "LiteLLM.Info" stderr
        # footer, which it prints on a transient error even when num_retries
        # recovers the call. Unrecovered errors still propagate.
        litellm.suppress_debug_info = True
        response = litellm.completion(
            model=model,
            max_tokens=4096,
            # Retry transient provider errors (e.g. Gemini free/paid-tier 503
            # "high demand", 429 rate limits) with exponential backoff.
            num_retries=3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
        )
        # litellm.completion() is typed as ModelResponse | CustomStreamWrapper
        # (overloaded on `stream`); without stream=True it always returns
        # ModelResponse at runtime. cast() narrows the type without changing
        # behavior.
        response = cast(ModelResponse, response)
        return response.choices[0].message.content or ""

    response = _get_client().messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


_PLAIN_ANSWER_SYSTEM = (
    "You are a helpful assistant. The user's message is not a code change or "
    "decision to deliberate — just answer it directly and concisely."
)


def _with_context(user_msg: str, context: str) -> str:
    """Prepend retrieved context to the user message, or return it unchanged.

    The bypass answer paths take `user_msg` only; without this the RAG block
    `deliberate()` builds is discarded and the reply is silently ungrounded.
    """
    if not context.strip():
        return user_msg
    return f"{context}\n\n---\n\n{user_msg}"


def plain_answer(user_msg: str, model: str, context: str = "") -> str:
    """Single conversational reply for input that is not a deliberation
    (greeting / chit-chat / empty). Routes through `call_voice`, so it honors the
    same Anthropic-vs-LiteLLM dispatch as the deliberating voices.

    `context` carries any retrieved RAG block so the reply is grounded in the
    same material a full deliberation would have seen.
    """
    return call_voice(
        "assistant", _PLAIN_ANSWER_SYSTEM, _with_context(user_msg, context), model
    )


_SHORT_RESPONSE_SYSTEM = (
    "The deliberation found this a low-risk, trivial request, so the long form is "
    "overkill. Give a direct, useful response to the user's input in at most 2 "
    "sentences."
)


def short_response(user_msg: str, model: str, context: str = "") -> str:
    """Concise reply for the scale_down (compressed) path, where a full
    deliberation is overkill. Produces the actual short response the path
    promises, instead of leaking the 'give a short response' instruction."""
    return call_voice(
        "assistant", _SHORT_RESPONSE_SYSTEM, _with_context(user_msg, context), model
    )
