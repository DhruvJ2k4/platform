-- security: master record per ISIN (doc 10). status: active|delisted|suspended.
CREATE TABLE security (
    isin TEXT PRIMARY KEY,
    name TEXT,
    status TEXT,
    first_listed DATE,
    delisted_on DATE,
    delist_terminal_price DECIMAL(12,2)
);
