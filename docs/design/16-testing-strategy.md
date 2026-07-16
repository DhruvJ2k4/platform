# 16 · Testing Strategy
**Summary:** Correctness concentrated where silent corruption enters: adjustments, tax lots, PIT semantics, engine purity. **Purpose:** test plan of record.

**Unit:** every factor function, cost/tax calculators, parsers per format epoch (fixture
files committed per epoch).
**Property (hypothesis):** ledger conservation (cash+positions+costs+taxes ≡ initial+P&L)
· adjusted-return invariance to adjustment timing · NAV continuity off cashflow days ·
PIT no-future-rows (shift asof, assert unreachable) · curation determinism (rebuild
twice, byte-compare) · FIFO ordering invariants · CA classifier totality + conservation
(classify never raises on arbitrary text; every parsed action is kept or dropped for exactly
one reason; review-bucket kinds — demerger/rights/other — are always needs_review; P0-10).
**Golden:** hand-computed 3-stock/8-quarter scenario with split, bonus, dividend,
delisting, LTCG/STCG boundary, exemption — reproduced to the paisa on every change.
**Oracle:** costless momentum config vs. vectorbt within float tolerance (guards the
replay driver, then our cost model is the only divergence source).
**Integration:** fixture-raw → full pipeline → known curated checksums; F1–F8 acceptance
flows from doc 13.
**Regression:** champion strategy result pinned; any diff on re-run of its manifest fails CI.
**Performance:** budget tests — daily pipeline < 15 min p95 on reference box; 15y single-
config backtest < 5 min.
**Data validation (production, continuous):** doc 08 gate + invariant suite + volumetric
monitors; treated as tests that run forever.
**Acceptance:** doc 13 criteria + doc 18 phase exit drills (3 injected faults, restore
drill) executed and logged, not assumed.
