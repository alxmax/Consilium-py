"""FastAPI HTTP server for consilium-py. Requires `pip install 'consilium-py[server]'`.

Start with:
    uvicorn consilium.server:app --reload

POST /deliberate  →  returns a consilium Report (expect 15–60 s while voices deliberate).
"""
# implements: CPYSRV-HTTP-001
from __future__ import annotations

try:
    from fastapi import FastAPI
except ImportError:
    raise ImportError(
        "The HTTP server requires the [server] extra. "
        "Run: pip install 'consilium-py[server]'"
    )

import logging
from contextlib import asynccontextmanager

from pydantic import BaseModel

from consilium import deliberate
from consilium.models import Report

logger = logging.getLogger("consilium.server")


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[type-arg]
    logger.info("consilium server ready — POST /deliberate (expect 15–60 s per request)")
    yield


app = FastAPI(
    title="consilium-py",
    description="Dialectical code-change deliberation over HTTP.",
    lifespan=_lifespan,
)


class DeliberateRequest(BaseModel):
    proposal: str
    context: str = ""
    mode: str = "sequential"
    model: str = ""


@app.post("/deliberate", response_model=Report)
def run_deliberate(req: DeliberateRequest) -> Report:
    kwargs: dict = dict(proposal=req.proposal, context=req.context, mode=req.mode)
    if req.model:
        kwargs["model"] = req.model
    return deliberate(**kwargs)
