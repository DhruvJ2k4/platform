# 17 · Operations
**Summary:** Runbooks and incident discipline sized for one operator. **Purpose:** make 3am-you and 3-years-later-you effective. Severity: SEV1 = wrong data could reach a proposal, or system dead; SEV2 = degraded/stale but safe; SEV3 = cosmetic.

**Steady state (the ≤2 hr/wk):** weekly — read DQ report + status page (10 min), review
any Tier-1/2 events (10 min); quarterly — proposal review (60–90 min), rate re-verify on
budget day, restore/fault drills per schedule. Daily: nothing (by design).

**RB-1 Dead-man alert fired (box silent):** check power/ISP → SSH LAN → if dead: restore
runbook on spare hardware (doc 15); if alive: read last structured log, `platform ingest
<src> --since <gap>` to heal; verify status page green.
**RB-2 Feed broken (parse failures / absence alarm):** raw is still being hoarded → no
data loss; snapshot the failing file into fixtures; fix/extend parser (new epoch);
re-curate; add fixture test. Announcements feed: check 7-day lookback covered the gap.
**RB-3 Bad data suspected downstream:** freeze proposals (`status: hold` flag); identify
offending raw watermark from manifests; correct parser/CA entry; `curate --rebuild`;
compare champion regression pin; unfreeze. Never hand-edit curated (it will be rebuilt away).
**RB-4 Demerger queue item:** gather scheme ratio from exchange circular; enter resolved
CA row (source_ref = circular); rebuild affected ISIN; verify against Screener price
chart visually; log.
**RB-5 Broker reconciliation mismatch:** proposals blocked automatically; import fresh
holdings CSV; diff vs. ledger; usual causes: unrecorded fill, CA on holding (check queue),
manual trade outside system (enter with reason code).
**RB-6 Decay flag fired:** do NOT retune; open champion review per doc 11 — challenger
process or planned wind-down to defensive posture. Discipline is the runbook.
**RB-7 Restore drill (2×/yr) & fault drills (phase exits):** scripted in repo; results
logged to runs/drills/.
**Incident notes:** every SEV1 gets a 10-line blameless post-mortem in ops/journal.md —
the operator's institutional memory.
