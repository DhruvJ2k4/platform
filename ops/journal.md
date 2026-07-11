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
