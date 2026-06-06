# consilium-py

Dialectical code-change deliberation as a standalone Python package.

Same deliberation engine as the [Consilium Claude Code skill](https://github.com/alxmax/Consilium),
usable without Claude Code — from any terminal, CI pipeline, or Python script.

```bash
pip install consilium-py
consilium deliberate "Add Redis caching to the API"
```

## How it works

Three AI voices deliberate on your proposal in a structured pipeline:

1. **Conservator** — assesses risk, reversibility, and regression potential
2. **Generator** — proposes 3–5 approaches with trade-off analysis  
3. **Control** — audits for technical correctness and glossary compliance

The aggregator produces a verdict: `GO`, `MODIFY`, `STOP`, `BLOCK`, or `ESCALATE`.
Confidence score (0.0–1.0) reflects inter-voice agreement.

For a visual walkthrough, open [`docs/Consilium-py Explained (standalone).html`](docs/Consilium-py%20Explained%20(standalone).html) locally.

## Install

```bash
pip install consilium-py
export ANTHROPIC_API_KEY=sk-ant-...
```

### Optional extras

| Extra | What it adds | Install |
|---|---|---|
| `[server]` | FastAPI REST endpoint + SSE streaming (`POST /deliberate`) | `pip install 'consilium-py[server]'` |
| `[rag]` | ChromaDB context injection — retrieves similar past decisions | `pip install 'consilium-py[rag]'` |
| `[langgraph]` | LangGraph orchestration mode replacing the sequential pipeline | `pip install 'consilium-py[langgraph]'` |
| `[litellm]` | Provider-agnostic voices — use any model via `provider/model` | `pip install 'consilium-py[litellm]'` |

## Deliberation modes

| Mode | Description |
|---|---|
| `sequential` *(default)* | Conservator → Generator → Control in a single context chain |
| `dialectic` | Sequential + Skeptic challenger on the chosen candidate |
| `trias` | 3 parallel personalities (Pioneer, Architect, Steward) with democratic vote |
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

# Use a specific model (or set CONSILIUM_MODEL env var)
consilium deliberate "Add caching" --model openai/gpt-4o
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
    model="claude-sonnet-4-6",
)

# RAG: inject similar past decisions as context (requires [rag] extra)
report = deliberate("Add rate limiting", rag=True)
```

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

### FastAPI server (requires `[server]` extra)

```bash
pip install 'consilium-py[server]'
uvicorn consilium.server:app
# POST /deliberate  { "proposal": "...", "mode": "sequential" }
```

## Requirements

- Python 3.11+
- `ANTHROPIC_API_KEY` — required for Anthropic models (default)
- Provider-specific env vars when using LiteLLM (`OPENAI_API_KEY`, etc.)

## Related

- **[Consilium skill](https://github.com/alxmax/Consilium)** — same engine as a Claude Code skill, with Trias, Dialectic, and Skeptic modes. Zero dependencies (stdlib-only). Runs inside Claude Code.

## License

See [LICENSE](LICENSE).
