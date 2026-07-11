# 02 · Market & Research Document
**Summary:** Survey of retail platforms, institutional practice, and the quant literature as they bear on this design. **Purpose:** ground design choices in what demonstrably works. **Scope:** Indian equities focus. **Assumptions:** landscape as of mid-2026. **Risks:** platform features change; re-survey annually. **Open questions:** depth of India-specific factor literature on net-of-cost premia. **Future extensions:** formal annual literature review task.

## Existing Indian retail platforms
| Platform | What it does well | Why it is not this platform |
|---|---|---|
| Screener.in | Fundamental screening UX, per-company exports | Snapshot (restated) data; no PIT; no portfolio engine → used here as a validation oracle only |
| smallcase | Packaged model portfolios, execution integration | Consumes strategies; doesn't let you research your own with owned data |
| sharpely | Advertises PIT, as-reported fundamentals and walk-forward backtests — validates our methodology market-wide | Closed data, subscription, no tax-lot/book control, platform-longevity risk |
| BacktestIndia | Includes delisted names; models Indian LTCG/STCG in backtests | Educational tool; fixed universe/strategy surface |
| Trendlyne / Tickertape | Rich display analytics, alerts | No API, no PIT guarantees; display-grade |
| Streak / algo platforms | Intraday strategy automation | Wrong horizon; execution-first, research-thin |

**Reading:** the market confirms both demand and the two hard problems (PIT correctness,
Indian cost/tax realism). No product offers owned data + owned engine + tax-lot fidelity,
which is exactly the part worth building; everything else is commodity.

## Institutional practice (what internal platforms actually converge on)
Immutable raw data with derived-on-rebuild layers · point-in-time everything · a single
implementation of portfolio logic shared by research and production (skew is a named,
feared bug class) · pre-registration and multiple-testing discipline · champion/challenger
promotion with incubation · costs modeled to the basis point and reconciled against fills ·
boring batch schedulers over exotic infrastructure at low frequencies.

## Quant research: proven vs. emerging vs. avoid
**Proven (decades, multi-market, survives costs at low turnover):** momentum (12-1),
low-volatility, quality, value (regime-dependent), size interacting with liquidity;
turnover suppression via buffered membership; vol-targeted position scaling.
**Documented failure modes to engineer for:** momentum crashes in sharp reversals
(2009-type) — mitigated here by the drawdown governor and mandatory reversal stress test;
smallcap factor results are inflated by survivorship (~5pp/yr in NIFTY Smallcap 250
evidence) and by ignoring circuit/liquidity frictions.
**Emerging (watch, don't build):** ML ranking ensembles (defensible at large N and daily
horizons, not at 20 names/quarterly), graph/supply-chain signals (data unavailable cheaply
for India), transformer forecasters (no robust net-of-cost retail evidence).
**Avoid (evidence-backed):** RL for allocation at low decision counts · social-sentiment
trading for Indian retail · optimization atop noise-level covariance estimates ·
survivor-biased backtesting of any kind.
