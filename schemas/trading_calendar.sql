-- trading_calendar: derived from bhavcopy presence (doc 10). session: normal|special|muhurat
-- (P0-08: muhurat from operator config/calendar.yaml — SsnId is F1 even on Muhurat days;
-- weekend presence or non-F1 SsnId => special; else normal).
CREATE TABLE trading_calendar (
    d DATE PRIMARY KEY,
    session TEXT
);
