-- fill (doc 10). source: contract_note|manual; charges is the per-fill charge breakdown JSON.
CREATE TABLE fill (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    d DATE NOT NULL,
    qty INT,
    price DECIMAL(12,2),
    charges JSON,
    source TEXT
);
