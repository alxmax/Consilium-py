"""Chat Q&A surface — retrieve, then answer.

A separate module from the deliberation pipeline on purpose. A question typed
into a chat box is not a code-change proposal: the Generator flags it
`not_a_proposal`, `deliberate()` throws the whole pipeline result away, and a
single reply is produced anyway. Routing chat through `deliberate()` therefore
pays for 3-10 voice calls to reach a one-call answer.

So `ask()` retrieves and answers directly. The full deliberation is still one
argument away — pass `mode=` — for input that really is a proposal.
"""
# implements: CPYBUS-CHAT-001
from __future__ import annotations

import os

from consilium import _SUPPORTED_MODES, deliberate
from consilium.models import DEFAULT_MODEL as _DEFAULT_MODEL
from consilium.models import Report
from consilium.voices import plain_answer


def ask(
    question: str,
    model: str = _DEFAULT_MODEL,
    rag: bool = True,
    mode: str | None = None,
    tenant: str | None = None,
    context: str = "",
) -> Report:
    """Answer `question`, grounded in the ingested-doc corpus.

    `mode=None` (default) retrieves and answers in a single model call. Passing a
    mode from `_SUPPORTED_MODES` runs the full deliberation instead.

    Unlike `deliberate()`, RAG is **on** by default — grounding is the point of a
    Q&A surface, whereas a deliberation is usually about a diff in hand.

    `context` lets a caller supply its own grounding text (e.g. a host app's own
    deterministic facts) independent of RAG retrieval. It is prepended to whatever
    RAG contributes when `rag=True`, and is the only source of context when
    `rag=False` — callers with no ingested corpus are not limited to an ungrounded
    reply.
    """
    model = os.environ.get("CONSILIUM_MODEL", model)

    if mode is not None:
        if mode not in _SUPPORTED_MODES:
            raise ValueError(
                f"Unknown mode: {mode!r}. Supported: {', '.join(_SUPPORTED_MODES)}"
            )
        return deliberate(question, model=model, mode=mode, rag=rag, tenant=tenant)

    sources: list[str] = []
    if rag:
        from consilium.rag import build_rag_bundle  # noqa: PLC0415
        rag_context, sources = build_rag_bundle(question, tenant=tenant)
        if rag_context:
            context = f"{context}\n\n{rag_context}" if context else rag_context

    return Report(
        verdict="ANSWER",
        confidence=0.0,
        recommendation=plain_answer(question, model, context=context),
        voices=[],
        reason="chat_answer",
        pipeline_executed=False,
        mode="chat",
        sources=sources,
    )
