# 09 · Data Source Evaluation
**Summary:** Source-by-source verdicts; the architecture is "own the free official feeds; validate against snapshot sites; buy nothing." **Purpose:** settle sourcing. **Scope:** all inbound data. **Assumptions:** rates/portals as of Jul 2026; re-verified each budget day. **Risks:** portal hostility drift. **Open questions:** none blocking — archive epoch map and IP-tolerance resolved, announcements depth ≥ Jan-2015 verified (pre-2015 floor unbracketed, non-blocking); see P0-05 findings below. **Future extensions:** BSE mirror feeds.

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

## P0-05 spike findings (2026-07-13; operator-invoked, residential IP, ≤25 requests total)

**Client-shape gate — the load-bearing discovery.** NSE's edge (Akamai) filters primarily on
request/client shape, not (only) IP:
- `archives.nseindia.com` and `nsearchives.nseindia.com`: HTTP 200 from a residential IP with
  the full browser header set (UA + Accept + Accept-Language + Referer); a bare-UA httpx call
  got 403. Both hosts serve both format eras interchangeably. **P0-06 adapter must send all
  four headers.**
- `www.nseindia.com` (API surface, incl. corporate-announcements): **403 pre-cookie for both
  httpx and curl** from a residential IP — the edge rejects non-browser TLS fingerprints
  outright. The P0-21 filings collector must budget for a browser-grade client (TLS
  impersonation or browser automation). Empirically confirms this row's "bot-sensitive;
  weakest link" verdict.

**Bhavcopy epoch map** (13 dated samples 2010–2026, all hoarded via the raw store):
| Epoch | Observed range | URL pattern | Header signature |
|---|---|---|---|
| E1 classic-11 | ≤ 2011-01-12 | `archives…/content/historical/EQUITIES/{Y}/{MMM}/cm{DD}{MMM}{Y}bhav.csv.zip` | `SYMBOL,…,TOTTRDVAL,TIMESTAMP,` (11 cols, trailing comma) |
| E2 classic-13 | 2011-07-13 → 2024-06 (boundary inside H1-2011) | same as E1 | E1 + `TOTALTRADES,ISIN,` |
| E3 UDiFF-34 | 2024-07-08 → present | `nsearchives…/content/cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | `TradDt,BizDt,Sgmt,…,Rsvd4` (34 cols) |

**Parser plan (feeds P0-07, sizing toward its 8h low end):** dispatch on *header signature*,
never on date. Two parsers: `classic` (one code path; treats `TOTALTRADES`/`ISIN` as optional
columns and pins BOTH observed signatures in an explicit allowlist — an unknown signature is a
ParseError, never a guess) and `udiff` (34-col; filter `SctySrs == EQ` per ADR-006; `Sgmt/Src`
sanity-checked). One trimmed fixture per signature (3 fixtures) cut from the hoarded samples.
Implication flagged for P0-09: pre-2011 rows have **no ISIN** — the security master must
resolve that era via effective-dated (symbol, series) listings.
`sec_bhavdata_full_{DDMMYYYY}.csv` (delivery quantities) noted as a P0-13 candidate; not
probed (request budget).

**Announcements archive depth (operator browser check, 2026-07-13):** not measurable from a
plain HTTP client (see client-shape gate), but the portal UI returns announcement rows with
full BROADCAST DATE/TIME plus RECEIPT timestamps back to **at least January 2015** (verified
windows: Jan–Nov 2019 and 12–16 Jan 2015, Reliance; columns: SYMBOL, COMPANY NAME, SUBJECT,
DETAILS, BROADCAST DATE/TIME, RECEIPT, DISSEMINATION, DIFFERENCE, ATTACHMENT; a Download-.csv
export exists in the UI). Pre-2015 floor left unbracketed — non-blocking. Two implications for
P0-21 / ADR-002: (1) historical broadcast timestamps exist ≥11 years back, so the lag-stamped
bridge can be *mined* from the portal archive rather than assumed; (2) attachment PDFs are
served from `nsearchives.nseindia.com/corporate/…` — the tolerant host — so document retrieval
can bypass the hostile www API once URLs are known (row metadata still needs the browser-grade
client).

**Datacenter-IP tolerance (single-vantage, fallback-path evidence only; ADR-009 unchanged):**
operator-run Colab probe, Google Cloud egress 34.148.89.104, 2026-07-13: archives-classic-2019
HTTP 200 (67,213 B — byte-identical to the residential download), archives-udiff-2025 HTTP 200
(170,322 B — ditto), www homepage HTTP 403 pre-cookie (same as plain clients everywhere).
Reading: the archive hosts tolerate at least one major cloud provider when the client sends
browser headers — ADR-009's fallback path (cloud catch-up ingestion if the home box dies) is
empirically alive for bhavcopy/archives; www's API hostility is client-shape-based, not
IP-based. CI still never touches exchange endpoints — that remains policy, not capability.
