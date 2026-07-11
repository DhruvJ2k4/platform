# 04 · Product Requirements Document
**Summary:** Full-system PRD for the V2 platform. **Purpose:** define what is built and how success is verified. **Scope:** all phases; Phase 0 requirements are FROZEN. **Assumptions:** V2 architecture (doc 05); constraints from ADR-000. **Risks:** requirement creep — additions require a removal or a written ADR. **Open questions:** §9. **Future extensions:** §10.

## 1. Goals
G1 Own a survivorship-bias-free, PIT-correct NSE dataset maintainable in ≤2 hrs/wk.
G2 Evaluate strategies with full Indian cost/tax realism and pre-registered discipline.
G3 Produce explained, human-approvable proposals per book on schedule and on events.
G4 Track live vs. expected performance, human overrides, and strategy decay continuously.
G5 Operate at ≤ ₹1,000/mo recurring, self-monitoring, restorable in ≤ 4h.

## 2. Non-goals
Intraday decisioning · social/news sentiment · options/derivatives · multi-user or
advisory features · autonomous (non-gated) execution · ML in the decision path for v1 ·
BSE (adapter slot reserved) · mobile/web app (static HTML reports suffice).

## 3. Personas
**P1 The Operator** (primary): technical investor; wants evidence-gated decisions and
minimal upkeep. **P2 The Future Maintainer** (the operator in 3 years, or an agent):
needs contracts, ADRs, and runbooks — served by this package. **P3 The Auditor**
(the operator's skeptical self): needs every number reproducible from raw + git.

## 4. User stories (priority order; acceptance criteria in doc 13)
- As the Operator, I run one command on a fresh machine and reach a validated, fully
  backfilled data store unattended.
- As the Operator, I receive a quarterly proposal per book listing exact orders, the rule
  that fired for each, factor evidence, liquidity check, and cost+tax estimate — and I
  approve, modify (reason-coded), or veto.
- As the Operator, I can ask what the investable universe and factor ranks were on any
  historical date and trust the answer is PIT-correct.
- As the Operator, I am alerted within 24h if any feed or the box itself dies, and within
  one report cycle if live performance decays below the backtest's plausible band.
- As the Auditor, I can re-execute any historical run bit-for-bit from its manifest.
- As the Operator, I see annually whether my overrides added or destroyed value.

## 5. Functional requirements (system level; per-phase detail in doc 18)
FR1 Ingestion of: NSE bhavcopy (current+archive epochs), corporate actions, financial-
results filings + announcements (PIT), ASM/GSM surveillance lists, index TRI series,
trading holidays (derived). FR2 Curation: ISIN-keyed security master with effective-dated
tickers and series; adjusted prices; PIT universe; events. FR3 Feature library: momentum,
volatility (EWMA default), liquidity stats, size; extensible per doc 11. FR4 One portfolio
engine (doc 05 §3) with backtest and live drivers; books as first-class. FR5 Evaluation
harness enforcing pre-registration, variant budget, walk-forward, holdout, stress suite.
FR6 Proposal reports (static HTML) with freshness banners and explanation blocks.
FR7 Ledger: FIFO tax lots, costs, dividends, delistings; contract-note reconciler.
FR8 Ops: dead-man's switch, data-quality suite, cloud backup, restore procedure.

## 6. Non-functional requirements
Reproducibility: any run re-executable from manifest (raw immutable + git). Reliability:
gap self-healing for retro-downloadable feeds; 7-day lookback for lossy feeds. Performance:
daily pipeline p95 < 15 min; full 15y backtest of one config < 5 min on the reference box.
Cost: ≤ ₹1,000/mo. Security: no inbound ports; secrets in keyring; encrypted backups.
Maintainability: no component may require > 30 min/wk attention in steady state.
Explainability: every proposed order carries a machine-readable reason chain.

## 7. KPIs & success criteria
The five metrics in doc 01 §Success metrics, measured quarterly; Phase exit criteria in
doc 18 are the milestone-level success criteria and are frozen.

## 8. Dependencies & risks
Depends on: continued free availability of exchange archives (mitigation: raw hoarding —
we keep everything ever downloaded); Zerodha console exports (mitigation: BrokerPort
manual CSV is broker-agnostic). Top risks with mitigations: R1 corporate-action errors
(golden/property tests, index reconstruction, demerger review queue) · R2 overfitting
(variant budget, holdout, incubation) · R3 operator abandonment (degraded-safe mode,
≤2hr/wk rule) · R4 source hostility to automation (residential IP, polite pacing, raw
retention) · R5 solo bus factor (this package + runbooks are the mitigation).

## 9. Open questions
Q1 free-float share source until fundamentals mature (traded-value proxy interim).
Q2 exact archive epoch boundaries (discovered in P0 backfill). Q3 datacenter-IP tolerance
(P0 week-1 spike; affects fallback only).

## 10. Future considerations (P2+ architectural insurance)
BSE adapter · polars swap behind the store · Kite execution adapter · fundamental factor
family · swing book (gated, ADR-012) · agent narration rung (ADR-015).
