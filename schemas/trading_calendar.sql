-- trading_calendar: derived from bhavcopy presence (doc 10).
-- session value set is not yet doc-enumerated; it firms up with P0-08 (e.g. muhurat sessions).
CREATE TABLE trading_calendar (
    d DATE PRIMARY KEY,
    session TEXT
);
