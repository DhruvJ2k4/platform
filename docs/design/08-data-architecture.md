# 08 · Data Architecture
**Summary:** Immutable raw → deterministic curated → features-as-code; versioning by rebuild; validation at the curation gate; lineage via run manifests. **Purpose:** authoritative data-layer rules. **Scope:** all data. **Assumptions:** ADR-001/003/016. **Risks:** curation determinism (property-tested). **Open questions:** free-float source (PRD Q1). **Future extensions:** BSE, fundamentals maturation.

## Layers
**RAW.** Exactly-as-downloaded files, immutable, hoarded forever, sha256-registered in
`raw_registry(source, logical_date, path, sha256, fetched_at)`. Raw is the only
irreplaceable asset; it is what the encrypted backup protects. Never parsed in place;
never deleted, even when wrong (supersession by re-download creates a new row).

**CURATED.** Deterministic function of (raw, code@git, config@git). Tables in doc 10.
Disposable by design: `curate --rebuild` reconstructs it identically (verified by the
rebuild-twice-byte-compare test). Published atomically behind the validation gate.
PIT rule: every fact row carries `available_at`; all reads go through as-of views that
filter `available_at <= asof` — look-ahead is prevented physically, not procedurally.

**FEATURES.** Code, not storage (ADR-016 companion): versioned pure functions + a
content-addressed cache (safe to `rm -rf` at any time).

**RESEARCH & PORTFOLIO DATASETS.** `runs/<run_id>/` = manifest (code hash, config hash,
raw watermarks, variant-budget state) + outputs (NAV, ledger, orders, reasons, report).
Champion runs additionally pin a materialized curated copy (a handful/yr — cheap).
Live ledger and proposals are append-only tables (doc 10) — the only data whose loss
rebuild cannot heal, so they are in the backup set alongside raw.

## Versioning & lineage
Identity of any derived artifact = (raw watermark set, code commit, config commit).
The manifest records it; `platform reproduce <run_id>` re-executes it. Lineage queries
("which raw files fed this proposal?") resolve from manifest watermarks — no lineage
framework needed at this scale.

## Validation (the gate)
Schema contracts (pandera) at curation publish · invariant suite: adjusted-return
invariance under adjustment timing; ledger conservation; calendar completeness; universe
monotonicity checks (a delisted ISIN never reappears); cross-source spot checks (CA
sample vs. independent source; fundamentals sample vs. Screener export quarterly) ·
volumetric monitors (row counts vs. expectation; null rates). Breach ⇒ publish blocked +
alert; consumers keep last-good curated (stale-but-consistent principle).
