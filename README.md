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
| `[rag]` | ChromaDB context injection — retrieves similar past decisions | `pip install 'consilium-py[rag]'` |
| `[langgraph]` | LangGraph orchestration mode replacing the sequential pipeline | `pip install 'consilium-py[langgraph]'` |

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

# Use a different model (or set CONSILIUM_MODEL env var)
consilium deliberate "Add caching" --model gemini/gemini-2.5-pro
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
    model="gemini/gemini-2.0-flash",
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

## Requirements

- Python 3.11+
- `OPENROUTER_API_KEY` — required for the default OpenRouter models
- `ANTHROPIC_API_KEY` — required when using bare Anthropic/Claude model names (e.g. `claude-sonnet-4-6`)
- Provider-specific env vars for other providers via LiteLLM (`OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.)

## Related

- **[Consilium skill](https://github.com/alxmax/Consilium)** — same engine as a Claude Code skill, with Trias, Dialectic, and Skeptic modes. Zero dependencies (stdlib-only). Runs inside Claude Code.

## License

See [LICENSE](LICENSE).
