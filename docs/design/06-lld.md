# 06 · Low-Level Design
**Summary:** Responsibilities, interfaces, workflow, and failure modes per subsystem. **Purpose:** implementation-ready component specs. **Scope:** all V2 components. **Assumptions:** contracts in docs 10/14. **Risks:** per-component below. **Open questions:** flagged inline. **Future extensions:** adapter slots.

## 6.1 Ingest adapters (one per source)
**Responsibility:** fetch source → write raw file + registry row. Nothing else.
**Interface:** `fetch(date) -> RawArtifact{path, sha256, source, logical_date}`; CLI
`ingest <source> --date|--since`. **Workflow:** politeness delay → download → checksum →
immutable write → registry upsert (idempotent by (source, logical_date)).
**Failure modes:** 404 on holiday (expected; calendar check) · format drift (parser is
NOT here — raw is stored regardless, parse failures surface in curation, data never lost)
· IP block (exponential backoff, alert after N days) · partial download (checksum reject).

## 6.2 Curation build
**Responsibility:** deterministic raw → curated transform; the only writer of curated.
**Interface:** `curate --rebuild|--incremental --asof <date>`. **Workflow:** parse (format-
epoch-versioned parsers) → security master resolution (ISIN; effective-dated symbol/series)
→ corporate-action adjustment (splits/bonuses automated; **demergers → review queue**,
curation of affected ISIN blocked until operator resolves) → PIT universe build → events
diff → validation gate (schema + invariants; hard fail = no publish) → atomic publish.
**Failure modes:** unparseable file (quarantine + alert; other sources proceed) ·
invariant breach (publish blocked — stale-but-consistent beats fresh-but-wrong) ·
demerger pending (affected name flagged uninvestable until resolved).

## 6.3 Feature library
**Responsibility:** pure feature functions over curated with strict as-of semantics.
**Interface:** `f(curated_view_asof(D), params) -> DataFrame[isin, value]`; registry maps
`feature_id -> (function, params, version)`. **Workflow:** compute on demand; content-
addressed cache keyed (feature_id, version, asof, curated_watermark). **Failure modes:**
silent look-ahead (mitigated: curated views physically filter `available_at <= D`;
property test shifts D and asserts no future rows reachable).

## 6.4 Portfolio engine
**Responsibility:** the decision function (doc 05 §3); selection with buffered membership,
capped inverse-vol weights, drift bands, drawdown governor, tax overlay (LTCG deferral,
exemption harvest), dynamic N (ADR-014), hard exclusions (surveillance, series, liquidity).
**Interface:** pure `decide(...) -> Decision`; every order carries `reasons: [rule_id,
evidence_ref…]`. **Failure modes:** infeasible constraints (deterministic relaxation
order: sector cap → name cap → N; each relaxation logged as a reason) · empty universe
(defensive posture: hold + cash) · engine exception (driver aborts run; no partial output).

## 6.5 Drivers
**BacktestDriver:** replay engine over trading calendar; applies execution model (doc 12);
maintains simulated ledger; emits run artifacts + manifest. **LiveDriver:** loads real
ledger + curated-asof-today; freshness check (refuse > 2 trading days stale unless
`--override`); emits Proposal. **Failure modes:** calendar mismatch (single shared
calendar table) · state divergence (live ledger reconciled to broker holdings before every
run; mismatch blocks proposal).

## 6.6 Evaluation harness
**Responsibility:** enforce doc 11 §Validation mechanically: registered-variant budget,
walk-forward, single-shot holdout (state file records the one look), stress suite,
deflated-Sharpe reporting, champion/challenger comparison, incubation ledger.
**Failure modes:** budget exhausted (refuses run; requires new ADR) · holdout re-access
attempt (hard refuse).

## 6.7 Ledger & reconciler
**Responsibility:** FIFO tax-lot ledger (buys, sells, dividends, delistings, charges);
parse broker contract notes; reconcile modeled vs. actual costs (>5bps gap ⇒ ticket);
feed realized slippage back to doc 12 model. **Failure modes:** contract-note format
drift (parser versioned; unparsed notes queue for manual entry — ledger correctness
over automation).

## 6.8 Report renderer
**Responsibility:** Jinja2 → static HTML: proposal, quarterly review, data-quality,
decay dashboard, override-alpha, status page. Freshness banner mandatory on all.
**Failure modes:** render on stale data (banner + proposal refusal path per 6.5).

## 6.9 BrokerPort
As ADR-011: `ManualBroker` (holdings CSV import, orders CSV export, fills from
reconciler) → `KiteBroker` (P2; daily-token constraint documented). Domain is ISIN-keyed;
adapters own symbol shims.

## 6.10 Ops & monitoring
Dead-man ping at pipeline end · absence-of-data alarms per feed (e.g., "no filings parsed
in 3 business days in results season") · weekly data-quality HTML · backup job + restore
runbook (doc 17). Failure mode covered by design: the box's own death is detected
externally (healthchecks.io), never by the box.
