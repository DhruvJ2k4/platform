# 20 · Implementation Plan (Granular WBS, Workflows, Iteration Protocol)
**Purpose:** the build-order bible — every task with definition-of-done (DoD) and effort. **Scope:** P0–P3 granular; P4 outline. **How to consume:** work top-to-bottom inside a phase; never start a task whose dependencies aren't DoD-green. **Assumption:** solo dev, 5–15 hrs/wk. **Cross-refs:** algorithms → doc 21, agents → doc 22, standards → doc 23, UI → doc 24.

## Repository skeleton (create in P0-01, exactly this)
```
platform/
├── pyproject.toml  uv.lock  .github/workflows/ci.yml
├── config/          # books/*.yaml costs.yaml tax.yaml liquidity.yaml sources.yaml
├── schemas/         # SQL DDL (authoritative); pandera models: src/quant/schemas/ (ADR-021)
├── src/quant/
│   ├── ingest/      # one adapter per source (bhavcopy, ca, filings, surveillance, tri)
│   ├── curate/      # parsers/ (per format epoch), adjuster, master, universe, events
│   ├── features/    # registry.py + one module per factor family
│   ├── engine/      # decide.py (PURE), selection, weights, governor, tax_overlay
│   ├── drivers/     # backtest.py, live.py
│   ├── ledger/      # lots.py, costs.py, taxes.py, reconcile.py
│   ├── evaluation/  # harness, walkforward, stress, decay, override_alpha
│   ├── reports/     # renderers (Jinja2) + templates/
│   ├── agents/      # P4: runtime, roster, tools, guards (doc 22)
│   ├── ops/         # deadman, backup, drills, status
│   └── cli.py       # Typer app = the API (doc 14)
├── tests/           # unit/ property/ golden/ integration/ fixtures/
└── ops/             # runbooks (doc 17), journal.md, drills/
```

## Phase 0 — Data foundation (≈ 95–115 h)
| ID | Task (goal) | DoD | Est |
|---|---|---|---|
| P0-01 | Repo+uv+ruff+mypy+pytest+CI skeleton | CI green on placeholder test; import-linter enforces layer rule | 3h |
| P0-02 | `schemas/`: DDL + pandera for all doc-10 tables | Contracts importable; round-trip test on empty tables | 6h |
| P0-03 | Config system (pydantic-settings; effective-dated rates) | Rate lookup by date unit-tested; bad config fails loudly | 4h |
| P0-04 | Raw store: atomic writes, sha256, `raw_registry` | Idempotent re-ingest is a no-op (test) | 4h |
| P0-05 | **Week-1 spikes:** datacenter-IP tolerance; archive-epoch survey; announcements archive depth | Findings written into doc 09 + parser plan | 6h |
| P0-06 | NSE bhavcopy adapter — current format | 30 recent days ingested; holiday 404 handled via calendar | 5h |
| P0-07 | Archive-epoch parsers (per P0-05 findings) | Fixture file per epoch parses; row counts sane | 8–14h |
| P0-08 | Trading calendar from bhavcopy presence | Muhurat + holidays correct for 3 sample years | 2h |
| P0-09 | Security master + effective-dated listing resolver (symbol changes file) | Known rename resolves correctly across boundary (test) | 8h |
| P0-10 | Corporate-actions ingester | 5y CA table populated; kinds classified; demergers → `needs_review` | 6h |
| P0-11 | **CA adjuster** (algorithm 21§1) + golden + property tests + **atomic publish of curated tables** (doc 06 §6.2; persists the validated frames returned by P0-08/09/10) | Golden to the paisa; invariance property green; demerger blocks; calendar/master/CA/prices published atomically | 14h |
| P0-12 | Dividend cash table (shipped as a derived surface over corporate_actions + operator cash resolutions — ADR-025; table promotion stays an open option) | Ex-date credits match CA source for sample | 2h |
| P0-13 | Liquidity stats + PIT universe builder (21§3–4) | `universe --date` <1s with exclusion reasons; monotonicity green | 8h |
| P0-14 | ASM/GSM surveillance ingester + hard-exclusion wiring | List-add flips investability next build (test) | 3h |
| P0-15 | Index TRI ingester (benchmarks) | Nifty50+Midcap150 TRI series loaded, gap-checked | 3h |
| P0-16 | DQ suite: gate + invariants + volumetrics | Injected bad file blocks publish + alerts | 6h |
| P0-17 | Dead-man switch + Telegram + status page v0 | Killed cron detected externally <24h (drill) | 4h |
| P0-18 | Backup (rclone crypt) + restore script | Restore drill on clean VM ≤4h, documented | 5h |
| P0-19 | 15y backfill run + **amended validation** (21§14) | Two-part validation passes; report archived | 8h |
| P0-20 | Fault drills ×3 (dead cron, corrupt file, missed week) | Each detected+healed as designed; logged | 3h |
| P0-21 | Filings/announcements PIT collector v0 (collect-early) | Results-day filing lands with broadcast ts; absence-alarm tested | 10h |

