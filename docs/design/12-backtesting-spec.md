# 12 · Backtesting Specification
**Summary:** Replay driver over the shared engine with full Indian cost/tax realism. **Purpose:** the honesty contract for all historical claims. **Scope:** equity delivery, long-only, EOD. **Assumptions:** rates as of Jul 2026, effective-dated in config, re-verified every budget day. **Risks:** model-vs-reality gap (closed by ADR-017 reconciliation). **Open questions:** none blocking. **Future extensions:** swing-book execution model (T+1 latency variant, ADR-12).

## Execution assumptions
Signals computed on close of decision date D; fills at D+1 close adjusted by slippage
(default) — sensitivity run at D+1 open. Delisting: forced exit at terminal bhavcopy
price; suspended-then-delisted worst-case config −100%. Circuit-locked names: unfillable
that day; order persists ≤ 3 sessions then cancels (reason-logged). Cash earns 0%
(conservative; liquid-fund modeling is a P2 refinement).

## Cost model (per side unless noted; config `costs.yaml`)
Brokerage ₹0 delivery (Zerodha; per-broker adapterized) · STT 0.10% buy AND sell ·
stamp 0.015% buy · NSE txn ~0.00297% · SEBI ₹10/crore · GST 18% on (brokerage+txn+SEBI)
· DP ≈ ₹15.9 per ISIN per sell day · AMC ₹300/yr portfolio-level. Round-trip statutory
≈ 0.23% + DP flat.

## Slippage model
`bps = base(tier) + 8·sqrt(participation_pct)`; tiers by MDTV: >₹25Cr:5 · ₹5–25Cr:15 ·
₹1–5Cr:30 · ₹20L–1Cr:60 (max 2%/day participation) · <₹20L uninvestable. Recalibrated
from ≥30 real fills (ADR-017).

## Tax model
FIFO lots (mandated for demat) · STCG 20% ≤12m · LTCG 12.5% >12m above ₹1.25L/yr
aggregate exemption · dividends taxed at configured slab (default 30%) · taxes debited
at fiscal-year end · overlays (deferral, harvesting) as engine switches.

## Corporate actions in backtests
Prices pre-adjusted in curated (splits/bonuses); cash dividends credited on ex-date from
CA table (cash_amount is credited ONLY for kind=dividend — a rights row's cash_amount is the
subscription premium, not a credit, ADR-023); any needs_review CA (demerger/rights/other/
amount-less dividend — the last cash-resolved per ADR-025):
resolved entries only (pending ⇒ name uninvestable historically for the unresolved window —
conservative). Note (P0-10 → P0-11): the CA feed's covered window may be shorter than price
history; the adjuster must treat price dates before the CA coverage floor (min covered ex_date)
as under-covered — NaN/exclude, never a partially-adjusted price.

## Benchmarks
Nifty 50 TRI and Nifty Midcap 150 TRI (official values via TRI ingest), each net of
0.2%/yr synthetic TER and identical tax treatment on the same rebalance dates as the
strategy (fair comparison, not raw index).

## Walk-forward & stress
As doc 11 §Validation. Stress suite additionally reports: max time-under-water, worst
rolling-12m vs. benchmark, cost-doubling breakeven, and liquidity-crunch scenario
(MDTV −50% ⇒ forced participation rise ⇒ slippage repricing).

## Acceptance (engine correctness — doc 16 details)
Golden scenario to the paisa · property suite green · vectorbt oracle match (costless
config) within float tolerance · index-reconstruction gate upstream.
