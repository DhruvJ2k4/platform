# Ops journal

## 2026-07-12 — P0-01
- Surprise: `src/platform` is shadowed by Python's stdlib `platform` module — the package could
  never be imported under pytest or console scripts. Resolved: import package renamed to `quant`
  (ADR-020); repo dir, CLI command, and distribution keep the name `platform`; doc 20 and
  CLAUDE.md updated in the same pass.
- Surprise: CLAUDE.md references `docs/design/` but the docs lived in `docs/decisions/`.
  Resolved: directory renamed to `docs/design/` (the docs carry no self-references either way).
- CI: both `|| true` escapes removed ahead of their stated schedule — import-linter contracts now
  exist, and mypy `--strict` passes on the skeleton trio today. `uv sync --locked` now enforces
  the committed lockfile in CI.
- New dev dependency beyond the ADR-010 stack, user-approved in the P0-01 plan: `detect-secrets`
  (doc 23's mandated pre-commit secret scan).

## 2026-07-12 — P0-02
- Doc 08 says every curated fact row carries `available_at`; doc 10's DDL puts it only on
  corporate_actions/fundamentals_pit (events has observed_at). Resolved with operator:
  transcribe doc 10 as authored — daily-published tables are PIT by `d <= asof`; columns are
  additive later if P0-13 needs them.
- DuckDB traps found and closed (ADR-021): bare DECIMAL silently means DECIMAL(18,3) → explicit
  (p,s) everywhere, test-enforced; `.df()` degrades DECIMAL to float64 → Arrow path
  (quant.schemas.arrow_frame) is the canonical typed read; `asof` is a reserved word (like
  `order`) → quoted in proposal DDL.
- quant.schemas deliberately imports no duckdb so engine → schemas stays clean under
  import-linter's transitive forbidden check. The DDL loader raises FileNotFoundError until the
  P0-03 exception taxonomy provides ConfigError.

## 2026-07-12 — P0-03
- `pyyaml` declared as a runtime dependency (was only transitively present via pre-commit);
  yaml configs are designed-in (docs 20/23), flagged and approved in the plan.
- Rate files carry a single verified epoch (effective_from 2024-07-23, Finance (No.2) Act
  2024 / doc-12 rates). Dates before it fail loudly by design; P1-02/P1-03 add golden-tested
  historical epochs. Custom Decimal-preserving YAML loader guarantees rates never exist as
  binary floats.
- Doc-23 exception taxonomy landed in quant/errors.py (bottom import-linter layer);
  quant/config.py sits just above quant.schemas. schemas.ddl_sql now raises ConfigError as
  promised in the P0-02 entry.

## 2026-07-12 — P0-04
- Doc 06 "registry upsert idempotent by (source, logical_date)" vs doc 08 "supersession
  creates a new row" reconciled via content-addressed filenames ({source}-{date}-{sha12}):
  identical bytes → complete no-op (the DoD); changed bytes → new file + appended row;
  nothing overwritten or deleted; landed raw files are chmod 0o444.
- Crash-safety ordering: file lands (tmp + fsync + atomic rename) BEFORE its registry row,
  so a crash between the two heals on the next ingest; a registered-but-missing file is
  restored without a new row and logged as a warning.
- fetched_at is naive UTC (matches the timestamp[us] contract); injectable for tests.
  Global structlog JSON config is deferred to P0-06 CLI wiring — store logs via defaults.
