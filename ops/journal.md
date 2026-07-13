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

## 2026-07-13 — ops: process encoded as skills + review agents
- The P0-01..04 working discipline is now executable by any model/session: four project
  skills (.claude/skills/: task, verify, review-domains, ship) and nine read-only reviewers
  in two panels (.claude/agents/ — engineering: arch-purity-guard, money-auditor,
  contract-auditor, docs-warden, test-warden; quant desk: quant-researcher, risk-manager,
  execution-trader, portfolio-manager — the desk panel also reviews plans/ideas), all
  referenced from CLAUDE.md. .gitignore now commits .claude/skills|agents|settings.json
  while still ignoring session cruft.
- Dogfooded on this very change: test-warden ran the full mandate and returned one NOTE
  (verify skill header overclaimed "exact gates CI runs" — fixed same pass; carried: CI's
  per-directory pytest split would skip a future suite dir outside the four known ones).
  Two reviewers hit the org's monthly agent spend limit mid-run; their checks were executed
  inline instead. Newly added agent names register at session start — same-session use
  falls back to general-purpose + "adopt the agent file's mandate".

## 2026-07-13 — P0-05
- NSE's edge gates on CLIENT SHAPE more than IP. Archives hosts: 200 with four browser
  headers (UA/Accept/Accept-Language/Referer), 403 bare-UA — P0-06's adapter must send all
  four. www API: 403 pre-cookie for httpx AND curl, from residential AND datacenter alike →
  TLS-fingerprint gating; the P0-21 collector needs a browser-grade client.
- Epoch map final: classic-11 (≤2011-01), classic-13 (+TOTALTRADES,ISIN; H1-2011→2024-06),
  UDiFF-34 (2024-07-08→). 13 dated samples hoarded via RawStore. Parser plan: dispatch on
  header signature with an explicit allowlist (unknown header = ParseError); 2 parsers,
  3 fixtures; pre-2011 rows carry no ISIN → P0-09 resolves that era via (symbol, series).
- DC fallback (single Google Cloud vantage): archives tolerated → ADR-009's fallback path is
  alive for bhavcopy; ADR-009 itself unchanged. Announcements portal archive reaches ≥
  Jan-2015 WITH broadcast timestamps; attachment PDFs served from the tolerant nsearchives
  host. Request discipline held: ≤25 residential + 4 DC; both 403s triggered immediate stops.
- Desk-panel debut: portfolio-manager reviewed the plan pre-approval (1 WARN + 2 NOTEs, all
  folded in). Post-change review executed inline (docs-only diff + spike scripts; agent
  budget conserved after earlier 429s).

## 2026-07-13 — P0-06
- First adapter live: `platform ingest bhavcopy --since 2026-05-25 --until 2026-07-10` →
  stored=32, noop=1 (2026-07-08, hoarded during P0-05 — live idempotency proof), holiday=2
  (real mid-week 404s on 2026-05-28 and 2026-06-26, logged as expected absence, exit 0).
  DoD "30 recent days ingested" met with margin; 33 distinct trading days in range.
- "Holiday 404 handled via calendar" at P0-06 = weekends skipped by the range iterator +
  weekday 404 recorded as a presence signal for P0-08 (the calendar derives FROM bhavcopy
  presence and cannot pre-exist the adapter); the presence↔calendar cross-check lands with
  P0-08. PM plan review (3 WARN + 2 NOTE) shaped: range ends at last COMPLETED day, widened
  for unconditional ≥30; testzip() CRC gate; --until/--json recorded as additive doc-14
  extensions.
- Recorded deferral, not deviation: 403/429 → abort-on-first-error for foreground backfills;
  doc 06 §6.1's exponential-backoff + alert IP-block mode belongs to the nightly-cron era
  and lands with P0-17 alerting.
