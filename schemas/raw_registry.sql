-- raw_registry: immutable raw file ledger (doc 08). No PK by design: re-downloads create
-- supersession rows sharing (source, logical_date); raw is never mutated or deleted.
CREATE TABLE raw_registry (
    source TEXT NOT NULL,
    logical_date DATE NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL
);
