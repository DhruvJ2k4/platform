-- run: manifest header per run (docs 08/10); run_id format {kind}-{yyyymmdd}-{shorthash} (doc 23).
-- book_id NULL for non-book runs (ingest/curate); raw_watermarks pins lineage (ADR-016).
CREATE TABLE run (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    book_id TEXT,
    code_hash TEXT,
    config_hash TEXT,
    raw_watermarks JSON,
    started_at TIMESTAMP,
    status TEXT
);
