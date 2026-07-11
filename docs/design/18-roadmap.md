# 18 · Roadmap
**Summary:** Five phases; each exits on drilled criteria, not vibes. Effort assumes 5–15 hrs/wk.

| Phase | Deliverables | Depends on | Key risks | Exit criteria (frozen) | Effort |
|---|---|---|---|---|---|
| **0 Data foundation** | F1–F3 + calendar + security master + DQ gate + dead-man + backup + fixtures; week-1 spikes (IP tolerance, archive epoch map, announcement archive depth); F4 collector started | — | CA correctness; epoch surprises | Two-part data validation passes (ADR-019: CA spot-checks + EW-proxy ≥0.995); 3 fault drills pass; unattended fresh-machine backfill; ≤2hr/wk over 4 weeks | 60–100h / 6–10 wk |
| **1 Research engine** | Shared engine + BacktestDriver + evaluation harness + F5; **Milestone 1 go/no-go** (pre-registered, ≤6 variants, holdout single-look) | P0 | Overfitting; engine bugs | Golden+property+oracle green; Milestone 1 verdict documented either way; if NO-GO → pivot per doc 01 metric 4 | 80–120h |
| **2 Live operation** | LiveDriver + F6 proposals + F7 ledger/reconciler + ManualBroker + incubation of champion (1 quarter paper) then capital | P1 GO | Human-loop friction; reconciliation gaps | First 2 live proposals executed & reconciled ≤5bps unexplained; freshness/reconciliation gates proven by injected staleness | 60–90h |
| **3 Monitoring & events** | F8: decay dashboard, override-alpha, event severity rules + evidence packs, status page hardening | P2 | Alert fatigue | 4 consecutive weeks ≤2hr/wk incl. one drill; decay flag validated on synthetic series | 40–60h |
| **4 Earned extensions** | Each behind its own ADR + gate: fundamental factors (ADR-002 maturity), vol-scaled momentum challenger, HRP challenger, Kite execution, swing book gate (ADR-012), agent narration rung (ADR-015), BSE adapter | P3 + gate conditions | Scope creep | Per-extension ADR with maintenance budget; champion/challenger for anything touching decisions | ongoing |
