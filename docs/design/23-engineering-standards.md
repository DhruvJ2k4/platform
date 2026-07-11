# 23 · Engineering Standards — Code, Caching, Performance, Security, Observability
**Purpose:** the daily-driver standards doc; everything a coder needs open in a tab. **Scope:** all code. **Rule zero:** these standards are CI-enforced where possible; a standard that isn't enforced is a suggestion.

## Code standards
Python 3.12+, `uv` + committed lockfile. Ruff (lint+format). Mypy `--strict` on
`engine/`, `ledger/`, `evaluation/` (money paths); standard elsewhere. Import-linter
contract enforces layer rule (ingest→curate→features→engine→drivers→reports; no
upward/sideways). Engine purity: CI grep-gate — `engine/` may not import io/requests/
datetime.now/duckdb; time and data arrive as arguments. Errors: exception taxonomy
{SourceError, ParseError, ContractViolation, LedgerError, ConfigError}; never bare
except; jobs exit nonzero on unhandled. Every module docstring states its contract in
one paragraph. Decimals for money (never float in ledger/costs); floats allowed in
factor math. Naming: tables snake_case singular; configs kebab-case yaml; run_ids
`{kind}-{yyyymmdd}-{shorthash}`.

## Caching (each layer: key, invalidation, eviction)
| Cache | Key | Invalidation | Notes |
|---|---|---|---|
| HTTP/raw | (source, logical_date) | never (raw IS the cache) | re-download = supersession row |
| Curated | — | rebuild on code/config change (ADR-016) | not a cache; derived store |
| Feature cache | (feature_id, fn_version, asof, curated_watermark) | key change only | content-addressed parquet; `rm -rf` safe |
| Report assets | (template_ver, run_id) | key change | rendered HTML archived per run |
| Agent tool outputs | (tool, args_hash, curated_watermark) | watermark change | avoids duplicate subprocess calls in a flow |
| LLM prompt cache | provider-side, system+tools prefix | provider TTL | cost lever for agent flows |
Rule: caches are always safe to delete; anything unsafe-to-delete is a store and gets
backup + contracts.

## Performance & latency budgets (CI perf tests assert the marked ones ✓)
Nightly pipeline p95 < 15 min: bhavcopy dl <2m · curate incremental <3m ✓ · features
warm <2m · events+status <1m · backup <5m. Full 15y curate --rebuild < 30 min ✓.
Backtest 15y single config < 5 min ✓ (rules: hot loop is numpy/DuckDB vectorized; no
per-row Python; per-day ledger ops O(names)). `universe --date` < 1s ✓. Proposal
end-to-end < 60s. Agent weekly flow < 10 min wall. Report page load: static, < 1s local.
Breach protocol: budgets are the trigger for optimization work — never optimize without
a breached budget (doc quality-standards).

## Security (threat model — assets → threats → mitigations)
**Assets:** personal financial data (ledger, reports), API keys (Telegram, backup, LLM),
data integrity (raw/curated), the box itself. **v1 has NO broker credentials.**
| Threat | Mitigation |
|---|---|
| Box compromise (LAN/home) | no inbound ports; SSH key-only from LAN; auto security updates OS-level; least-privilege service user |
| Backup bucket leak | rclone **crypt** (client-side); write-scoped token; bucket versioning |
| Supply chain | lockfile-pinned; monthly scheduled update day + `uv` audit; no auto-updates on prod box |
| Secret leakage | OS keyring/root-env only; pre-commit secret scan; secrets never in configs/repo |
| **Prompt injection via filings → agents** | doc 22 guardrails: containment, data-labeling, zero-tool analysts, external validators |
| Financial data → LLM API | config `agents.redact_positions=true` default: agents see ranks/percentages, not ₹ values, unless operator opts out |
| Tampered source data (integrity) | checksums at ingest; cross-source spot checks; DQ invariants; immutable raw enables forensics |
| Operator error (rm -rf) | raw+operational in nightly encrypted backup + second local disk; restore drilled 2×/yr |

## Observability
structlog JSON lines: {ts, run_id, job, event, level, isin?, table?, rows?, ms}. Run
manifests (doc 08) for lineage. Metrics kept simple: per-job duration/rows appended to a
DuckDB `job_stats` table → charts on status page (no Prometheus stack). Alert routing:
SEV1 (publish blocked, dead-man, freshness breach, reconcile mismatch) → Telegram now;
SEV2 → daily digest; SEV3 → weekly DQ report. Absence-alarms are first-class (doc 06).

## CI (GitHub Actions; never touches exchange endpoints)
jobs: lint+type → unit+property → golden → integration (committed fixtures) → perf ✓
tests → champion regression pin → package. Trunk-based; tags = deploys; deploy =
`git pull && uv sync && platform smoke` on the box; rollback = previous tag.
