# 14 · API & Module Contracts
**Summary:** CLI tools are the API; table schemas are the data contracts; two Python ports. **Purpose:** integration surface for humans, tests, and future agents (ADR-015).

## CLI (Typer; every command idempotent, JSON-output capable, exit-code disciplined)
```
platform ingest <source> --date|--since        platform curate --incremental|--rebuild
platform universe --date [--book]              platform features <id> --date
platform backtest <strategy.yaml> --from --to  platform evaluate <run_id>
platform propose <book> [--override-staleness] platform explain <proposal_id|order_id>
platform ledger <book> [--reconcile <notes>]   platform events --since [--severity]
platform status                                platform reproduce <run_id>
platform backup --run|--verify                 platform restore --drill
```

## Python ports (Protocols)
`BrokerPort`: get_holdings / get_cash / submit_orders / get_fills (ADR-011; Manual→Kite).
`DecisionEngine`: `decide(state, market_view, book_config) -> Decision` — pure; drivers
inject data and clock (ADR-016). No other cross-module Python API is public: modules
communicate through curated/operational tables (doc 10) and run artifacts.

## Data contracts
Authoritative schemas live in `schemas/` (pandera + SQL DDL, versioned with code);
doc 10 mirrors them. Contract-change policy: additive by default; breaking changes need
an ADR + rebuild. `Decision.reasons` schema: `[{rule_id, params, evidence_refs[]}]` —
the explainability contract every UI/report/agent consumes.
