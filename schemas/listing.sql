-- listing: effective-dated (exchange, symbol, series) map per ISIN (doc 10).
-- No PK by design: one ISIN carries many listing rows over time.
-- valid_from NULL = start unknown / open past (predates records — ADR-022);
-- valid_to NULL = open-ended. Listing answers IDENTITY only, never existence/age/activity.
CREATE TABLE listing (
    isin TEXT NOT NULL,
    exchange TEXT NOT NULL,
    symbol TEXT NOT NULL,
    series TEXT NOT NULL,
    valid_from DATE,
    valid_to DATE
);
