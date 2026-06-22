"""Voice prompt loading, API dispatch, and JSON extraction."""
# implements: CPYBUS-VOI-001
# implements: CPYEXT-LTL-001
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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

    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    return {}


def call_voice(_voice_name: str, system_prompt: str, user_msg: str, model: str) -> str:
    if "/" in model:
        try:
            import litellm  # noqa: PLC0415
        except ImportError:
            raise ImportError(
                f"Model {model!r} requires LiteLLM. "
                "Run: pip install 'consilium-py[litellm]'"
            )
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
