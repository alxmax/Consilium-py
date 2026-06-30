"""Provider-error classification, shared by cli.py and server.py.

Framework-free by design (no click, no fastapi) so both the CLI and the HTTP
server can depend on it without an inverted import (server.py must not import
from the click-based cli.py).
"""
from __future__ import annotations


def is_provider_error(e: BaseException) -> bool:
    root = (type(e).__module__ or "").split(".")[0]
    if root in ("litellm", "openai"):
        return True
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        return False
    return isinstance(e, anthropic.APIError)


def provider_error_message(e: BaseException, model: str | None) -> str:
    """Human-readable, actionable message for a provider failure."""
    status = getattr(e, "status_code", None)
    model = model or "the configured model"
    if status in (401, 403, 404):
        kind = "not found or retired" if status == 404 else "rejected (auth / permission)"
        return (
            f"Model {model!r} {kind} (HTTP {status}) — not transient. "
            "Set CONSILIUM_MODEL=claude-cli to use your local Claude subscription."
        )
    detail = f" (HTTP {status})" if status else ""
    return (
        f"Model provider unavailable{detail} — try again shortly, or set "
        "CONSILIUM_MODEL=claude-cli to use your local Claude subscription."
    )
