# 03 · Product Strategy
**Summary:** Personal platform, not a product; compounding moat is owned PIT data; evolution gated by evidence. **Purpose:** decide where effort goes and what we refuse to build. **Scope:** 3-year horizon. **Assumptions:** no commercialization (avoids SEBI advisory-registration questions entirely). **Risks:** scope creep via "platform envy." **Open questions:** none blocking. **Future extensions:** multi-user family mode (explicit non-goal for now).

## Positioning
An internal tool for one investor. No users to acquire, no compliance surface of advice
distribution, no uptime SLA beyond the operator's own needs. This is a strategic advantage:
every feature that exists only to impress others is cut by default.

## Build vs. buy (final)
| Capability | Verdict | Rationale |
|---|---|---|
| EOD price/CA data | **Build** (ingest free official) | Only route to bias-free data under cost ceiling; vendor = drag + lock-in |
| PIT fundamentals | **Build forward, bridge history** | Not purchasable at retail cost; value compounds with time (start early) |
| Backtester | **Build small + oracle cross-check** | The Indian cost/tax/PIT specifics *are* the product; frameworks provide everything except them |
| Execution | **Buy** (broker apps → Kite API later) | Zero edge in building execution |
| Monitoring plumbing | **Buy free tier** (healthchecks.io, Telegram) | Commodity |
| Visualization | **Build thin** (static HTML) | Dashboards-as-a-service is maintenance without alpha |

## Phased evolution (detail in doc 18)
P0 data foundation → P1 research engine + Milestone 1 go/no-go → P2 live proposals +
reconciliation → P3 monitoring/events/decay → P4 earned extensions (fundamental factors,
swing book gate, Kite execution, agent narration rung).

## Long-term vision alignment
The agent-system vision (ADR-015) is served *now* by CLI-tool discipline and decision
logging, and *later* by an admission ladder in which agents earn authority through the
same champion/challenger gate as any model. The moat that compounds meanwhile is data:
every quarter of collected PIT filings is an asset no competitor of the operator's future
self can backfill.
