-- lot: open FIFO tax lots (doc 10, doc 21 §8). open_price includes pro-rated buy charges,
-- hence sub-paisa scale (12,4); FIFO consumption is recorded via fill links.
CREATE TABLE lot (
    lot_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    isin TEXT NOT NULL,
    open_d DATE NOT NULL,
    open_price DECIMAL(12,4),
    qty_open INT,
    qty_remaining INT
);
