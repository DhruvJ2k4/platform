-- proposal: operational, append-only (doc 10). status/human_action value sets firm up in P2.
-- "asof" is a DuckDB reserved word (ASOF JOIN); the column name is exactly: asof.
CREATE TABLE proposal (
    proposal_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    "asof" DATE,
    run_id TEXT,
    status TEXT,
    human_action TEXT,
    override_reason TEXT,
    created_at TIMESTAMP
);
