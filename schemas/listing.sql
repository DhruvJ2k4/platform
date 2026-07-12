-- listing: effective-dated (exchange, symbol, series) map per ISIN (doc 10).
-- No PK by design: one ISIN carries many listing rows over time; valid_to NULL = open-ended.
CREATE TABLE listing (
    isin TEXT NOT NULL,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    series TEXT NOT NULL,
    valid_from DATE NOT NULL,
    valid_to DATE
);
