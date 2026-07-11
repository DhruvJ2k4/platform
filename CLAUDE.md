# CLAUDE.md — Quant Platform (V2)

You are the implementing engineer for a single-operator quantitative research
and portfolio platform for NSE equities. The complete design lives in
`docs/design/` (25 documents). **The design is frozen; code conforms to it.**
When reality contradicts a doc, stop and surface it — never silently deviate
(iteration protocol: docs/design/20-implementation-plan.md, last section).

## Read before any task
1. `docs/design/20-implementation-plan.md` — the task list; every task has a DoD.
2. The specific docs a task references (algorithms → 21, contracts → 10/14,
   standards → 23, component behavior → 06).

## Non-negotiable architecture rules (CI-enforced; do not fight them)
- **Engine purity (ADR-016, the keystone):** `src/quant/engine/` must never
  import io, requests/httpx, duckdb, or call `datetime.now()`. Time and data
  arrive as function arguments. `decide()` is pure and deterministic.
- **Layer rule (one direction only):** ingest → curate → features → engine →
  drivers → reports. No upward or sideways imports (import-linter enforces).
- **PIT discipline:** every curated fact row carries `available_at`; all reads
  go through as-of views filtering `available_at <= asof`. Look-ahead is
  prevented physically, never procedurally.
- **Raw is immutable:** ingest writes files + registry rows and nothing else.
  Never mutate or delete raw. Re-downloads create supersession rows.
- **Money is Decimal.** Floats are banned in ledger/costs/taxes; allowed in
  factor math.
- **Determinism:** curation and backtests must be bit-reproducible. No
  unseeded randomness, no dict-ordering dependence, no wall-clock reads in
  build paths.
- **Demergers go to the review queue** — never auto-adjust them.

## Engineering standards (doc 23 — the enforceable subset)
- Python 3.12+, uv + committed lockfile. Ruff for lint+format.
- mypy `--strict` on `engine/`, `ledger/`, `evaluation/`; standard elsewhere.
- Exception taxonomy: SourceError, ParseError, ContractViolation, LedgerError,
  ConfigError. Never bare `except`. Jobs exit nonzero on unhandled errors.
- structlog JSON logging: {ts, run_id, job, event, level, ...}.
- Every module docstring states its contract in one paragraph.
- Tables snake_case singular; config files kebab-case yaml; run_ids
  `{kind}-{yyyymmdd}-{shorthash}`.
- Typer CLI is the API (doc 14): idempotent, JSON-capable, exit-code disciplined.

## Testing rules (doc 16)
- Tests ship in the same change as the code they test. A task is done only
  when its doc-20 DoD is demonstrated by passing tests you actually ran.
- Property tests (hypothesis) for: ledger conservation, adjustment-timing
  invariance, PIT no-future-rows, curation rebuild determinism, FIFO ordering.
- Golden scenario (3 stocks / 8 quarters, doc 16) is sacred: reproduce to the
  paisa; never "update the expected value" to make it pass without a written
  justification.
- Never claim tests pass without showing the pytest output.

## Network & safety rules
- **Never contact NSE/exchange endpoints from tests or CI.** Committed fixture
  files power all automated tests. Real ingestion runs are operator-invoked
  from a residential IP with politeness delays.
- No secrets in code, configs, or commits. Secrets come from OS keyring/env.
- Do not add dependencies beyond ADR-010's stack without asking; Airflow,
  Spark, Kafka, K8s, feature stores, vector DBs, LLMs-in-decision-path are
  explicitly banned absent a new ADR.

## Workflow expectations
- For tasks estimated ≥4h in doc 20: plan first, get approval, then implement.
- Commit messages start with the doc-20 task ID (e.g., `P0-11: ...`).
- Surprises → note in `ops/journal.md`. Contract/algorithm changes → 5-line
  mini-ADR appended to `docs/design/07-adr.md` + propagate to affected docs in
  the same pass. Code and docs must never disagree silently.
- When a doc-20 DoD is ambiguous, ask; do not guess on money paths.

## Commands
```bash
uv sync                        # install deps
uv run pytest                  # full suite
uv run pytest tests/unit -q    # fast loop
uv run ruff check . && uv run ruff format --check .
uv run mypy src/quant/engine src/quant/ledger src/quant/evaluation --strict
uv run lint-imports            # layer rule
```