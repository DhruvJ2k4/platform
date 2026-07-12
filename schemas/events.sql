-- events (doc 10). isin NULL for market-wide events (e.g. index-drawdown regime, doc 21 §17);
-- kind values grow with the P3 severity rules; payload is source-shaped JSON.
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    isin TEXT,
    kind TEXT NOT NULL,
    severity INT,
    payload JSON,
    observed_at TIMESTAMP
);
