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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Consilium</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; max-width: 760px; margin: 0 auto; padding: 32px 16px 64px; background: #0f0f0f; color: #e0e0e0; }
  h1 { font-size: 1.5rem; font-weight: 700; margin: 0 0 4px; letter-spacing: -.02em; }
  .sub { color: #666; margin: 0 0 28px; font-size: .9rem; }

  label { display: block; font-size: .8rem; color: #888; margin-bottom: 6px; letter-spacing: .04em; text-transform: uppercase; }
  textarea, select {
    width: 100%; background: #161616; color: #e0e0e0;
    border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 12px;
    font-size: .95rem; font-family: inherit; transition: border-color .15s;
  }
  textarea:focus, select:focus { outline: none; border-color: #3b82f6; }
  #proposal { height: 90px; resize: vertical; }
  #context  { height: 70px; resize: vertical; }
  select { cursor: pointer; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23888' d='M6 8L1 3h10z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; }
  select option { background: #1a1a1a; }

  .row { display: flex; gap: 12px; margin-top: 12px; align-items: flex-end; }
  .field { flex: 1; }
  .btn {
    padding: 10px 22px; background: #2563eb; color: #fff;
    border: none; border-radius: 8px; cursor: pointer; font-size: .95rem;
    font-weight: 600; white-space: nowrap; transition: background .15s, opacity .15s;
  }
  .btn:hover:not(:disabled) { background: #1d4ed8; }
  .btn:disabled { opacity: .45; cursor: default; }

  .hint { color: #555; font-size: .78rem; margin-top: 8px; }

  /* spinner */
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #444; border-top-color: #3b82f6; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }

  #status { margin-top: 16px; color: #888; font-size: .85rem; min-height: 20px; }
  #result { margin-top: 24px; }

  .card { background: #161616; border: 1px solid #2a2a2a; border-radius: 10px; padding: 20px 22px; margin-bottom: 14px; }
  .verdict-line { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
  .verdict { font-size: 1.5rem; font-weight: 700; }
  .GO    { color: #4ade80; }
  .MODIFY{ color: #facc15; }
  .STOP  { color: #f87171; }
  .BLOCK { color: #f87171; }
  .ANSWER{ color: #60a5fa; }
  .meta  { color: #555; font-size: .82rem; }
  .rec   { color: #cbd5e1; line-height: 1.6; margin-bottom: 0; }

  .sketch-wrap { margin-top: 14px; }
  .sketch-label { font-size: .78rem; color: #6b7280; margin-bottom: 6px; }
  .sketch { background: #0d0d0d; border: 1px solid #222; border-radius: 6px; padding: 12px 14px; font-size: .85rem; white-space: pre-wrap; color: #d1d5db; }

  .skeptic { margin-top: 14px; border-top: 1px solid #1f1f1f; padding-top: 14px; }
  .skeptic-title { font-size: .78rem; color: #f59e0b; margin-bottom: 6px; }
  .skeptic li { font-size: .84rem; color: #9ca3af; line-height: 1.5; margin-bottom: 4px; }

  .error-card { background: #1a0a0a; border: 1px solid #3f1111; border-radius: 10px; padding: 16px 20px; color: #fca5a5; font-size: .9rem; }
</style>
</head>
<body>
<h1>Consilium</h1>
<p class="sub">AI deliberation for code changes — enter a proposal and get a structured verdict.</p>

<label for="proposal">Proposal</label>
<textarea id="proposal" placeholder="e.g. Add a /health endpoint to the FastAPI server"></textarea>

<label for="context" style="margin-top:14px">Context <span style="text-transform:none;font-size:.75rem;color:#555">(optional — paste relevant code, diff, or notes)</span></label>
<textarea id="context" placeholder="Paste code, a git diff, or additional context…"></textarea>

<div class="row">
  <div class="field">
    <label for="mode">Mode</label>
    <select id="mode">
      <option value="sequential">Sequential — fast (default)</option>
      <option value="dialectic">Dialectic — adds Skeptic voice</option>
      <option value="trias">Trias — 3 personalities, high-stakes</option>
    </select>
  </div>
  <button class="btn" id="btn" onclick="run()">Deliberate</button>
</div>
<div class="hint">Ctrl+Enter to submit &nbsp;·&nbsp; results appear below</div>

<div id="status"></div>
<div id="result"></div>

<script>
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
async function run() {
  const proposal = document.getElementById('proposal').value.trim();
  if (!proposal) { document.getElementById('proposal').focus(); return; }
  const context = document.getElementById('context').value.trim();
  const mode = document.getElementById('mode').value;
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');
  const result = document.getElementById('result');

  btn.disabled = true;
  status.innerHTML = '<span class="spinner"></span>Deliberating… this takes 15–60 s';
  result.innerHTML = '';

  try {
    const res = await fetch('/deliberate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({proposal, context, mode})
    });
    const d = await res.json();

    if (!res.ok) {
      const msg = Array.isArray(d.detail)
        ? d.detail.map(e => e.msg || JSON.stringify(e)).join('; ')
        : (d.detail || 'Server error ' + res.status);
      result.innerHTML = '<div class="error-card"><strong>Error</strong><br>' + esc(msg) + '</div>';
      return;
    }

    const vc = d.verdict || 'UNKNOWN';
    const conf = d.confidence != null ? (d.confidence * 100).toFixed(0) + '%' : '—';
    let html = '<div class="card">';
    html += '<div class="verdict-line">';
    html += '<span class="verdict ' + vc + '">' + vc + '</span>';
    html += '<span class="meta">' + conf + ' confidence &nbsp;·&nbsp; ' + esc(d.mode || '—') + ' mode</span>';
    html += '</div>';
    html += '<p class="rec">' + esc(d.recommendation || '') + '</p>';

    if (d.chosen_sketch) {
      html += '<div class="sketch-wrap">';
      html += '<div class="sketch-label">How to implement (' + esc(d.chosen) + ')</div>';
      if (d.chosen_summary) html += '<div style="font-size:.85rem;color:#9ca3af;margin-bottom:6px">' + esc(d.chosen_summary) + '</div>';
      html += '<div class="sketch">' + esc(d.chosen_sketch) + '</div>';
      html += '</div>';
    }

    if (d.skeptic && d.skeptic.can_object) {
      html += '<div class="skeptic">';
      html += '<div class="skeptic-title">Skeptic · ' + esc(d.skeptic.failure_mode || '') + ' · ' + esc(d.skeptic.addressable || '') + '</div>';
      html += '<ul>' + (d.skeptic.concrete_concerns || []).map(c => '<li>' + esc(c) + '</li>').join('') + '</ul>';
      html += '</div>';
    }

    html += '</div>';
    result.innerHTML = html;
  } catch(e) {
    result.innerHTML = '<div class="error-card"><strong>Request failed</strong><br>' + esc(e.message) + '</div>';
  } finally {
    btn.disabled = false;
    status.innerHTML = '';
  }
}

document.addEventListener('keydown', e => {
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
