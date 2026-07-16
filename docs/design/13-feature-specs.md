# 13 · Feature Specifications (major features; acceptance criteria are the contract)
**Summary:** Implementation-ready specs. **Purpose:** unambiguous build targets. **Scope:** P0–P3 features. Format per feature: Input → Output → Logic → Edge cases → Acceptance.

## F1 Bhavcopy ingestion & backfill (P0)
In: date/range. Out: raw files + registry rows. Logic: LLD 6.1. Edge: holidays (calendar),
Muhurat session, format epochs, re-download supersession. Accept: 15y backfill completes
unattended; re-run of any date is a no-op; holiday 404 ≠ alert; injected corrupt file
rejected by checksum.

## F2 Corporate-actions adjustment (P0 — highest-risk component)
In: CA table + unadjusted prices. Out: `prices_adj` with adj_factor chain. Logic: reverse
cumulative factors from ex-dates; dividends NOT price-adjusted (credited as cash in
ledger); any needs_review CA (demerger/rights/other) → review queue (block + flag; ADR-023).
Edge: same-day multiple actions; actions on suspended names; rights issues → review queue
(operator enters factor from circular; auto-from-terms falsified — the feed's faceVal is
anachronistic so issue price S is unrecoverable, ADR-023); bonus on partly-paid/preference
(queue). Accept: golden scenario; adjustment-timing invariance property; two-part validation per doc 21 §14 / ADR-019 (CA spot-checks ≤25bps; EW-proxy corr ≥ 0.995, no unexplained >5% days); ITC-Hotels-class demerger lands in
queue, not in data.

## F3 PIT universe builder (P0)
In: prices_adj, listings, surveillance, liquidity stats. Out: `universe_membership` daily.
Logic: EQ series only; hygiene (price ≥ ₹20, age ≥ 180td, ff-mcap floor); surveillance
hard-exclusions; investability vs. book corpus computed at query time (corpus is a
parameter, not baked in). Edge: relist after suspension (age reset); symbol change
mid-window. Accept: `universe --date 2016-03-31` returns in <1s with exclusion reasons
per name; monotonicity invariants green.

## F4 PIT fundamentals collector (P1, collect-early)
In: filings portal. Out: raw XBRL/CSV + `fundamentals_pit` rows with `filed_at`. Edge:
revisions (revision_seq), consolidated vs. standalone (store both, tag), broken XBRL
(raw kept, parse quarantined). Accept: results-season day yields rows with broadcast
timestamps; absence-alarm fires on 3 silent business days in season; quarterly Screener
sample check <2% discrepancy or ticket.

## F5 Backtest run (P1)
In: strategy YAML + date range. Out: run dir (manifest, NAV, ledger, orders+reasons,
report). Accept: doc 12 acceptance; deterministic across two executions; variant budget
enforced (7th registered variant refused).

## F6 Quarterly proposal (P2)
In: book config, live ledger, curated-asof-today. Out: proposal HTML + orders CSV +
proposal/order rows. Logic: LiveDriver → engine → renderer; freshness gate; broker-
holdings reconciliation precondition. Edge: stale data (refuse), unreconciled holdings
(refuse), infeasible constraints (logged relaxation). Accept: every order shows rule_id
chain + cost/tax estimate; approve/modify/veto captured with reason codes.

## F7 Ledger & contract-note reconciliation (P2)
In: fills, contract notes (PDF/CSV). Out: lots, realized P&L, cost-gap report. Accept:
golden tax scenario (STCG/LTCG boundary, exemption) to the rupee; >5bps modeled-vs-actual
gap raises ticket; slippage recalibration report after 30 fills.

## F8 Monitoring & decay (P3)
In: runs, ledger, proposals. Out: status page, decay dashboard, override-alpha annual
report; dead-man + absence alarms. Accept: 3 injected-fault drills (dead cron, corrupt
download, missed week) detected as designed; decay flag fires on synthetic degraded
series; override-alpha report renders with ≥ 4 quarters of data.
