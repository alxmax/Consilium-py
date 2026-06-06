# consilium-py

Dialectical code-change deliberation as a standalone Python package.

Same deliberation engine as the [Consilium Claude Code skill](https://github.com/alxmax/Consilium),
usable without Claude Code — from any terminal, CI pipeline, or Python script.

```bash
pip install consilium-py
consilium deliberate "Add Redis caching to the API"
```

## How it works

Three voices deliberate sequentially on your proposal:

1. **Conservator** — assesses risk, reversibility, and regression potential
2. **Generator** — proposes approaches with trade-off analysis
3. **Control** — audits for consistency and glossary compliance

The aggregator produces a verdict: `GO`, `MODIFY`, `STOP`, `BLOCK`, or `ESCALATE`.

## Install

```bash
pip install consilium-py
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

### CLI

```bash
# Text output (default)
consilium deliberate "Refactor the auth module"

# With context files
consilium deliberate "Refactor the auth module" -c src/auth.py -c src/middleware.py

# JSON output
consilium deliberate "Add health check endpoint" --output json
```

### Python API

```python
from consilium import deliberate

report = deliberate("Add Redis caching to the API")
print(report.verdict)      # GO / MODIFY / STOP / BLOCK / ESCALATE
print(report.confidence)   # 0.0 – 1.0
print(report.recommendation)

# With context
report = deliberate(
    "Refactor auth module",
    context=open("src/auth.py").read(),
    model="claude-sonnet-4-6",
)
```

## Requirements

- Python 3.11+
- `ANTHROPIC_API_KEY` environment variable

## Related

- **[Consilium skill](https://github.com/alxmax/Consilium)** — same engine as a Claude Code skill,
  with Trias, Dialectic, and Skeptic modes. Zero dependencies (stdlib-only). Runs inside Claude Code.
