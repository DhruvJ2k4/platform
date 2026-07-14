# 10 · Database Design
**Summary:** DuckDB over Parquet; 15 tables (14 core + raw registry); partitioning by year; sorting in place of indexes. **Purpose:** physical schema. **Scope:** curated + operational tables (raw is files + registry). **Assumptions:** ADR-003/016/021. **Risks:** schema migrations (append-and-view policy below). **Open questions:** none blocking. **Future extensions:** BSE via `exchange` columns already present.

## Entity overview (ER, described)
`security` 1—N `listing` (per exchange/symbol/series, effective-dated) · `security` 1—N
`prices_adj` / `corporate_actions` / `fundamentals_pit` / `events` / `universe_membership`
· `book` 1—N `proposal` 1—N `order` 1—N `fill`; `book` 1—N `lot` (ledger) · `run` 1—1
manifest, 1—N artifacts.

## Core DDL (mirror; authoritative copies live in schemas/, NOT NULL detail there — ADR-021)
```sql
CREATE TABLE security (isin TEXT PRIMARY KEY, name TEXT, status TEXT,           -- active|delisted|suspended
  first_listed DATE, delisted_on DATE, delist_terminal_price DECIMAL(12,2));
CREATE TABLE listing (isin TEXT, exchange TEXT, symbol TEXT, series TEXT,
  valid_from DATE, valid_to DATE);                                              -- effective-dated ticker map
CREATE TABLE trading_calendar (d DATE PRIMARY KEY, session TEXT);              -- from bhavcopy presence; session: normal|special|muhurat (P0-08)
CREATE TABLE prices_adj (isin TEXT, d DATE, exchange TEXT, series TEXT,
  o DECIMAL(12,2), h DECIMAL(12,2), l DECIMAL(12,2), c DECIMAL(12,2),
  close_unadj DECIMAL(12,2), volume BIGINT, traded_value DECIMAL(18,2),
  adj_factor DOUBLE, band_hit TEXT,                                             -- upper|lower|null
  PRIMARY KEY (isin, d));
CREATE TABLE corporate_actions (isin TEXT, ex_date DATE, kind TEXT,             -- split|bonus|dividend|demerger|rights|buyback
  ratio_num INT, ratio_den INT, cash_amount DECIMAL(12,2), status TEXT,         -- auto|needs_review|resolved
  source_ref TEXT, available_at TIMESTAMP);
CREATE TABLE universe_membership (isin TEXT, d DATE, investable BOOL,
  mdtv DECIMAL(18,2), amihud DOUBLE, zero_days_pct DOUBLE, surveillance TEXT,
  excl_reasons TEXT[]);                                                         -- PIT universe: the only allowed universe source
CREATE TABLE fundamentals_pit (isin TEXT, period_end DATE, statement TEXT,
  item TEXT, value DECIMAL(18,2), filed_at TIMESTAMP, available_at TIMESTAMP,
  source TEXT, confidence TEXT, revision_seq INT);                              -- confidence: native|bridged
CREATE TABLE events (event_id TEXT PRIMARY KEY, isin TEXT, kind TEXT,
  severity INT, payload JSON, observed_at TIMESTAMP);
CREATE TABLE index_tri (index_name TEXT, d DATE, tri_value DECIMAL(18,6));
CREATE TABLE raw_registry (source TEXT, logical_date DATE, path TEXT,
  sha256 TEXT, fetched_at TIMESTAMP);                                           -- raw ledger (doc 08): supersession rows, no PK
-- operational (append-only, in backup set):
CREATE TABLE proposal (proposal_id TEXT PRIMARY KEY, book_id TEXT, "asof" DATE, -- asof: DuckDB reserved word, quoted
  run_id TEXT, status TEXT, human_action TEXT, override_reason TEXT, created_at TIMESTAMP);
CREATE TABLE "order" (order_id TEXT PRIMARY KEY, proposal_id TEXT, isin TEXT,
  side TEXT, qty INT, limit_hint DECIMAL(12,2), reasons JSON);
CREATE TABLE fill (fill_id TEXT PRIMARY KEY, order_id TEXT, d DATE, qty INT,
  price DECIMAL(12,2), charges JSON, source TEXT);                              -- source: contract_note|manual
CREATE TABLE lot (lot_id TEXT PRIMARY KEY, book_id TEXT, isin TEXT,
  open_d DATE, open_price DECIMAL(12,4), qty_open INT, qty_remaining INT);      -- open_price incl. buy charges → (12,4)
CREATE TABLE run (run_id TEXT PRIMARY KEY, kind TEXT, book_id TEXT,
  code_hash TEXT, config_hash TEXT, raw_watermarks JSON, started_at TIMESTAMP, status TEXT);
```

## Physical strategy
Parquet partitioned by year for `prices_adj` and `fundamentals_pit`; files sorted
(isin, d) — DuckDB zone-maps make explicit indexes unnecessary at this scale (~10⁷ rows,
low-GB total). Operational tables live in one DuckDB file, WAL-checkpointed after jobs,
included in nightly backup. Migrations: additive columns + versioned views; destructive
changes require rebuild (which we can always do — ADR-016). DECIMAL always carries explicit
(p,s) — DuckDB defaults bare DECIMAL to (18,3) — and typed reads go through the Arrow path
(quant.schemas.arrow_frame), never .df(), which degrades DECIMAL to float64 (ADR-021).
