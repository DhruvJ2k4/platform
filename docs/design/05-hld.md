# 05 · High-Level Architecture (V2)
**Summary:** Batch, EOD, four effective layers, one portfolio engine with two drivers, reproducibility by rebuild. **Purpose:** the authoritative system picture. **Scope:** logical + deployment views. **Assumptions:** single operator, home runner (ADR-009). **Risks:** §6. **Open questions:** none blocking. **Future extensions:** adapter slots noted inline.

## 1. V1 → V2 changes (what this revision changed and why)
| # | Change | Why it is superior |
|---|---|---|
| 1 | **One portfolio engine, two drivers** (backtest replay / live step) replaces sibling backtester+engine | Research/live skew becomes impossible by construction — the classic quant-shop bug class is eliminated, not policed |
| 2 | **Feature store → feature library + cache** | Features are pure functions over curated data; DuckDB computes them in sub-seconds; a versioned storage tier bought nothing but upkeep |
| 3 | **Snapshot versioning → reproducibility by rebuild** | Curated = f(raw, code, config), all immutable/git-versioned; store the recipe, not copies; champion runs alone pin materializations |
| 4 | **Event monitor → events table + severity rules + report section** | A "subsystem" for a daily diff-and-flag was structure without substance |
| 5 | **Validation rationalized** to the ingest→curated boundary + global invariant suite | Contract checks where corruption enters; ceremony removed elsewhere |
| + | Added: incubation stage; demerger review queue; contract-note reconciler; series-aware universe (EQ only; BE/BZ/SME excluded structurally) | Each covers a real, previously silent failure mode |

## 2. Logical architecture
```
 official free sources (NSE portals, index TRI, surveillance lists)
        │  polite adapters · residential IP · idempotent · date-parameterized
        ▼
 RAW  — immutable as-downloaded files (hoarded forever, encrypted cloud backup)
        │  deterministic curation build  (code+config in git ⇒ rebuildable)
        ▼
 CURATED — DuckDB/Parquet: security_master · listings · trading_calendar ·
           prices_adj · corporate_actions · pit_universe · fundamentals_pit ·
           events · index_tri            [validation gate + invariant suite HERE]
        │
        ▼
 FEATURE LIBRARY — pure functions (momentum, EWMA vol, MDTV, size…); cached, not stored
        │
        ▼
 PORTFOLIO ENGINE (single implementation; pure: (state, asof, book_config) → decision)
   ├── BacktestDriver: replay over history → Evaluation Harness (pre-reg, budget,
   │       walk-forward, holdout, stress) → champion/challenger → INCUBATION (paper)
   └── LiveDriver: single step today → PROPOSAL → Report Renderer (HTML, freshness
           banner, reason chains) → HUMAN gate (approve/modify/veto, reason-coded)
                                        → BrokerPort (Manual CSV → Kite later)
                                        → Fills → Ledger (FIFO lots) → Reconciler
 MONITORING (cross-cutting): dead-man switch · data-quality report · decay dashboard ·
 override-alpha report · status page
```
Dependency rule: downward arrows only; table contracts (doc 10) are the interfaces.

## 3. The engine contract (the load-bearing abstraction)
`decide(portfolio_state, market_view_asof(D), book_config) -> Decision{targets, orders,
reasons}` — pure, deterministic, no I/O, no clock access. Drivers own I/O and time. All
cost/tax/liquidity logic lives in engine-called libraries shared identically by both
drivers. This single contract is what makes backtests honest and proposals testable.

## 4. Integration points
Inbound: exchange portals (scrape/download), niftyindices TRI, broker back-office CSV,
contract notes. Outbound: Telegram alerts, healthchecks.io pings, rclone-encrypted backup
bucket, reports directory (synced, never served).

## 5. Deployment view
One home mini-PC (Ubuntu LTS, UPS advisable) running cron; dev on workstation; GitHub for
code + CI (tests/lint only — CI never touches exchange endpoints); cloud object storage
for encrypted backups; no inbound network exposure. Full detail in doc 15.

## 6. Architectural risks
Engine purity erosion (mitigation: no-I/O lint rule + driver-only clock injection) ·
curation build nondeterminism (mitigation: pinned deps via lockfile; property test:
rebuild twice, byte-compare) · home-box SPOF (mitigation: external dead-man detection +
documented ≤4h restore; accepted for a personal system).
