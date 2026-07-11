# Documentation Package — Index & Standards
**Project:** Personal Quantitative Investment Research Platform (Indian Equities) · **Package version:** 2.0 · **Date:** 2026-07-07

## Executive summary
Complete pre-implementation documentation for a production-grade, single-operator quantitative
research and portfolio-management platform for NSE equities. Version 2 architecture: batch,
EOD-only, one portfolio engine with two drivers (backtest replay / live), reproducibility by
deterministic rebuild, free official data sources only, human-gated execution.

## Document map
| # | Document | Answers |
|---|---|---|
| 01 | Product Vision | Why this exists; what success means |
| 02 | Market & Research | What exists; what works; what to avoid |
| 03 | Product Strategy | Positioning, build-vs-buy, phased evolution |
| 04 | PRD | What we build; for whom; how we verify it |
| 05 | High-Level Architecture | V2 system design and V1→V2 changes |
| 06 | Low-Level Design | Per-subsystem responsibilities, interfaces, failure modes |
| 07 | Architecture Decision Records | Every major decision, incl. superseded ones |
| 08 | Data Architecture | Layers, versioning-by-rebuild, validation, lineage |
| 09 | Data Source Evaluation | Source-by-source verdicts and the chosen architecture |
| 10 | Database Design | Tables, DDL, partitioning, storage strategy |
| 11 | Quantitative Research Framework | Factors, construction, risk, validation |
| 12 | Backtesting Specification | Costs, taxes, slippage, execution, stress tests |
| 13 | Feature Specifications | Major features with acceptance criteria |
| 14 | API & Module Contracts | CLI tools, ports, data contracts |
| 15 | Infrastructure & Deployment | Dev env, CI, monitoring, secrets, backup, DR |
| 16 | Testing Strategy | Unit, property, golden, integration, acceptance |
| 17 | Operations | Runbooks, incident response, maintenance |
| 18 | Roadmap | Phases 0–4 with exit criteria and effort |
| 19 | Final Self-Review | Remaining weaknesses and simplification opportunities |

## Documentation standards used here
Each document opens with a compact front-matter block (Summary / Purpose / Scope /
Assumptions / Risks / Open questions / Future extensions — one line each where one line
suffices). Documents are deliberately dense: for a single-operator project, documentation
that will not be maintained is technical debt, so every page must earn its upkeep. ADRs
(doc 07) are the only append-only documents; all others are living and versioned in git
alongside code.

## Terminology (used consistently across the package)
**Book** — an independent strategy sleeve with its own capital, config, and ledger.
**Raw** — immutable as-downloaded source files. **Curated** — deterministically derived,
analysis-ready tables. **PIT** — point-in-time: only information available on date D is
visible to logic running "as of" D. **MDTV** — 60-day median daily traded value.
**Champion / challenger** — the deployed strategy config vs. a candidate replacing it.
**Incubation** — paper-only live running of a challenger. **Proposal** — an explained,
human-approvable set of orders. **Run manifest** — the recorded recipe (code hash, config
hash, data watermarks) that makes a run reproducible. **Operator** — the human owner.
