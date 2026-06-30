---
id: CPYSRV-HTTP-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYBUS-API-001]
---

# HTTP server — POST /deliberate and the / web UI

Optional `[server]` extra exposing the deliberation engine over HTTP via FastAPI, plus a
self-contained HTML page so a browser can drive `deliberate()` without the CLI or API key
plumbing.

## WHAT — Contract

- Importing `consilium.server` shall raise `ImportError` with a `pip install 'consilium-py[server]'`
  hint when `fastapi` is not installed, rather than a raw `ModuleNotFoundError`.
- `GET /` shall return an `HTMLResponse` containing a self-contained page (inline CSS/JS, no
  external assets) that posts to `/deliberate` and renders the verdict, confidence, mode,
  recommendation, `chosen_sketch` (when present), and Skeptic concerns (when `skeptic.can_object`).
- `POST /deliberate` shall accept a JSON body `{proposal: str, context: str = "", mode: str =
  "sequential", model: str = ""}` and call `deliberate(proposal=..., context=..., mode=...)`,
  forwarding `model` only when non-empty (an empty `model` lets `deliberate()` fall back to its
  own default / `CONSILIUM_MODEL`).
- `POST /deliberate` shall respond with the full `consilium.models.Report` serialized as JSON
  (FastAPI `response_model=Report`), status 200 on success.
- The app shall be importable and constructible (`from consilium.server import app`) without any
  network call — `deliberate()` is invoked only when a request hits `/deliberate`.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `fastapi` is installed and voices mocked to a GO verdict, when `POST /deliberate` is
  called with `{"proposal": "Add health check"}`, then the response is 200 and the body contains
  `verdict`, `confidence`, `recommendation`, and a `voices` list.
- Given a request with `context` and `mode` set, when `POST /deliberate` is called, then the
  response is 200 and `verdict` is present in the body.
- Given `GET /`, when called, then the response is an HTML page (content-type `text/html`).

## WHERE — Current implementation

- `src/consilium/server.py`
