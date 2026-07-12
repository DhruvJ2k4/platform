-- universe_membership: the only allowed universe source (doc 10, ADR-008); PIT by d.
-- surveillance value set (GSM*/ASM stages) is source-shaped, not doc-enumerated.
CREATE TABLE universe_membership (
    isin TEXT NOT NULL,
    d DATE NOT NULL,
    investable BOOL,
    mdtv DECIMAL(18,2),
    amihud DOUBLE,
    zero_days_pct DOUBLE,
    surveillance TEXT,
    excl_reasons TEXT[]
);
