# 19 · Final Self-Review of the Package
**Purpose:** the honest closing audit requested before calling the design complete.

**Remaining weaknesses (real, accepted or scheduled):**
1. **Corporate-actions residual risk** — the review queue + tests reduce but cannot
   eliminate it; demergers and exotic actions will consume operator judgment forever.
   This is the platform's permanent tax; budgeted, not solved.
2. **Historical fundamentals bridge quality is unknown** until measured; value/quality
   research may effectively wait for native PIT accumulation (by design, but slow).
3. **Solo bus factor** — docs and runbooks mitigate; nothing eliminates it.
4. **Un-validated assumptions carried into P0** (IP tolerance, archive epochs,
   announcement archive depth) — deliberately front-loaded as week-1 spikes.
5. **Statistical honesty ceiling** — even perfect discipline over ~12 decisions/yr means
   the live verdict on the champion takes years; incubation and shadow ledgers shorten
   nothing, they only keep us honest meanwhile.

**Potential overengineering (watched, with tripwires):**
Variant-budget enforcement in code (keep — it disciplines the operator, the cheapest
component per unit of harm prevented) · drawdown governor dual thresholds (keep; ~30
lines) · **this documentation package itself** — 19 documents for one developer is the
single largest overengineering risk here; tripwire: any doc not touched in 6 months gets
merged or archived; ADRs and runbooks are the protected core.

**Hidden maintenance costs surfaced:** parser epochs (each format change ≈ 2–6h) ·
demerger queue (≈ 1–3/quarter in a 20-name book's universe) · rate re-verification
(budget day, 1h) · dependency update days (monthly, 1h) · drill calendar (4×/yr, ~6h
total). Sum fits inside the 2hr/wk envelope with margin — but barely in results season.

**Missing documentation (deliberate deferrals):** per-parser epoch notes (written as
epochs are met, not speculatively) · Kite adapter design (P2/P4) · swing-book spec
(exists only as its admission gate — writing more now would be design-ahead-of-evidence).

**Future scalability risks:** none material to ₹1Cr scale (workload is ~10⁷ rows); the
real scaling limits are operator attention and decision-count statistics, and no
architecture fixes those.

**Further simplification opportunities (best candidates if pressure appears):**
merge docs 13+14 into the code repo as docstrings+schemas (kill two documents) ·
drop the features cache until a profile proves it needed (start uncached) ·
ManualBroker could remain permanent — Kite execution may never justify its token-
management friction at quarterly cadence.

**Verdict:** the package is complete for implementation start. The design's center of
gravity — immutable raw, deterministic rebuild, one engine, human gate, pre-registered
evaluation — is the part that must not erode; everything else is legitimately negotiable
with evidence.
