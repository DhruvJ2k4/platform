# 11 · Quantitative Research Framework
**Summary:** Rules-first factor investing with buffered construction, drawdown-budgeted risk, and mechanically enforced validation. **Purpose:** the research methodology contract. **Scope:** all books. **Assumptions:** ADR-000 (no ML in decision path v1). **Risks:** momentum crash; overfitting. **Open questions:** India net-of-cost factor premia magnitudes (Milestone 1 answers empirically). **Future extensions:** fundamental factor family; HRP challenger.

## Factor library (versioned pure functions; v1 set)
`mom_12_1` 12-month return skipping most recent month · `vol_ewma` λ=0.94 EWMA daily vol
(default risk input; 60d sample vol as diagnostic) · `mdtv`, `amihud`, `zero_days_pct`
(liquidity) · `size_ff` free-float mcap (proxy until fundamentals mature) ·
`lowvol_rank` inverse-vol ranking factor. Gated P4: `quality_*`, `value_*` (ADR-002
conditions). Every factor: formula, params, version, unit tests, and a one-page
rationale citing the evidence base — no anonymous features.

## Ranking & strategy framework
A strategy = YAML spec: universe params (doc 12/ADR-007) + factor (or fixed-weight factor
blend) + selection (entry_rank N, exit at buffer·N) + weighting + cadence + overlays.
Ranking is cross-sectional on the PIT universe at decision date. No fitted parameters in
v1 champion candidates (momentum lookback etc. are pre-registered constants); anything
fitted later must be walk-forward estimated.

## Portfolio construction (engine rules, shared by both drivers)
Buffered membership (turnover suppression is structural) → capped inverse-vol weights
(8% name / 25% sector, AMFI map) → dynamic N (ADR-014) → cash residual → drift-band
trades intra-quarter (>25% relative drift only) → hard exclusions override everything
(surveillance, series, liquidity failure, delisting risk, pending CA review — any needs_review
corporate action: demerger/rights/other, ADR-023).

## Risk framework
Drawdown budget per book (default 25%) with pre-committed governor: at 0.8× budget new-
position sizing halves + human review; at 1.0× defensive posture (cash floor 30%).
Exposure reporting: name/sector concentration, liquidity-weighted exit time ("days to
liquidate at p_max"), factor exposure drift. **Named factor risk:** momentum crashes in
sharp reversals — governor + mandatory reversal stress (doc 12) are the mitigations;
optional vol-scaled momentum is a pre-registered P2 challenger.

## Rebalancing methodology
Quarterly scheduled + drift bands + event-triggered review (Tier-1 events may advance
review, never bypass the human) + tax overlay: LTCG deferral in months 10–12 unless hard
exclusion; optional March exemption harvesting. All overlays are backtestable switches —
their value is measured, not assumed.

## Event-driven analysis
Events land as curated rows (doc 10); severity rules per kind (earnings-of-held: review;
ASM/GSM add: hard exclusion; rating downgrade: Tier 1; pledge jump >10pp QoQ: Tier 2 flag;
bulk-deal cluster: Tier 2; index drawdown >15%: process review). Evidence packs assembled
into proposals; no autonomous action.

## Validation methodology (mechanically enforced by harness)
Pre-registration in git before results · ≤ 6 variants per milestone (budget enforced;
refusal at #7) · walk-forward only · single-look holdout (~2.5 most recent years) ·
robustness gauntlet: 2× slippage, ±30d fundamental-lag stretch, start-date jitter (8
offsets), sub-period consistency, 2018 smallcap crash + Mar-2020 + reversal scenario ·
deflated-Sharpe context reported · incubation ≥ 1 quarter (ADR-018) · promotion only via
champion/challenger ADR. Live: shadow ledger, decay dashboard (rolling 12m live Sharpe
vs. backtest bootstrap band; <10th percentile for 2 consecutive quarters ⇒ formal
review), override-alpha report annually.
