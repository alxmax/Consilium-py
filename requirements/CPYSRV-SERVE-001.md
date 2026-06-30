---
id: CPYSRV-SERVE-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYSRV-HTTP-001]
---

# serve CLI command — local web UI launcher

`consilium serve` starts the `[server]` extra's FastAPI app (CPYSRV-HTTP-001) under `uvicorn` for
local, no-API-plumbing use: pick a free port, open the browser, wire `CONSILIUM_MODEL`.

## WHAT — Contract

- `consilium serve` shall require the `[server]` extra; if `import uvicorn` fails, it shall raise
  a `ClickException` with a `pip install 'consilium-py[server]'` hint rather than a raw
  `ModuleNotFoundError`.
- `--model` shall default to the CLI's default model and read the `CONSILIUM_MODEL` env var
  (Click `envvar=`); before starting the server, the resolved `model` value shall be written back
  into `os.environ["CONSILIUM_MODEL"]` so that `deliberate()` calls made by the running server
  (which has no access to the CLI's local `model` variable) pick it up.
- `--port` (default 8124) shall be probed for availability; if busy, the command shall print a
  notice and retry the next port upward (`port + 1`) until a free one is found, before binding.
- Unless `--no-browser` is passed, the command shall open the default web browser at the chosen
  `http://<host>:<port>/` URL automatically, on a daemon thread, after a short delay — so opening
  the browser never blocks or fails the act of starting the server.
- The command shall call `uvicorn.run("consilium.server:app", host=host, port=port,
  log_level="warning")`, blocking until interrupted (e.g. Ctrl+C).

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given `uvicorn` is not installed, when `consilium serve` is invoked, then it exits non-zero
  with a `[server]` extra install hint and `uvicorn.run` is never called.
- Given `--model openai/gpt-4o`, when `consilium serve` is invoked, then `os.environ["CONSILIUM_MODEL"]`
  is set to `"openai/gpt-4o"` before `uvicorn.run` is called.
- Given the requested port is reported busy, when `consilium serve` is invoked, then it retries
  on `port + 1` until a free port is found, and `uvicorn.run` is called with that free port.
- Given `--no-browser`, when `consilium serve` is invoked, then `webbrowser.open` is never called.
- Given no `--no-browser`, when `consilium serve` is invoked, then a browser-opening thread is
  started targeting the chosen `http://<host>:<port>/` URL.

## WHERE — Current implementation

- `src/consilium/cli.py` (`serve_cmd`)
