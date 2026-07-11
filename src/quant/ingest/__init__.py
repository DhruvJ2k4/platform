"""Source ingest adapters, one per source (bhavcopy, corporate actions, filings, surveillance, TRI).

Contract (doc 06 §6.1): fetch a source for a logical date, write an immutable raw file plus a
registry row, and do nothing else. Idempotent by (source, logical_date); re-downloads create
supersession rows, never mutations. Parsing lives in curation — raw is stored even when it will
fail to parse, so data is never lost.
"""
