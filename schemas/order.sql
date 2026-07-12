-- "order" is a SQL reserved word; the table name is exactly: order (doc 10). side: buy|sell.
-- reasons: the explainability contract [{rule_id, params, evidence_refs[]}] (doc 14).
CREATE TABLE "order" (
    order_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    isin TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INT,
    limit_hint DECIMAL(12,2),
    reasons JSON
);
