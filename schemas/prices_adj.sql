-- prices_adj: adjusted EOD prices (doc 10). band_hit: upper|lower|NULL.
-- Money columns at paisa precision; adj_factor is factor math, deliberately DOUBLE (doc 23).
CREATE TABLE prices_adj (
    isin TEXT NOT NULL,
    d DATE NOT NULL,
    exchange TEXT,
    series TEXT,
    o DECIMAL(12,2),
    h DECIMAL(12,2),
    l DECIMAL(12,2),
    c DECIMAL(12,2),
    close_unadj DECIMAL(12,2),
    volume BIGINT,
    traded_value DECIMAL(18,2),
    adj_factor DOUBLE,
    band_hit TEXT,
    PRIMARY KEY (isin, d)
);
