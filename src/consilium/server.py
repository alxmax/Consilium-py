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

from fastapi.responses import HTMLResponse
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


_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Consilium</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; background: #0f0f0f; color: #e0e0e0; }
  h1 { font-size: 1.4rem; margin-bottom: 4px; }
  p.sub { color: #888; margin-top: 0; font-size: .9rem; }
  textarea { width: 100%; box-sizing: border-box; height: 100px; background: #1a1a1a; color: #e0e0e0; border: 1px solid #333; border-radius: 6px; padding: 10px; font-size: .95rem; resize: vertical; }
  button { margin-top: 10px; padding: 8px 20px; background: #2563eb; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: .95rem; }
  button:disabled { opacity: .5; cursor: default; }
  #status { margin-top: 12px; color: #888; font-size: .85rem; }
  #result { margin-top: 20px; }
  .verdict { font-size: 1.6rem; font-weight: bold; margin-bottom: 4px; }
  .GO { color: #4ade80; } .MODIFY { color: #facc15; } .STOP { color: #f87171; } .BLOCK { color: #f87171; }
  .rec { color: #cbd5e1; margin-bottom: 16px; }
  .sketch { background: #1a1a1a; border: 1px solid #333; border-radius: 6px; padding: 12px; font-size: .85rem; white-space: pre-wrap; }
  .conf { color: #888; font-size: .85rem; }
</style>
</head>
<body>
<h1>Consilium</h1>
<p class="sub">Dialectical deliberation — enter a proposed change and get a verdict.</p>
<textarea id="proposal" placeholder="e.g. Add a /health endpoint to the FastAPI server"></textarea>
<br>
<button id="btn" onclick="run()">Deliberate</button>
<div id="status"></div>
<div id="result"></div>
<script>
async function run() {
  const proposal = document.getElementById('proposal').value.trim();
  if (!proposal) return;
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');
  const result = document.getElementById('result');
  btn.disabled = true;
  status.textContent = 'Deliberating… (15–60 s)';
  result.innerHTML = '';
  try {
    const res = await fetch('/deliberate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({proposal})
    });
    const d = await res.json();
    if (!res.ok) { status.textContent = 'Error: ' + (d.detail || res.status); return; }
    const vc = d.verdict || 'UNKNOWN';
    let html = '<div class="verdict ' + vc + '">' + vc + '</div>';
    html += '<div class="conf">confidence ' + (d.confidence !== null ? (d.confidence * 100).toFixed(0) + '%' : '—') + ' &nbsp;·&nbsp; mode ' + (d.mode || '—') + '</div>';
    html += '<div class="rec">' + (d.recommendation || '') + '</div>';
    if (d.chosen_sketch) {
      html += '<div style="margin-bottom:6px;font-size:.85rem;color:#94a3b8">How to implement (' + d.chosen + '):</div>';
      html += '<div class="sketch">' + d.chosen_sketch + '</div>';
    }
    result.innerHTML = html;
    status.textContent = '';
  } catch(e) {
    status.textContent = 'Request failed: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}
document.getElementById('proposal').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run();
});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return _UI


@app.post("/deliberate", response_model=Report)
def run_deliberate(req: DeliberateRequest) -> Report:
    kwargs: dict = dict(proposal=req.proposal, context=req.context, mode=req.mode)
    if req.model:
        kwargs["model"] = req.model
    return deliberate(**kwargs)