## Phase 1 — Research engine + Milestone 1 (≈ 85–115 h)
| ID | Task | DoD | Est |
|---|---|---|---|
| P1-01 | Engine state types + pure `decide()` skeleton | Purity lint (no I/O/clock imports) enforced in CI | 6h |
| P1-02 | Cost calculator (21§9) | Matches hand-computed contract-note table to the rupee | 4h |
| P1-03 | FIFO lot ledger + tax engine (21§8) | Golden tax scenario exact; conservation property green | 12h |
| P1-04 | Slippage model (21§10) | Tier/participation table unit-tested; config-driven | 3h |
| P1-05 | Factor library: mom_12_1, EWMA vol, size proxy (21§5) | Values match independent notebook calc on 10 names | 6h |
| P1-06 | Selection+weights+bands+governor+tax overlay (21§6–7) | Each rule unit-tested; reasons JSON emitted per order | 12h |
| P1-07 | BacktestDriver replay loop (21§11) | Deterministic across runs; NAV continuity property green | 10h |
| P1-08 | vectorbt oracle cross-check (costless config) | Match within float tolerance | 5h |
| P1-09 | Evaluation harness: pre-reg registry, variant budget, walk-forward, holdout state, stress suite (21§12–13) | 7th variant refused; holdout single-look enforced by state file | 12h |
| P1-10 | Benchmark treatment (TRI net of TER + tax parity) | Benchmark series reproducible | 4h |
| P1-11 | **Milestone 1 runs** (≤6 pre-registered variants) + verdict report | Go/no-go documented either way; robustness gauntlet table | 10h |
| P1-12 | Backtest report renderer | One-page HTML per run from manifest | 5h |

## Phase 2 — Live operation (≈ 60–85 h)
LiveDriver+freshness gate (6h) · holdings CSV import+reconcile precondition (5h) ·
proposal renderer per doc 24 (10h) · `approve/veto` CLI with reason codes (4h) ·
Zerodha contract-note parser (8h) · reconciler + cost-gap report (8h) · incubation
ledger + quarter of paper (calendar time) · first live cycle end-to-end (6h) ·
slippage recalibration after ≥30 fills (4h). Exit: doc 18 P2 criteria.

## Phase 3 — Monitoring & events (≈ 40–60 h)
Decay dashboard (21§15) 8h · override-alpha (21§16) 8h · event severity rules + evidence
packs 8h · results-season absence alarms hardening 4h · status page v1 4h · ≤2hr/wk
4-week proof (calendar). **Phase 4 (outline):** agent flows per doc 22 (30–50h, gated on
stable reasons-JSON) · fundamental factors (ADR-002 gate) · Kite adapter · challengers.

## Operating workflows (what actually runs)
**Nightly (cron 19:30 IST):** ingest all sources → curate --incremental → DQ gate →
features cache warm (optional) → status page → backup → dead-man ping. Any gate failure
⇒ publish blocked, alert, yesterday's curated stays live.
**Weekly (operator, ≤20 min):** read DQ + status; skim Tier-1/2 events.
**Quarterly (operator, 60–90 min):** LiveDriver proposal → read report incl. dissent →
approve/modify/veto (reason-coded) → place orders manually → import contract notes →
reconcile. **Annually:** budget-day rate re-verify; override-alpha review; doc tripwire
pass. **Results season:** filings collector runs hot; expect +30 min/wk triage.

## Iteration & change protocol (how building feeds back into design)
Reality will contradict the docs. When it does: small surprise → fix + note in
ops/journal.md; contract/algorithm change → mini-ADR (5 lines) in doc 07 + propagate to
affected docs same day; frozen-decision collision → check its unfreezing condition; if
triggered, full DR supersession, else the code conforms to the freeze. Never let code
and docs disagree silently — that is the definition of rot here.
