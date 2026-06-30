"""Voice prompt loading, API dispatch, and JSON extraction."""
# implements: CPYBUS-VOI-001
# implements: CPYEXT-LTL-001
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import anthropic

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "voices"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def extract_json(text: str) -> dict[str, Any]:
    """Extract first JSON object from text, handling markdown fences."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # Brace-depth counting on raw characters mis-tracks braces that appear
    # inside JSON string values (e.g. a "sketch" field containing pseudocode
    # like "if (x) { return y; }"), truncating the slice and silently
    # producing {}. raw_decode() uses the real JSON tokenizer, so it is
    # string-boundary aware; retry from each subsequent '{' if a given start
    # position isn't valid JSON (e.g. a brace in surrounding prose).
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
            return obj
        except json.JSONDecodeError:
            start = text.find("{", start + 1)

    return {}


def call_voice(_voice_name: str, system_prompt: str, user_msg: str, model: str) -> str:
    if model == "claude-cli":
        # Dispatch each voice through the Claude Code CLI (`claude -p`), reusing the
        # local subscription auth instead of an API key. Note: each call reloads the
        # full Claude Code harness, so this is a demo/no-key path — NOT the lean
        # direct-API dispatch that makes the LangGraph mode cheap.
        import shutil  # noqa: PLC0415
        import subprocess  # noqa: PLC0415

        claude_bin = shutil.which("claude") or "claude"  # resolve .CMD/.exe shim on Windows
        # The <SUBAGENT-STOP> header tells the global using-superpowers skill to
        # skip its "invoke skills before responding" loop, so the voice gets a
        # clean completion instead of XML tool-call preambles.  --tools none
        # removes all built-in and MCP tools so Claude can't execute anything
        # from the prompt (anti-hijack), and with no tools available it never
        # burns turns on blocked attempts.
        full = f"<SUBAGENT-STOP>\nYou are a subagent dispatched to perform a specific evaluation. Respond with plain text only — no tool calls.\n</SUBAGENT-STOP>\n\n{system_prompt}\n\n{user_msg}"
        proc = subprocess.run(
            [
                claude_bin, "--model", "sonnet", "--output-format", "text",
                "--max-turns", "1",
                "--tools", "none",
                "-p",
            ],
            input=full, capture_output=True, text=True, encoding="utf-8", timeout=240,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude -p failed ({proc.returncode}): {proc.stderr[:300]}")
        return proc.stdout

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


def plain_answer(user_msg: str, model: str) -> str:
    """Single conversational reply for input that is not a deliberation
    (greeting / chit-chat / empty). Routes through `call_voice`, so it honors the
    same Anthropic-vs-LiteLLM dispatch as the deliberating voices."""
    return call_voice("assistant", _PLAIN_ANSWER_SYSTEM, user_msg, model)


_SHORT_RESPONSE_SYSTEM = (
    "The deliberation found this a low-risk, trivial request, so the long form is "
    "overkill. Give a direct, useful response to the user's input in at most 2 "
    "sentences."
)


def short_response(user_msg: str, model: str) -> str:
    """Concise reply for the scale_down (compressed) path, where a full
    deliberation is overkill. Produces the actual short response the path
    promises, instead of leaking the 'give a short response' instruction."""
    return call_voice("assistant", _SHORT_RESPONSE_SYSTEM, user_msg, model)
