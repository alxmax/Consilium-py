---
id: CPYSRV-AUTH-001
status: confirmed
layer: bus
owner: human
depends_on: [CPYSRV-HTTP-001]
---

# HTTP access control — optional API key and per-caller rate limit

`consilium serve` binds `127.0.0.1` and is a single-operator tool. The same app
object bound to a non-loopback interface is a different exposure: each request
costs 3–10 provider calls, so an uncapped public endpoint is an unbounded bill,
not merely an open door. Both controls are opt-in via env var so local use is
unchanged.

## WHAT — Contract

- When `CONSILIUM_API_KEY` is unset or empty, `POST /deliberate` and `POST /ask`
  shall be reachable without credentials (the localhost default).
- When it is set, both routes shall require a matching `X-API-Key` request header
  and return HTTP **401** otherwise, without invoking `deliberate()` or `ask()`.
  The comparison shall use `hmac.compare_digest` so a wrong key leaks no prefix
  information by timing.
- `CONSILIUM_RATE_LIMIT` shall cap requests per caller per 60-second window,
  defaulting to `30`. Exceeding the cap shall return HTTP **429**. A value of `0`
  or less shall disable the cap; an unparseable value shall fall back to the
  default rather than raise.
- The caller shall be identified by `X-API-Key` when present, else by client IP —
  behind a proxy every caller otherwise shares one IP and one bucket.
- The limiter is in-process and per worker: it is a single-process cap, NOT a
  distributed quota. This is a documented limitation, not a defect.
- The `GET /` UI route shall not be rate limited.
- `reset_rate_limit()` shall clear all buckets.

## WHAT — Verify intent

None — doc is unambiguous.

## HOW — Acceptance

- Given no `CONSILIUM_API_KEY`, when `POST /deliberate` is called with no header, then 200 (tested-by `tests/test_server.py::TestApiKeyAuth::test_no_key_configured_leaves_endpoint_open`).
- Given `CONSILIUM_API_KEY=secret`, when the header is absent or wrong, then 401 and `deliberate` is not called (tested-by `tests/test_server.py::TestApiKeyAuth::test_configured_key_rejects_request_without_header` and `test_configured_key_rejects_wrong_header`).
- Given `CONSILIUM_API_KEY=secret`, when `X-API-Key: secret` is sent, then 200 (tested-by `tests/test_server.py::TestApiKeyAuth::test_correct_key_is_accepted`).
- Given `CONSILIUM_RATE_LIMIT=2`, when three requests are made, then the third returns 429 (tested-by `tests/test_server.py::TestRateLimit::test_requests_beyond_the_limit_get_429`).
- Given `CONSILIUM_RATE_LIMIT=1`, when `GET /` is called twice, then both return 200 (tested-by `tests/test_server.py::TestRateLimit::test_limit_does_not_apply_to_the_ui_route`).
- Given `CONSILIUM_API_KEY=secret`, when `POST /ask` is called with no header, then 401 and `ask` is not called (tested-by `tests/test_server.py::TestAskRoute::test_is_behind_the_same_api_key`).

## WHERE — Current implementation

- `src/consilium/server.py`
