# 21 · Algorithm Specifications
**Purpose:** precise, implementable specs for every load-bearing algorithm — the "no ambiguity for the coder" document. **Convention:** pseudocode is Python-shaped; all parameters come from config; every algorithm has a named test in doc 16's suites.

## §1 Corporate-action price adjustment (reverse cumulative factors)
For each ISIN, actions sorted by ex_date descending. Price-affecting kinds: split, bonus,
rights (dividends are NOT price-adjusted — cash-credited in ledger; consistent with TRI
benchmarks which include reinvestment).
```
factor(action): split num:den → den/num ; bonus b:a → a/(a+b) ; rights → theoretical
  ex-rights factor from terms (price P_cum, issue price S, ratio r): (P_cum + r·S)/((1+r)·P_cum)
adj_factor(isin, d) = ∏ factor(a) for a.ex_date > d          # =1 for latest dates
adjusted_close(d) = raw_close(d) · adj_factor(isin, d)
```
Same-day multiple actions: multiply factors (order-independent). Demerger: no reliable
formula from ratios alone → `needs_review`; block curation of that ISIN; operator enters
resolved factor from exchange circular (RB-4). Invariant (property test): daily returns
computed from adjusted prices are identical whether adjustment is applied today or after
appending future data.

## §2 PIT as-of semantics (leakage-proof by construction)
Every curated fact row carries `available_at`. All reads go through:
```sql
CREATE VIEW v_asof AS SELECT * FROM t WHERE available_at <= :asof;
-- fundamentals joined to decision dates via DuckDB:
ASOF JOIN prices p ON f.isin=p.isin AND f.available_at <= p.d
```
Property test: recompute any feature with asof=D and asof=D+90; rows dated ≤D must be
byte-identical.

## §3 Liquidity statistics (rolling 60 trading days, per ISIN, daily)
`MDTV = median(traded_value)` · `zero_days_pct = mean(volume==0 or halted)` ·
`amihud = mean(|ret_d| / traded_value_d)` (skip zero-volume days) ·
`ewma_var_t = λ·ewma_var_{t-1} + (1−λ)·ret_t²`, λ=0.94, seeded with 60d sample var;
`vol = sqrt(252·ewma_var)`.

## §4 PIT universe builder (pipeline; emit ALL exclusion reasons, not first)
```
candidates = listings active on d, exchange=NSE, series=='EQ'
exclude if: price<₹20 | age<180 td | ff_mcap<floor (proxy: rank by MDTV until
  fundamentals mature — flagged) | surveillance in {GSM*, ASM stage≥2} |
  zero_days_pct>5% | pending demerger review
investable(book) = position_value(book) ≤ p_max · MDTV      # evaluated at query time
```

## §5 Factors (v1)
`mom_12_1 = adj_close[d−21td] / adj_close[d−252td] − 1` (missing history ⇒ NaN ⇒ excluded)
· `lowvol_score = −vol` · `size = ff_mcap proxy`. Cross-sectional percentile ranks on the
universe as of decision date. Factor values NaN-safe; a name must have full lookback.

## §6 Selection with buffered membership (turnover suppressor)
```
ranked = universe sorted by factor desc (rank 1 = best)
keep   = {h ∈ holdings : rank(h) ≤ buffer·N and not hard_excluded(h)}
adds   = top-ranked non-held names filling to N (skip if !investable)
reasons: entry|hold_buffer|exit_rank|exit_hard(<which>)|skip_liquidity
```
Hard exclusions (surveillance/delisting/liquidity/demerger) override the buffer, always.

## §7 Weights, drift bands, governor, tax overlay (applied in this order)
**Capped inverse-vol (iterative water-filling):**
```
w_i ∝ 1/vol_i → repeat: clip at name_cap(8%)+sector_cap(25%), renormalize uncapped ←
until no new clip (≤ N iters). Residual (from caps at floor) → cash.
```
**Drift bands (intra-quarter):** trade name i only if |w_actual/w_target − 1| > 0.25 or
hard exclusion; rebalance only breached names toward target.
**Drawdown governor (per book, hysteresis state machine):**
NORMAL →(dd ≥ 0.8·budget)→ CAUTION: new-position sizes ×0.5, alert →(dd ≥ budget)→
DEFENSIVE: cash floor 30%, no new entries →(dd ≤ 0.6·budget)→ back to NORMAL. States
are engine inputs, ledger-derived — deterministic and backtestable.
**Tax overlay:** sell signal on lot aged 10–12m and reason==exit_rank (not hard) ⇒ defer
to 12m+1d. March window: realize LTCG up to remaining ₹1.25L exemption on oldest lots,
repurchase next session (India has no wash-sale rule — statutory; step-up is legitimate);
switchable, so backtests measure its value.

