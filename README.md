# platform

Single-operator quantitative research and portfolio platform for NSE equities:
batch, EOD-only, one pure portfolio engine with two drivers (backtest replay /
live), reproducibility by deterministic rebuild, human-gated execution.

- The frozen design package lives in [`docs/design/`](docs/design/00-INDEX.md).
- Engineering rules for contributors and agents: [`CLAUDE.md`](CLAUDE.md).
- The import package is `quant` (ADR-020); the CLI command is `platform`.

## Quickstart

```bash
uv sync                        # install deps + editable package
uv run pytest                  # full suite
uv run ruff check . && uv run ruff format --check .
uv run mypy src/quant/engine src/quant/ledger src/quant/evaluation --strict
uv run lint-imports            # layer rule
uv run platform status
```
