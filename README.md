# consilium-py

Dialectical code-change deliberation as a standalone Python package.

Same deliberation engine as the [Consilium Claude Code skill](https://github.com/alxmax/Consilium),
usable without Claude Code — from any terminal, CI pipeline, Python script, or HTTP API.

```bash
pip install consilium-py
consilium deliberate "Add Redis caching to the API"
```

## How it works

Three AI voices deliberate on your proposal in a structured pipeline:

1. **Generator** — proposes 3–5 approaches with trade-off analysis; runs first, blind to any risk framing (anti-anchoring)
2. **Conservator** — assesses risk, reversibility, and regression potential of the Generator's candidates
3. **Control** — audits for technical correctness and glossary compliance

The aggregator produces a verdict: `GO`, `MODIFY`, `STOP`, `BLOCK`, or `ESCALATE`.
Confidence score (0.0–1.0) reflects inter-voice agreement.

For a visual walkthrough, open [`docs/index.html`](docs/index.html) — a "how it works" page with
links to the requirement map and the architecture diagram — or the full architecture poster
[`docs/consilium_architecture.html`](docs/consilium_architecture.html).

## Install

```bash
pip install consilium-py
export OPENROUTER_API_KEY=sk-or-...
```

### Optional extras

| Extra | What it adds | Install |
|---|---|---|
| `[server]` | FastAPI HTTP server — `POST /deliberate` and `POST /ask` over HTTP | `pip install 'consilium-py[server]'` |
| `[rag]` | ChromaDB context injection — retrieves similar past decisions **and ingested reference docs** ([details](#rag--document-ingestion)) | `pip install 'consilium-py[rag]'` |
| `[docs]` | Document extractors for `consilium ingest` — PDF, DOCX, HTML | `pip install 'consilium-py[docs]'` |
| `[langgraph]` | LangGraph orchestration mode replacing the sequential pipeline | `pip install 'consilium-py[langgraph]'` |

## Deliberation modes

| Mode | Description |
|---|---|
| `sequential` *(default)* | Generator → Conservator → Control in a single context chain |
| `dialectic` | Sequential + Skeptic challenger on the chosen candidate |
| `trias` | 3 parallel personalities (Pioneer, Architect, Steward) voting on a shared candidate set |
| `langgraph` | LangGraph-orchestrated pipeline; requires `[langgraph]` extra |

## Usage

### CLI

```bash
# Default (sequential mode, text output)
consilium deliberate "Refactor the auth module"

# With context files
consilium deliberate "Refactor the auth module" -c src/auth.py -c src/middleware.py

# Different mode + JSON output
consilium deliberate "Add health check endpoint" --mode trias --output json

# Review the current git diff
consilium check

# Use a different model (or set CONSILIUM_MODEL env var)
consilium deliberate "Add caching" --model gemini/gemini-2.5-pro
consilium deliberate "Add caching" --model openai/gpt-4o

# Explain a codebase (summary, public API, dependencies, gotchas)
consilium explain src/consilium/voices.py
consilium explain src/consilium/ --output json

# Start the web UI (requires the [server] extra) — picks a free port, opens a browser
consilium serve
consilium serve --port 9000 --no-browser
```

### Python API

```python
from consilium import deliberate

# Basic
report = deliberate("Add Redis caching to the API")
print(report.verdict)        # GO / MODIFY / STOP / BLOCK / ESCALATE
print(report.confidence)     # 0.0 – 1.0
print(report.recommendation)

# With mode and context
report = deliberate(
    "Refactor auth module",
    context=open("src/auth.py").read(),
    mode="dialectic",
    model="gemini/gemini-2.0-flash",
)

# RAG: inject similar past decisions + ingested docs as context (requires [rag] extra)
report = deliberate("Add rate limiting", rag=True)
```

### RAG & document ingestion

The `[rag]` extra pulls two kinds of context into a deliberation, each retrieved
by cosine similarity from a local ChromaDB store (`~/.consilium/chroma/`):

- **`SIMILAR PAST DECISIONS`** — your own past deliberation runs. Low-confidence
  and `STOP`/`BLOCK` runs are excluded by design (a failed past call isn't guidance).
- **`RELEVANT DOCS`** — chunks of reference documents you've ingested (coding
  standards, an architecture note, an API guide), cited by source in the report.
  So Control can check a change against *"conform CODING_STANDARDS.md"*.

#### Supported formats

`consilium ingest` dispatches on file suffix. Text formats need nothing; the
rest come with the `[docs]` extra. Anything else is skipped with a message on
stderr — never silently.

| Suffix | Handling | Needs |
|---|---|---|
| `.md` `.txt` `.py` `.rst` | read as-is | — |
| `.pdf` | text per page (PyMuPDF — no external binary) | `[docs]` |
| `.docx` | paragraph text | `[docs]` |
| `.html` `.htm` | visible text; `<script>`/`<style>` stripped | `[docs]` |
| `.csv` | **schema summary only** — see below | — |
| images | not ingested | — |

**CSV is summarised, not embedded.** You get the filename, column list, row
count, and the first few rows *for shape only*. Its rows are deliberately not
indexed: a top-k cosine match returns a handful of arbitrary rows, and a model
will happily compute a confident, wrong aggregate from them. Retrieval should
answer *"which dataset holds this?"* — the figure itself must come from a
deterministic query against the real file. The same reasoning excludes `.sql`
(a schema script is not data).

Images are excluded for a different reason: OCR needs an external `tesseract`
binary, and a silently empty extraction is worse than an explicit skip. The
registry (`_EXTRACTORS` in `rag.py`) is one dict entry per format, so adding OCR
later touches nothing else in the ingest path.

```bash
pip install 'consilium-py[rag]'

consilium index                 # index your past runs (~/.consilium/runs/)
consilium ingest docs/          # chunk + index a doc or directory into the corpus
consilium ingest CODING.md      # …one file at a time works too

consilium deliberate "Add a cache layer" --rag     # inject both blocks
```

`ingest` chunks each `.md`/`.txt`/`.py`/`.rst` file (1200-char windows, 200
overlap), skipping binaries, files over 1 MB, and symlinks that escape the target.
Re-ingesting a file replaces its chunks (no stale orphans). Retrieved docs are
deduplicated by source, so one big file can't crowd out the others.

**Toggling:** `--rag` / `--no-rag`, defaulting from the `CONSILIUM_RAG` env var —
so you can set `CONSILIUM_RAG=1` locally and still force `--no-rag` for a single run.

> **On determinism:** RAG is **off by default** on purpose. Injecting past runs
> makes a deliberation's output depend on your history, which is at odds with the
> project's reproducibility goal. The `docs` path (a fixed, committed corpus) is the
> one that could ever be made default-safe — pinning/versioning a corpus is noted
> as future work, not done yet.

### HTTP API

Requires the `[server]` extra. Runs the three-voice deliberation over HTTP — useful for CI pipelines, polyglot codebases, or quick demos.

```bash
pip install 'consilium-py[server]'

# Easiest: consilium serve picks a free port, opens a browser to the HTML UI
export OPENROUTER_API_KEY=sk-or-...
consilium serve

# Or run uvicorn directly for more control (no auto port/browser handling)
uvicorn consilium.server:app --port 8123

# Or use claude-cli — no API key, just a Claude subscription
CONSILIUM_MODEL=claude-cli consilium serve
```

```bash
curl -X POST http://localhost:8123/deliberate \
  -H "Content-Type: application/json" \
  -d '{"proposal": "Add a /health endpoint to the auth service"}'
# → {"verdict":"GO","confidence":0.5,"recommendation":...}
```

Request body fields: `proposal` (required), `context`, `mode` (`sequential` / `dialectic` / `trias`), `model` — all optional except `proposal`. If `model` is omitted, `CONSILIUM_MODEL` env var is used.

### Chat Q&A — `POST /ask`

A question is not a code-change proposal: the deliberation pipeline classifies it
`not_a_proposal` and discards its own result, so routing chat through
`/deliberate` pays for 3–10 voice calls to reach a one-call answer. `/ask`
retrieves from the ingested-doc corpus and answers directly, and returns the
chunks it used in `sources` so the grounding is verifiable.

```bash
consilium ingest ./docs          # seed the corpus first ([rag] extra)

curl -X POST http://localhost:8123/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What retry budget do the voices use?"}'
# → {"verdict":"ANSWER","recommendation":"...","sources":["voices.md#2"],"mode":"chat"}
```

Fields: `question` (required), `rag` (default `true`), `model`, and `mode`. Leave
`mode` unset for the cheap grounded answer; set it (`sequential` / `dialectic` /
`trias`) to opt into a full deliberation when the input really is a proposal.
The same surface is available in Python as `consilium.chat.ask(...)`, without the
`[server]` extra.

### Serving beyond localhost

`consilium serve` binds `127.0.0.1` and both controls below are off by default,
so local use is unchanged. Set them before exposing the port:

| Env var | Effect |
|---|---|
| `CONSILIUM_API_KEY` | When set, `/deliberate` and `/ask` require a matching `X-API-Key` header (401 otherwise). Unset = no auth. Single-tenant: all callers share one corpus. |
| `CONSILIUM_API_KEYS` | `tenant:key,tenant:key` — turns on **multi-tenant** mode. Each key authenticates *and* selects that tenant's RAG scope. Takes precedence over the singular variable. |
| `CONSILIUM_RATE_LIMIT` | Requests per 60 s per caller (default `30`, `0` disables). Exceeding it returns 429. In-process, per worker — not a distributed quota. |
| `CONSILIUM_HOME` | Storage root for `runs/` and `chroma/`. Defaults to `~/.consilium`, which is the *service account's* home under a server — set this to a persistent volume. |

#### Tenancy — two modes

`tenant=None` (the default, and what `CONSILIUM_API_KEY` alone gives you) keeps
one shared corpus. Setting `CONSILIUM_API_KEYS` scopes both reads and writes per
key:

```bash
export CONSILIUM_API_KEYS="alice:sk-alice-…,bob:sk-bob-…"
consilium ingest ./alice-docs --tenant alice
# a request with alice's key can never retrieve bob's chunks, and vice versa
```

The tenant is resolved **server-side from the authenticated key** — a `tenant`
field in the request body is ignored, so a caller cannot pick their own scope.

Two consequences worth knowing before you switch a live corpus:

- **Scoped mode fails closed.** Records written before tenancy existed carry no
  tenant key, so a scoped query cannot see them. That is deliberate — the
  alternative is leaking pre-tenancy data to whichever tenant asks first.
  Re-ingest under a tenant (`consilium ingest <path> --tenant <id>`) to restore
  visibility.
- **The switch is not retroactive.** Anything already served from a shared
  corpus stays served; scoping only governs what happens from now on.

### No-API-key backend (claude-cli)

If you have a Claude subscription (Claude Code CLI), you can run deliberations without any API key:

```bash
consilium deliberate "Add caching" --model claude-cli
```

```python
report = deliberate("Add caching", model="claude-cli")
```

Each voice call routes through `claude -p` (Claude Code CLI). Slower than a direct API call but useful for demos, local exploration, or when you don't have an API key.

### Provider-agnostic (LiteLLM)

Any model accessible via LiteLLM can be used by passing `provider/model`:

```bash
export OPENAI_API_KEY=sk-...
consilium deliberate "Add caching" --model openai/gpt-4o
```

```python
report = deliberate("Add caching", model="openai/gpt-4o")
```

The `CONSILIUM_MODEL` environment variable overrides the `--model` / `model=` parameter:

```bash
export CONSILIUM_MODEL=openai/gpt-4o
consilium deliberate "Add caching"
```

### Using OpenRouter (default)

OpenRouter gives access to Gemini, Claude, GPT, and hundreds of other models through a
single API key. This is the default provider.

```bash
export OPENROUTER_API_KEY=sk-or-...
```

```bash
# CLI — default model is openrouter/google/gemini-2.0-flash-001
consilium deliberate "Add caching"
consilium deliberate "Refactor auth" --model openrouter/google/gemini-2.5-pro
consilium deliberate "Add caching" --model openrouter/anthropic/claude-sonnet-4-5

# Or set once and forget
export CONSILIUM_MODEL=openrouter/google/gemini-2.5-flash
consilium deliberate "Add caching"
consilium check
```

```python
# Python API
from consilium import deliberate

report = deliberate("Add caching", model="openrouter/google/gemini-2.0-flash-001")
print(report.verdict)
print(report.recommendation)
```

> **Model strings:** use the `openrouter/` prefix followed by the exact model ID from the  
> [OpenRouter model list](https://openrouter.ai/models) — e.g. `openrouter/google/gemini-2.5-pro`.
> A `404 No endpoints found` means the model isn't available on your account (add credits or
> try a `:free` variant like `openrouter/google/gemini-2.0-flash-exp:free`).

## Deploy

Terraform for running the [HTTP API](#http-api) on GCP Cloud Run lives in
[`infra/`](infra/README.md) — private by default, API key in Secret Manager, no plain
secrets in Cloud Run env vars, Terraform state in a versioned GCS bucket (not local). See
[`infra/README.md`](infra/README.md) for the build/push/apply steps.

## Development

```bash
pip install -e ".[dev,server,rag,langgraph]"

python -m pytest          # full suite — voices are mocked, no API calls
pyright src/              # type check
python scripts/reqmap.py gate   # requirement-traceability drift gate (CI-style check)
```

Every source file that implements a capability carries a `# implements: <ID>` comment; its
tests carry `# tested-by: <ID>`. [`requirements/_map.md`](requirements/_map.md) is the generated
source-of-truth map (also viewable as [`requirements/_map.html`](requirements/_map.html)) — the
`gate` command above fails the build if code and requirements drift apart.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the test suite on a **Python
3.11 + 3.12 matrix** plus the drift gate on every push. Two versions, not one, because the
package declares `requires-python = ">=3.11"` — testing both proves the floor it advertises
actually holds, so a 3.11 user can't hit a version-specific break that only 3.12 was tested against.

## Requirements

- Python 3.11+
- `OPENROUTER_API_KEY` — required for the default OpenRouter models
- `ANTHROPIC_API_KEY` — required when using bare Anthropic/Claude model names (e.g. `claude-sonnet-4-6`)
- Provider-specific env vars for other providers via LiteLLM (`OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.)
- No API key needed when using `--model claude-cli` — requires the [Claude Code CLI](https://claude.ai/code) installed and authenticated. Defaults to Sonnet; pick another Claude model with `--model claude-cli:opus`

## Related

- **[Consilium skill](https://github.com/alxmax/Consilium)** — same engine as a Claude Code skill, with Trias, Dialectic, and Skeptic modes. Zero dependencies (stdlib-only). Runs inside Claude Code.

## License

See [LICENSE](LICENSE).