## §8 FIFO tax-lot ledger
Per (book, ISIN): deque of lots {open_d, open_price_incl_buy_charges, qty}. SELL pops
from front; per consumed slice: holding = sell_d − open_d; gain classified STCG (≤365d)
/ LTCG; sell-side charges allocated pro-rata by value. Fiscal-year accumulator applies
20% STCG; LTCG taxed 12.5% on max(0, LTCG_FY − 1.25L). Conservation invariant (property):
cash + Σ position_mv + Σ charges + Σ taxes − Σ dividends ≡ initial + Σ realized+unrealized P&L.

## §9 Cost calculator (per order; rates from effective-dated config)
buy: brokerage + 0.10%·v (STT) + 0.015%·v (stamp) + 0.00297%·v (exch) + 0.0001%·v (SEBI)
+ 18% GST on (brokerage+exch+SEBI). sell: same minus stamp, plus DP ₹15.9 per ISIN per
day. AMC ₹300/yr at book level.

## §10 Slippage
`participation = order_value/MDTV`; reject if > tier cap. `bps = base(tier) +
8·sqrt(100·participation)`; buys fill at price·(1+bps/1e4), sells at (1−…).

## §11 Backtest replay loop (driver; engine stays pure)
```
for d in trading_days: mark ledger to adjusted closes; credit dividends(ex_date==d)
  process forced events: delisting → exit at terminal price (worst-case config −100%)
  if pending orders: fill unless band_hit blocks; expire after 3 sessions (reason-logged)
  if d in rebalance_days or drift/governor/hard-event triggers:
      decision = decide(state, view_asof(d), book_cfg)     # PURE
      queue orders for d+1 (default close+slippage; sensitivity: open)
  at fiscal-year end: debit taxes
outputs: NAV series, ledger, orders+reasons, per-trade costs, run manifest
```

## §12 Walk-forward & holdout protocol
Expanding window: fit any estimated param on [t0, t) only; apply on [t, t+step). v1
champion candidates have NO fitted params (constants pre-registered) ⇒ walk-forward
reduces to honest chronology. Holdout: last ~2.5y excluded from ALL variant runs; a
state file records the single permitted evaluation (config hash, timestamp); harness
hard-refuses a second look.

## §13 Multiple-testing haircut & stress suite
With K registered variants over T years, report alongside realized Sharpe the null band:
bootstrap (block, 6-month blocks) K max-Sharpes from zero-mean resampled strategy
returns; champion must exceed the 95th percentile of that max distribution. Stress runs
(each a config overlay): slippage×2 · fundamental-lag+30d (when used) · start-date
jitter ±1q ×8 · sub-period 3y rolling wins · named windows (2018 smallcap, Mar-2020,
sharp-reversal synthetic: invert worst momentum drawdown month ordering).

## §14 Data-validation: index reconstruction (AMENDED — supersedes doc 13 F2 line)
Part A (adjustment correctness): for the 50 largest CA events by mcap, compare our
adjusted return across ex-date vs. an independent chart source; |diff| > 25 bps ⇒ fail.
Part B (breadth): equal-weight proxy of current Nifty50 constituents over trailing 5y —
daily-return correlation vs official TRI ≥ 0.995 AND zero single days with unexplained
|proxy−index| > 5%. Rationale: 0.999 needed historical cap weights, which we correctly
refuse to use (ADR-008). Mini-ADR recorded in doc 07 as ADR-019.

## §15 Strategy decay detection
Monthly: bootstrap the champion's backtest daily returns → distribution of rolling-12m
Sharpe. Compute live rolling-12m Sharpe from shadow ledger. Flag if live < p10 for 2
consecutive quarter-ends ⇒ RB-6 (formal review; never silent retune). Also tracked:
realized-vs-modeled cost gap, hit-rate drift, factor-rank IC trend (diagnostics only).

## §16 Override-alpha
Maintain counterfactual "pure-system" ledger: every proposal executed exactly as
proposed at modeled fills. Annually: actual_return − counterfactual_return, decomposed
per override reason-code. Honest caveat printed on the report: modeled fills ⇒ the
comparison favors neither side systematically only while cost model stays calibrated (§10, ADR-017).

## §17 Event severity (table-driven; agents may annotate, never re-score)
`severity = base(kind) + held?+2 + ranked_topN?+1`; thresholds: ≥4 Telegram now,
3 next-report pack, ≤2 digest. Base: GSM/ASM-add 4 · rating-downgrade 3 · earnings-held
3 · pledge Δ>10pp 2 · bulk-deal cluster 1 · index-drawdown regime 3 (process review).
