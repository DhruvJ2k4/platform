# 15 · Infrastructure & Deployment
**Summary:** One home box, cron, GitHub CI for code only, encrypted cloud backup, no inbound network. **Purpose:** ops-ready environment spec. **Assumptions:** ADR-009. **Risks:** home power/ISP (accepted, healed). **Open questions:** none — the P0 IP-tolerance spike (fallback path only) is resolved in doc 09's P0-05 findings.

**Dev environment:** workstation; `uv sync` from lockfile; `platform curate --rebuild`
against a raw subset fixture; pre-commit = ruff + pytest-fast.
**CI (GitHub Actions):** lint, type-check, unit+property tests, golden scenarios, docs
link check. CI never contacts exchange endpoints (datacenter IP + politeness); a small
committed raw fixture set powers integration tests.
**Production:** Ubuntu LTS mini-PC; deploy = `git pull && uv sync && smoke test` tagged
release; rollback = checkout previous tag (data is rebuildable; operational tables are
append-only and unaffected). Cron: ingest+curate nightly (post-market), weekly DQ report,
quarterly proposal per book schedule, nightly backup.
**Monitoring:** healthchecks.io dead-man ping (pipeline end) + Telegram sev-1; weekly
digest; status HTML regenerated nightly.
**Secrets:** OS keyring / root-owned env file; only secrets in v1: Telegram token, backup
bucket write-scoped key. Broker credentials do not exist in v1.
**Backup:** nightly rclone **crypt** (reports/ledger contain personal financial data) of
raw/ + operational DuckDB + configs + runs/manifests to object storage (B2/R2 class,
≈$0–1/mo). 3-2-1 achieved with a second local disk copy.
**Recovery/DR:** documented restore: new box → OS → clone repo → uv sync → rclone restore
→ `curate --rebuild` → smoke. Target ≤ 4h; drilled twice yearly (doc 17 runbook).
**Supply chain:** lockfile-pinned deps; `uv` audit on update days only (scheduled
monthly); no auto-updates on the production box.
