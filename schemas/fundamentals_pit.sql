-- fundamentals_pit (doc 10, ADR-002). confidence: native|bridged.
-- PIT: rows visible only where available_at <= asof; bridged rows carry stretched-lag stress.
CREATE TABLE fundamentals_pit (
    isin TEXT NOT NULL,
    period_end DATE,
    statement TEXT,
    item TEXT,
    value DECIMAL(18,2),
    filed_at TIMESTAMP,
    available_at TIMESTAMP,
    source TEXT,
    confidence TEXT,
    revision_seq INT
);
