-- index_tri: official TRI series consumed as benchmark values only (doc 10, ADR-008).
CREATE TABLE index_tri (
    index_name TEXT NOT NULL,
    d DATE NOT NULL,
    tri_value DECIMAL(18,6)
);
