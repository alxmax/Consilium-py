"""Voice prompt loading, API dispatch, and JSON extraction.
# implements: CPYBUS-VOI-001
# implements: CPYEXT-LTL-001
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import anthropic

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "voices"

_client: anthropic.Anthropic | None = None

# Per-call usage log for the claude_cli backend (cost / tokens / duration).
# Cleared + read by experiment harnesses to measure a deliberation's footprint.
_CLI_USAGE: list[dict] = []


def _call_claude_cli(system_prompt: str, user_msg: str, model: str) -> str:
    """Route a voice call through the authenticated `claude -p` CLI instead of the
    Anthropic SDK. Enabled with env CONSILIUM_BACKEND=claude_cli — lets the package
    run without ANTHROPIC_API_KEY (uses the Claude Code session auth). One subprocess
    per voice call.
    """
    prompt = f"{system_prompt}\n\n---\n\n{user_msg}"
    claude = shutil.which("claude") or "claude"
    # Single-turn text generation only: --max-turns 1 keeps it a plain completion
    # (no tools, no autonomous loop, no permission bypass) — a voice just emits JSON.
    cmd = [claude, "-p", "--model", model,
           "--output-format", "json", "--max-turns", "1"]
    proc = subprocess.run(cmd, input=prompt, capture_output=True,
                          text=True, encoding="utf-8", timeout=900)
    if not (proc.stdout or "").strip():
        raise RuntimeError(f"claude -p returned empty output (rc={proc.returncode}): "
                           f"{(proc.stderr or '')[:300]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout
    u = data.get("usage", {}) or {}
    _CLI_USAGE.append({
        "cost": data.get("total_cost_usd", 0.0),
        "api_ms": data.get("duration_api_ms", data.get("duration_ms", 0)),
        "in": u.get("input_tokens", 0),
        "out": u.get("output_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
    })
    return data.get("result", "")


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
    if os.environ.get("CONSILIUM_BACKEND") == "claude_cli":
        return _call_claude_cli(system_prompt, user_msg, model)

    if "/" in model:
        try:
            import litellm  # noqa: PLC0415
        except ImportError:
            raise ImportError(
                f"Model {model!r} requires LiteLLM. "
                "Run: pip install 'consilium-py[litellm]'"
            )
        response = litellm.completion(
            model=model,
            max_tokens=4096,
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
