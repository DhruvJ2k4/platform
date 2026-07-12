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
