# 09 · Data Source Evaluation
**Summary:** Source-by-source verdicts; the architecture is "own the free official feeds; validate against snapshot sites; buy nothing." **Purpose:** settle sourcing. **Scope:** all inbound data. **Assumptions:** rates/portals as of Jul 2026; re-verified each budget day. **Risks:** portal hostility drift. **Open questions:** archive epoch map (P0). **Future extensions:** BSE mirror feeds.

| Source | Role | Quality | Cost | PIT | History | API/access | Licensing | Maint. | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| NSE bhavcopy (+archives) | Prices/volumes/series incl. delisted | High (official) | Free | Yes by nature | ~20y | File downloads; epochs | Public data | Med (epochs) | **Core** |
| NSE corporate actions | Adjustments, dividends | High | Free | Yes | Long | File/portal | Public | Med (demergers manual) | **Core** |
| NSE filings/announcements (XBRL/CSV) | PIT fundamentals + event layer | High | Free | **Yes (broadcast ts)** | Fwd + partial archive | Portal; bot-sensitive | Public regulatory | Med-high (weakest link; absence-alarms) | **Core (P1 collect-early)** |
| ASM/GSM surveillance lists | Hard exclusions | High | Free | Yes (daily) | Fwd | File | Public | Low | **Core** |
| NSE Indices TRI values | Benchmarks | High | Free | Yes | Long | File/portal | Public (values) | Low | **Core** |
| Broker (Kite ₹500/mo) | Live quotes at execution; candles | Good | ₹500/mo | No (survivor list) | 10y intraday | Good API | No redistribution | Low | Optional P2 |
| Screener.in | Validation oracle, display | Good UX | Free | No | ~10y shown | Per-company export | ToS-restricted | Low (sampled) | Oracle only |
| sharpely / BacktestIndia | Methodology cross-checks | n/a | Free/paid | Claimed | n/a | UI | n/a | None | External sanity checks |
| Trendlyne/Tickertape | — | Display-grade | Freemium | No | — | None official | Restricted | High if scraped | Rejected |
| Alpha Vantage / FMP | — | India coverage inadequate | $ | Unclear | Shallow | Good (US) | OK | Low | Rejected |
| Kaggle dumps / yfinance | Prototyping sandbox only | Unverified | Free | No | Static | n/a | Varies | n/a | Never critical-path |

**Recommended architecture (final):** three concentric rings — (1) core official feeds
owned and hoarded; (2) validation oracles sampled read-only; (3) optional broker feed at
execution time only. No paid research-data dependency exists anywhere in the design.
