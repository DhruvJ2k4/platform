# 07 · Architecture Decision Records
**Summary:** Append-only record of every major decision, including superseded ones. **Purpose:** preserve rationale; prevent re-litigating settled questions without new evidence. **Format:** Problem → Alternatives → Decision → Trade-offs accepted → Future implications. Statuses: ACCEPTED / SUPERSEDED-BY.

**ADR-000 Constraints charter — ACCEPTED.** Problem: scope discipline. Decision: cost ≤ ₹1,000/mo; maintenance ≤ 2 hrs/wk; EOD-only; human gate architectural; every ML component must beat a rules baseline; CUT list (social sentiment, option flow, news NLP, online learning/RL) binding. Implication: all other ADRs inherit these tests.

**ADR-001 System of record = official exchange archives (bhavcopy + CA + filings) — ACCEPTED.** Alternatives: broker candles (survivorship-biased), paid vendors (cost-ceiling breach: 0.3–0.8%/yr drag), yfinance (unreliable). Trade-off accepted: we own parser maintenance across format epochs. Implication: raw hoarding forever; parsers are format-epoch-versioned.

**ADR-002 PIT fundamentals: forward XBRL collection + lag-stamped historical bridge + snapshot-site validation oracle — ACCEPTED.** Alternatives: any single provider (all fail PIT or cost). Implication: fundamental factors gated ≥ 8 quarters native PIT; bridged rows flagged and stress-tested (+30d lag stretch).

**ADR-003 Storage: Parquet canonical + DuckDB as (stateless) query/build engine — ACCEPTED.** Alternatives: Postgres/Timescale (ops burden), SQLite (poor columnar). Implication: zero database operations; scale ceiling ~100× current needs.

**ADR-004 Orchestration: cron + idempotent, date-parameterized CLI jobs — ACCEPTED.** Alternatives: Airflow/Prefect/Dagster (services without justification at 5-step daily DAG). Revisit trigger: DAG genuinely exceeds ~15 interdependent steps.

**ADR-005 Backtesting: custom small engine + vectorbt as cross-validation oracle — ACCEPTED.** Alternatives: zipline (dead once already), backtrader (maintenance mode), Lean (overkill). Rationale: Indian cost/tax/PIT/delisting fidelity *is* the complexity; frameworks supply everything except it. Trade-off: we own bugs → doc 16's golden/property/oracle program. **Amended by ADR-016:** the "engine" is the shared portfolio engine; backtesting is a driver.

**ADR-006 Universe: NSE-only, EQ series; BSE-ready via ISIN-keyed master + adapter slot — ACCEPTED.** Alternatives: NSE+BSE now (≈1.8× ingestion surface for <5% investable additions concentrated in fraud/illiquidity territory). Amendment (V2): BE/BZ/SME series structurally excluded, not merely liquidity-filtered.

**ADR-007 Liquidity/capacity: participation-based investability (position ≤ p_max·MDTV), tiered base-slippage + √participation impact, turnover governance via buffers — ACCEPTED.** Alternatives: static "top-N by mcap" universes (ignores order size; not corpus-portable). Implication: identical model in both drivers; recalibrated from real fills (ADR-017).

**ADR-008 Historical index constituents never used in logic — ACCEPTED.** Problem: membership files are current-state (look-ahead). Decision: universes from own PIT ranks; official indices consumed only as TRI return series. Implication: benchmark ingest adapter for TRI values.

**ADR-009 Deployment: home mini-PC on residential IP + external dead-man switch + encrypted cloud backup — ACCEPTED.** Alternatives: VPS/GitHub Actions ingestion (datacenter-IP hostility; validated as P0 spike), laptop (not always-on). Trade-off: home power/ISP risk, healed by idempotent catch-up + retro-downloadable feeds.

**ADR-010 Stack: Python 3.12+/uv/pandas-at-edges/DuckDB-for-transforms/pydantic-configs/Typer/pytest+hypothesis/ruff/structlog/Jinja2-static-HTML — ACCEPTED.** Banned absent new ADR: Airflow, Spark, Kafka, K8s, microservices, feature-store products, vector DBs, LLMs in the decision path.

