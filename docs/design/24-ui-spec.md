# 24 · UI & Interaction Specification
**Purpose:** exact spec of every surface the operator sees and the approval interaction. **Philosophy:** reports ARE the UI; zero servers by default (a server is a pager duty). Static, printable, self-contained HTML (inline CSS+plotly), dark-on-light, generated per run and archived — the UI has version history for free.

## Surface inventory
1. **Proposal report** (the flagship, quarterly + event-advanced) — layout top-to-bottom:
   - **Freshness banner** (green/amber/red; max ingest date per feed; red blocks per doc 06).
   - **Summary strip:** book, asof, NAV, cash, drawdown vs budget + governor state,
     turnover this proposal, est. costs ₹, est. tax ₹.
   - **Action table:** per order — side, name, qty, est. price band, participation %,
     **reason chain rendered as plain English pills** (from reasons JSON: e.g., "entered:
     rank 7 ≤ 20" · "exit: ASM stage 2"), cost+tax line, lot ages affected.
   - **Holdings table:** current vs target weight bars, drift flags, rank history sparkline.
   - **Evidence appendix:** per name — factor scores, liquidity stats, recent Tier-1/2
     events with filing links (agent evidence packs when enabled).
   - **Dissent memo** (agent or template): the case against, displayed BEFORE the
     approval block — the UI enforces reading order.
   - **Approval block:** checklist (reconciled? freshness green? dissent read?) + the
     exact CLI line to run: `platform approve <id> [--veto ISIN --reason CODE]…` +
     orders CSV download.
2. **Status page** (nightly): traffic-light per feed (last success, rows, next
   expected), job duration sparklines, DQ summary, backup age, agent-validator failure
   rate, pending demerger queue count.
3. **Decay dashboard** (monthly): live vs backtest rolling-Sharpe band chart (§15),
   modeled-vs-actual cost gap, hit-rate trend, per-book NAV vs benchmarks (TRI, net).
4. **Quarterly review** (post-execution): fills vs model, reconciliation result,
   turnover/tax ledger, what the buffer saved (trades avoided × est. cost).
5. **Override-alpha annual:** actual vs pure-system counterfactual, decomposed by
   override reason code; one honest headline number.
6. **Run/backtest report:** equity curve vs benchmarks, drawdown, stress table,
   gauntlet pass/fail grid, variant-budget state, manifest block.

## Interaction design (v1: CLI + files; a deliberate decision)
Approve/veto happens via one copy-pasted CLI line from the report; reason codes are a
fixed enum (`conviction, liquidity_doubt, external_info, tax_personal, other:<text>`) so
override-alpha can decompose. **Mini-DR (UI-1):** a localhost approval web-app was
considered (FastAPI, buttons) and REJECTED for v1 — it adds a served process, auth
questions, and maintenance for saving ~30 seconds/quarter. Revisit trigger: operator
skips or delays ≥2 consecutive quarterly reviews and cites friction — then build the
smallest possible localhost app (single file, no framework beyond stdlib/FastAPI).

## Information design rules
Every number that drove a decision is visible within one click/scroll of the decision it
drove (no "trust me" surfaces). Color encodes state only (green/amber/red), never
decoration. Tables sort by actionability, not alphabet. Every report footer: run_id,
config hash, code tag — the reproducibility handle. Mobile: readable via the synced
folder (reports are responsive-width HTML); no app.

## Accessibility & quality bar
Semantic HTML, real tables, ≥4.5:1 contrast, no color-only meaning (icons+text), prints
to A4 sanely (the quarterly ritual may be on paper — respect it).
