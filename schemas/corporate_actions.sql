-- corporate_actions (doc 10). kind: split|bonus|dividend|demerger|rights|buyback;
-- status: auto|needs_review|resolved. PIT: rows visible only where available_at <= asof.
CREATE TABLE corporate_actions (
    isin TEXT NOT NULL,
    ex_date DATE NOT NULL,
    kind TEXT NOT NULL,
    ratio_num INT,
    ratio_den INT,
    cash_amount DECIMAL(12,2),
    status TEXT,
    source_ref TEXT,
    available_at TIMESTAMP
);
