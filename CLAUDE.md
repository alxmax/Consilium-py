# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with all extras)
pip install -e ".[dev,server,rag,langgraph]"

# Run all tests (no API calls — voices are mocked)
python -m pytest

# Run a single test file
python -m pytest tests/test_sequential.py

# Run a single test
python -m pytest tests/test_sequential.py::TestRunSequential::test_go_verdict

# Type check
pyright src/

# CLI (requires ANTHROPIC_API_KEY or CONSILIUM_MODEL)
consilium deliberate "Add health check endpoint"
consilium deliberate "Refactor auth" --mode dialectic --output json
consilium check                          # deliberate on staged git diff
consilium check --diff HEAD~1
consilium index                          # rebuild RAG index from ~/.consilium/runs/
```

## Architecture

### Core pipeline

Every deliberation passes through three AI voices in sequence, then the aggregator produces a `Report`:

1. **Conservator** (`prompts/voices/conservator.md`) — risk, reversibility, regression scores
2. **Generator** (`prompts/voices/generator.md`) — proposes 3–5 approaches with trade-offs; selects `preferred`
3. **Control** (`prompts/voices/control.md`) — audits for glossary compliance and cross-voice disagreements

Each voice is called via `voices.call_voice()`, which routes to Anthropic SDK or LiteLLM based on whether the model string contains `/` (e.g. `openai/gpt-4o`). Prompts are `.md` files loaded from `prompts/voices/` at call time.

The aggregator (`aggregator.py:aggregate_sequential`) applies a veto cascade:
- `glossary_fail` → `BLOCK`
- any `irreversibility_flag` from Conservator → `BLOCK`
- substantial disagreements → `MODIFY`/`ESCALATE`
- clean path → `GO`/`MODIFY`/`STOP` derived from `confidence_methodology`

### Deliberation modes (`src/consilium/modes/`)

| Mode | What it does |
|---|---|
| `sequential` | Single chain: Conservator → Generator → Control |
| `dialectic` | Sequential + 4th **Skeptic** voice challenging the chosen candidate; `--skeptic-can-override` lets it downgrade the verdict |
| `trias` | 3 parallel personalities (Pioneer, Architect, Steward) each run a full sequential deliberation; democratic majority vote decides |
| `langgraph` | Same sequential pipeline expressed as a LangGraph `StateGraph`; requires `[langgraph]` extra |

### Public surface

- `deliberate()` in `src/consilium/__init__.py` — single entry point for all modes; accepts `model`, `mode`, `rag`, `skeptic_can_override`
- `consilium.cli` — Click group with `deliberate`, `check`, and `index` commands
- `CONSILIUM_MODEL` env var overrides `--model` / `model=` everywhere

### Optional extensions (lazy imports)

All extras guard their imports with `try/except ImportError` and surface a `pip install` hint:
- **LiteLLM** (`voices.py`): triggered when `model` contains `/`
- **RAG** (`rag.py`): ChromaDB at `~/.consilium/chroma/`; runs persist to `~/.consilium/runs/`
- **LangGraph** (`modes/langgraph_mode.py`): imports at call site
- **FastAPI server**: `src/consilium/server.py` — module ships in `src/`, but `fastapi`/`uvicorn` are only pulled in via the `[server]` extra; the module raises a clear `ImportError` if imported without it

### Requirements traceability

Source files carry `# implements: CPYXXX-YYY-001` comments; tests carry `# tested-by: CPYXXX-YYY-001`. The canonical map is `requirements/_map.md`. When adding a new capability, follow the same pattern and update the map.

### Testing conventions

Tests mock `consilium.modes.<mode>.call_voice` (not the Anthropic client) so they exercise aggregation logic without API calls. Fixture JSON for voice outputs lives inline in each test file. `tests/fixtures/sample_report.json` validates `Report` schema parsing.