**ADR-011 BrokerPort: manual-first thin port; Kite → others as adapters — ACCEPTED.** Implication: fills loop back into slippage calibration; Kite daily-token friction documented, defers automation.

**ADR-012 Strategy books; swing gated by pre-registered admission (core live ≥ 4 quarters; swing go/no-go with full friction + T+1 latency; ≤ 20% capital; −15% kill switch) — ACCEPTED.** Alternatives: unified multi-horizon process (contamination), refusal (paternalistic). Implication: `book_id` first-class everywhere.

**ADR-013 Curated snapshot versioning — SUPERSEDED-BY ADR-016.**

**ADR-014 Dynamic N + minimum viable corpus (N∈[12,30]; pos ≥ max(₹25k, flat-fees/10bps); < ₹3L → index-core degraded mode; < ₹1L → refuse direct equity) — ACCEPTED.**

**ADR-015 Agent-ready, not agent-driven: typed CLI tools + logged decisions now; agent admission ladder (narration → research assistant → decision support → authority via champion/challenger only) — ACCEPTED.** Decision cadence remains EOD; live quotes are an execution detail.

**ADR-016 One portfolio engine, two drivers; reproducibility by rebuild — ACCEPTED (V2 keystone).** Problem: sibling backtester/engine invites research-live skew; snapshot hoarding conflated reproducibility with storage. Decision: pure `decide()` shared by replay and live drivers; curated is disposable/rebuildable from immutable raw + git; only champion runs pin materializations; run manifests record (code hash, config hash, raw watermarks). Trade-offs: rebuild time on old runs (minutes — acceptable); engine purity discipline required (lint-enforced). Future implication: any new decision logic lands once, is backtested and shipped as the same object.

**ADR-017 Reconciliation loop: contract notes parsed, modeled-vs-actual > 5bps investigated, slippage params recalibrated after ≥30 fills — ACCEPTED (V2 addition).**

**ADR-018 Incubation: challengers run paper-only ≥ 1 quarter post-gauntlet before capital — ACCEPTED (V2 addition).** Rationale: the missing rung between backtest and money; costs one quarter of patience, buys a live out-of-sample sample.

**ADR-019 Index-reconstruction acceptance amended to a two-part test — ACCEPTED (implementation planning finding).** Problem: the frozen ≥0.999 correlation criterion silently required historical constituent weights, which ADR-008 correctly bans as look-ahead. Decision: Part A — 50 largest corporate-action events spot-checked vs. independent source, |diff| > 25 bps fails; Part B — equal-weight proxy of current Nifty50 constituents, 5y daily-return correlation vs official TRI ≥ 0.995 with zero unexplained >5% single-day divergences. Trade-off: slightly weaker breadth statistic, honest method. Affected docs updated: 13 (F2), 18 (P0 exit), 21 (§14). Lesson: acceptance criteria get a "is this measurable without banned data?" check at freeze time.

**ADR-020 Import package is `quant`; the name `platform` stays for repo, CLI, and distribution — ACCEPTED (P0-01 finding).** Problem: doc 20's skeleton named the import package `platform`, which Python's stdlib shadows — the stdlib directory precedes site-packages on sys.path, and pytest preloads stdlib `platform` into sys.modules, so `platform.engine`/`platform.cli` could never be imported (verified empirically before any code existed). Alternatives: sys.path front-insertion hacks (fragile; break stdlib consumers inside test runners), renaming repo/CLI/product too (needless churn). Decision: import package `src/quant/`; repo directory, `platform` CLI command, and distribution name unchanged; doc 20 skeleton and CLAUDE.md paths updated in the same pass. Trade-off accepted: import name differs from the product word. Implication: candidate top-level module names get a stdlib-collision check at design time (`python -c "import <name>; print(<name>.__file__)"`).
