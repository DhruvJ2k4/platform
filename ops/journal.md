# Ops journal

## 2026-07-12 — P0-01
- Surprise: `src/platform` is shadowed by Python's stdlib `platform` module — the package could
  never be imported under pytest or console scripts. Resolved: import package renamed to `quant`
  (ADR-020); repo dir, CLI command, and distribution keep the name `platform`; doc 20 and
  CLAUDE.md updated in the same pass.
- Surprise: CLAUDE.md references `docs/design/` but the docs lived in `docs/decisions/`.
  Resolved: directory renamed to `docs/design/` (the docs carry no self-references either way).
- CI: both `|| true` escapes removed ahead of their stated schedule — import-linter contracts now
  exist, and mypy `--strict` passes on the skeleton trio today. `uv sync --locked` now enforces
  the committed lockfile in CI.
- New dev dependency beyond the ADR-010 stack, user-approved in the P0-01 plan: `detect-secrets`
  (doc 23's mandated pre-commit secret scan).

## 2026-07-12 — P0-02
- Doc 08 says every curated fact row carries `available_at`; doc 10's DDL puts it only on
  corporate_actions/fundamentals_pit (events has observed_at). Resolved with operator:
  transcribe doc 10 as authored — daily-published tables are PIT by `d <= asof`; columns are
  additive later if P0-13 needs them.
- DuckDB traps found and closed (ADR-021): bare DECIMAL silently means DECIMAL(18,3) → explicit
  (p,s) everywhere, test-enforced; `.df()` degrades DECIMAL to float64 → Arrow path
  (quant.schemas.arrow_frame) is the canonical typed read; `asof` is a reserved word (like
  `order`) → quoted in proposal DDL.
- quant.schemas deliberately imports no duckdb so engine → schemas stays clean under
  import-linter's transitive forbidden check. The DDL loader raises FileNotFoundError until the
  P0-03 exception taxonomy provides ConfigError.

## 2026-07-12 — P0-03
- `pyyaml` declared as a runtime dependency (was only transitively present via pre-commit);
  yaml configs are designed-in (docs 20/23), flagged and approved in the plan.
- Rate files carry a single verified epoch (effective_from 2024-07-23, Finance (No.2) Act
  2024 / doc-12 rates). Dates before it fail loudly by design; P1-02/P1-03 add golden-tested
  historical epochs. Custom Decimal-preserving YAML loader guarantees rates never exist as
  binary floats.
- Doc-23 exception taxonomy landed in quant/errors.py (bottom import-linter layer);
  quant/config.py sits just above quant.schemas. schemas.ddl_sql now raises ConfigError as
  promised in the P0-02 entry.

## 2026-07-12 — P0-04
- Doc 06 "registry upsert idempotent by (source, logical_date)" vs doc 08 "supersession
  creates a new row" reconciled via content-addressed filenames ({source}-{date}-{sha12}):
  identical bytes → complete no-op (the DoD); changed bytes → new file + appended row;
  nothing overwritten or deleted; landed raw files are chmod 0o444.
- Crash-safety ordering: file lands (tmp + fsync + atomic rename) BEFORE its registry row,
  so a crash between the two heals on the next ingest; a registered-but-missing file is
  restored without a new row and logged as a warning.
- fetched_at is naive UTC (matches the timestamp[us] contract); injectable for tests.
  Global structlog JSON config is deferred to P0-06 CLI wiring — store logs via defaults.

## 2026-07-13 — ops: process encoded as skills + review agents
- The P0-01..04 working discipline is now executable by any model/session: four project
  skills (.claude/skills/: task, verify, review-domains, ship) and nine read-only reviewers
  in two panels (.claude/agents/ — engineering: arch-purity-guard, money-auditor,
  contract-auditor, docs-warden, test-warden; quant desk: quant-researcher, risk-manager,
  execution-trader, portfolio-manager — the desk panel also reviews plans/ideas), all
  referenced from CLAUDE.md. .gitignore now commits .claude/skills|agents|settings.json
  while still ignoring session cruft.
- Dogfooded on this very change: test-warden ran the full mandate and returned one NOTE
  (verify skill header overclaimed "exact gates CI runs" — fixed same pass; carried: CI's
  per-directory pytest split would skip a future suite dir outside the four known ones).
  Two reviewers hit the org's monthly agent spend limit mid-run; their checks were executed
  inline instead. Newly added agent names register at session start — same-session use
  falls back to general-purpose + "adopt the agent file's mandate".

## 2026-07-13 — P0-05
- NSE's edge gates on CLIENT SHAPE more than IP. Archives hosts: 200 with four browser
  headers (UA/Accept/Accept-Language/Referer), 403 bare-UA — P0-06's adapter must send all
  four. www API: 403 pre-cookie for httpx AND curl, from residential AND datacenter alike →
  TLS-fingerprint gating; the P0-21 collector needs a browser-grade client.
- Epoch map final: classic-11 (≤2011-01), classic-13 (+TOTALTRADES,ISIN; H1-2011→2024-06),
  UDiFF-34 (2024-07-08→). 13 dated samples hoarded via RawStore. Parser plan: dispatch on
  header signature with an explicit allowlist (unknown header = ParseError); 2 parsers,
  3 fixtures; pre-2011 rows carry no ISIN → P0-09 resolves that era via (symbol, series).
- DC fallback (single Google Cloud vantage): archives tolerated → ADR-009's fallback path is
  alive for bhavcopy; ADR-009 itself unchanged. Announcements portal archive reaches ≥
  Jan-2015 WITH broadcast timestamps; attachment PDFs served from the tolerant nsearchives
  host. Request discipline held: ≤25 residential + 4 DC; both 403s triggered immediate stops.
- Desk-panel debut: portfolio-manager reviewed the plan pre-approval (1 WARN + 2 NOTEs, all
  folded in). Post-change review executed inline (docs-only diff + spike scripts; agent
  budget conserved after earlier 429s).

## 2026-07-13 — P0-06
- First adapter live: `platform ingest bhavcopy --since 2026-05-25 --until 2026-07-10` →
  stored=32, noop=1 (2026-07-08, hoarded during P0-05 — live idempotency proof), holiday=2
  (real mid-week 404s on 2026-05-28 and 2026-06-26, logged as expected absence, exit 0).
  DoD "30 recent days ingested" met with margin; 33 distinct trading days in range.
- "Holiday 404 handled via calendar" at P0-06 = weekends skipped by the range iterator +
  weekday 404 recorded as a presence signal for P0-08 (the calendar derives FROM bhavcopy
  presence and cannot pre-exist the adapter); the presence↔calendar cross-check lands with
  P0-08. PM plan review (3 WARN + 2 NOTE) shaped: range ends at last COMPLETED day, widened
  for unconditional ≥30; testzip() CRC gate; --until/--json recorded as additive doc-14
  extensions.
- Recorded deferral, not deviation: 403/429 → abort-on-first-error for foreground backfills;
  doc 06 §6.1's exponential-backoff + alert IP-block mode belongs to the nightly-cron era
  and lands with P0-17 alerting.

## 2026-07-13 — P0-07
- Three-epoch parser landed (quant/curate/parsers/bhavcopy.py): exact-header allowlist
  dispatch, ParseError on unknown signatures and on UDiFF invariant drift (Sgmt/Src/
  FinInstrmTp) — the new-epoch alarm. Money is Decimal from first parse into decimal128(p,s).
- Corrected my own P0-05 doc-09 note: series filtering moved OFF the parser to the universe
  candidate layer (doc 21 §4 / ADR-006 single choke point) — parser filtering would have
  severed EQ→BE→EQ price history. Regression-locked by the non-EQ-survives tests.
- PM plan review caught my guessed row-count band being falsified by on-disk files; the band
  is now a measured output: all 45 registered raw files parse with zero failures — classic-11
  1,358–1,468 · classic-13 1,516–2,757 · udiff 2,802–3,479 (recorded in doc 09 for the DQ
  gate). ParsedBhavcopy is an interface contract, deliberately outside TABLES/doc-10
  governance (guard noted in quant.schemas docstring).

## 2026-07-14 — P0-08
- Adapter extended (additive) for calendar-grade backfills: era-aware URLs (classic archive
  pattern ≤ 2024-07-07 via sources.yaml classic_url_template — the P0-06 UDiFF-only adapter
  would have 404'd all pre-cutover dates and poisoned presence) and --include-weekends
  (Muhurat 2023-11-12 was a SUNDAY; an explicit --date now always fetches).
- 3-year backfill: 2023-07-01..2026-05-22 with weekends → stored=713, holiday/absent=340,
  zero failures. Raw vault now holds ~758 trading days of bhavcopy.
- Session-taxonomy finding (data-driven, closes doc 10's open note): every UDiFF file
  carries SsnId=F1 — 498/498, INCLUDING Muhurat 2024-11-01 and 2025-10-21 — so the data
  alone cannot identify Muhurat; and weekend presence also matches NSE DR-drill Saturdays
  (2024-01-20/03-02/05-18) and Budget-day sessions (2025-02-01, 2026-02-01). Final enum:
  normal | special (weekend presence or non-F1 SsnId drift alarm) | muhurat (operator-
  maintained config/calendar.yaml, NSE-circular-sourced; reviewed at the doc-17 annual pass).
- Live DoD: 750 trading days across 3 sample years (2024: 249, 2025: 249); 10 known
  holidays absent; muhurat exactly [2023-11-12, 2024-11-01, 2025-10-21]; specials correctly
  separated. Closes the P0-06 carried clause (presence↔calendar cross-check). Calendar
  persistence into the curated store lands with P0-11's atomic publish (builder returns a
  validated frame for now). Classic-era weekday-Muhurat limitation resolved via config, not
  heuristics. Post-diff reviews inline again (org agent spend limit).

## 2026-07-15 — P0-09
- Security master landed (quant/curate/master.py): observations-first construction with the
  symbolchange file pinning gap boundaries and backdating pre-observation chains (ADR-022).
  Live file probed+ingested in one request: NO header row (shape validation is the drift
  alarm, not a header allowlist), depth 1999→present, self-rename artifact rows (dropped by
  the builder), applicable_from == first trading day under the new symbol for all three
  vault-verified renames.
- Probe killed my planned invariant before it shipped: an ISIN legitimately trades the same
  symbol in MULTIPLE series the same day (EQ+BL block window, EQ+T0, BE+BL — 29/40 sampled
  files). Interval model is per (isin, symbol, series) with rename boundaries at symbol
  level; "one series per ISIN-day" would have blocked the build almost daily.
- Desk-panel plan review (PM 1 WARN + 5 NOTE, QR 5 WARN + 5 NOTE) reshaped the task: doc 21
  §4 candidates line amended in-pass (open-past listings would leak future/dead names into
  "listings active on d"); snapshot-truncation invariance became property test #4 (the
  time-consistency proof); PREVCLOSE splice validator added as the early net for the
  recycled-symbol limitation; identity-only rule (never existence/age/activity) is a hard
  requirement forwarded to P0-13.
- Effort honesty: full surface (adapter + parser + builder + resolver + schema widening +
  ADR + 5 test files) exceeded doc 20's 8h estimate — recorded as fact, not silent drift.
  Master persistence follows the P0-08 precedent (validated frames now; P0-11 publishes).
- Carried to P0-17: symbolchange re-fetch on the nightly list. Carried to P0-19: hit-rate
  baseline split died-before vs survived-past ISIN coverage; severed-chain counts (ISIN
  reissue events).
- Live-demo encounter (fixed same pass): bond ISIN INE148I07ND6 published ONE day
  (2024-07-26) under the issuer's renamed equity symbol SAMMAANCAP inside its own
  965IHFL25C span, then moved to 965SCL25C — real overlapping symbol spans for one ISIN.
  The interleave ContractViolation would have blocked every full-vault build; same-ISIN
  overlap is not an identity ambiguity, so such spans are now evidence-bounded parallel
  eras (counted in stats.parallel_spans, warned). Cross-ISIN same-day conflict remains
  fatal. ADR-022 amended.
- Breadcrumb for P0-11: bhavcopy holds parallel series rows per (isin, day) (EQ+BL, EQ+T0)
  but prices_adj's PK is (isin, d) — curation must pick the primary series row per day or
  the PK is unsatisfiable.
- Org agent spend limit hit mid-review: the 6-agent post-diff panel died at launch; review
  executed inline (P0-07/P0-08 precedent).
- Second live-demo encounter (fixed same pass): an ISIN CHANGE with the symbol kept —
  AARVEEDEN moved INE273D01019→INE273D01027 — made the new ISIN's chain-backdated era
  overlap the old ISIN's observed era. Repair now runs three deterministic passes per
  (symbol, series): synthetic claims yield to any ISIN's observations (clip to after last
  observation / drop when falsified, stats.synthetic_dropped), open ends retreat to
  evidence, then a verify pass where any surviving overlap raises. Splice DQ restricted to
  boundaries ≤7 calendar days wide — with sparse pre-2023 sample days, wider "boundaries"
  compare prices years apart and are incomparable, not failures.
- Third and fourth live-demo encounters (fixed same pass): (a) IPAPPM→ANDPAPER→ANDHRAPAP —
  a MULTI-HOP rename path whose intermediate symbol was never observed; boundary pinning is
  now gap BRIDGING (walk the rename graph backward inside the gap, cap 6 hops, emit exact
  synthetic intermediate eras). (b) Rename records are now globally consumed (explained at
  most once, earliest-observed ISIN first, pins and chains sharing one ledger) and the
  conflict-repair retreat orders the pair by EVIDENCE, not claim date — otherwise the
  post-ISIN-change line stole its predecessor's symbol history (ANDHRAPAP, TRIDENT,
  AARVEEDEN all hit variants of this). Full-vault core build now green: 6,839 securities /
  10,842 listings; splice DQ 431 pass, 0 fail, 613 incomparable (sparse gaps); 344
  synthetic eras; 230 chain stops; 586 recycle clips.

## 2026-07-16 — P0-10
- CA source resolved by live probe (the P0-05 spike never covered it): no bulk file on the
  tolerant nsearchives host (4 paths → 404); the source is the www JSON API
  `corporates-corporateActions?index=equities&from_date&to_date`. Doc-vs-reality: doc 09 P0-05
  said the www API needs a browser-grade client (P0-21) — FALSE for this endpoint. It is
  COOKIE-gated: the homepage 403 still sets the Akamai cookie, then the API returns 200 to a
  plain httpx client. Adapter cookie-primes (SourceSpec.prime_url; the 403 prime is tolerated,
  not gated). Window is uncapped — one call returned 2021-07→2026-07 (12,182 rows, 3.7 MB). Doc
  09 amended; P0-21's separate browser-grade need is unchanged.
- Two probe findings reshaped the design (both would have been silent money bugs): (1)
  caBroadcastDate is null for ALL rows — no announcement timestamp in this feed → available_at
  set conservatively to ex_date (look-ahead-safe; P0-21 refines). (2) faceVal is anachronistic
  — the CURRENT face value, = the POST-split value in 251/263 splits, 0 ISINs with >1 faceVal —
  so split ratios are parsed from the subject text (never faceVal) and rights issue price S is
  unrecoverable → rights are ALWAYS needs_review (ADR-023), not auto.
- Classifier is a conservative rules engine over human-entered free-text subjects (typos:
  divdend, inteirm, "Bonus- 1:2", "Rights Issue 4:17"). Content ambiguity → needs_review, never
  a crash; only structural JSON drift (non-list body / missing consumed key) is a ParseError;
  nothing price-affecting is silently dropped (fallthrough = other/needs_review). Pinned column
  conventions (doc 21 §1): split num/den=old/new face value → factor den/num (covers
  consolidations); bonus num/den=X:Y → factor den/(num+den); dividend cash=Σ per-share
  (compounds summed); amount-less dividend → needs_review, never 0.
- Desk/Ultraplan corrections folded in before code: kind=demerger-for-everything was a semantic
  lie → additive kind='other' (ADR-023; pandera + doc-10 comment, no DDL — SQL has no CHECK),
  with doc 21 §4/§6 hard-exclusion generalized "pending demerger" → "any needs_review CA";
  EQ-only filter replaced by a non-equity-instrument EXCLUDE-list (GS/IV/RR) so a real equity CA
  tagged non-EQ is never dropped (CAs are ISIN-level facts); preference-share bonus ("Bonus
  Ncrps") routed to needs_review (a false equity dilution otherwise); multi-action subjects (2
  in 5y, both scheme+bonus) → other/needs_review via precedence, not a silent second-action drop.
- DoD interpretation (P0-08/P0-09 precedent): "5y CA table populated" = builder returns a
  validated corporate_actions frame; persistence lands with P0-11's atomic publish.
- Live 5y build: 12,179 parsed (3 exact dupes collapsed) → 8,205 CA rows; per-kind
  split 264 / bonus 264 / dividend 7,270 / rights 195 / buyback 148 / demerger 58 / other 6;
  auto 7,930, needs_review 275 (all demerger+rights+other + amount-less dividends + preference
  bonus); 818 non-equity dropped, 3,156 meetings dropped; conservation balances.
- Carried: per-component dividend rows if P0-12 needs them (currently summed); broadcast-ts
  available_at refinement → P0-21; nightly incremental window → P0-17.
- Desk+engineering review (9 agents, all launched successfully this time — no spend-limit fallback):
  contract-auditor PASS; arch-purity 1 NOTE (parser sort key made total-order — fixed).
  Money-critical finds converged across money-auditor/execution-trader/risk-manager/quant-researcher
  and were fixed in-pass: (a) zero/sub-rupee ratios were classified auto → factor 0 or ÷0 in the
  adjuster; now any non-positive or non-integer face-value ratio → needs_review (_positive gate,
  _FV_RE widened to see decimals). (b) _dividend_total summed EVERY rupee token → face-value/interest
  figures inflated cash and an amount-less "on face value Rs 10" fabricated a credit; now non-dividend
  monetary clauses are masked before summing (compounds still add up) and a 0/absent total →
  needs_review. (c) dividend branch now applies the non-equity-instrument guard (preference/cumulative
  dividends → needs_review), matching split/bonus. (d) builder classifies BEFORE the isin/ex_date
  gate so a real action can't vanish silently for missing identity/date — such drops now warn with
  kind+status (hard-exclusion integrity). (e) unexpected series tags are kept-but-alarmed.
  Impact on the live build: auto 7930→7929, needs_review 275→276 (one ambiguous "Interest Dividend"
  → review); all other counts unchanged. New tests lock every fix + a numeric factor-convention anchor.
- WARN justified (not fixed — fixing would fabricate): available_at=ex_date makes a needs_review
  CA's hard-exclusion first visible on ex_date, not during the pre-ex announce window. The feed has
  no announcement date (caBroadcastDate null) and record/book-closure dates are LATER than ex_date;
  setting an earlier available_at would be a guessed fact and could itself leak. ex_date is the
  evidence-based floor for both the price path (look-ahead-safe; quant-researcher PASS) and the
  exclusion; the pre-ex exclusion refinement needs P0-21's broadcast-timestamp mining. Carried to
  P0-21; P0-11/P0-13 must not read "no visible CA before ex-date" as "safe to trade into".
- Carried to P0-11: CA feed coverage window may be shorter than price history → the adjuster must
  NaN/exclude price dates before the CA coverage floor (min covered ex_date), never partially adjust
  (quant-researcher missing-past bias). For production the operator ingests the full price-history
  window, not just the DoD's 5y (the API is uncapped). doc 09 "history" corrected to "≥5y probed"
  (only 5y was actually fetched). Bitemporal gap noted: an NSE revision of a historical CA rewrites
  adjusted history while available_at still reads ex_date — relies on raw immutability + supersession
  rows to detect drift (acceptable; CA records rarely revised).
- Persistence deferral fixed at the root: P0-11's doc-20 DoD amended to explicitly own the atomic
  publish of the curated tables returned by P0-08/09/10 (was stranded — P0-11's DoD named only the
  adjuster). doc 24 review-queue count scoped to held/investable ISINs so it stays actionable.

## 2026-07-18 — P0-11
- CA adjuster + curation pipeline + atomic publish landed (curate/{adjust,prices,build,publish}.py;
  `platform curate --rebuild --asof`). Factors are exact Fractions; adjusted o/h/l/c paisa-quantized
  HALF_UP; adj_factor stores the float; volume/traded_value/close_unadj raw. Vault parsed ONCE and
  shared (master alone had re-parsed 758 files; rebuild now ~3.5min end-to-end).
- Doc-vs-reality event (found by hypothesis, not by me): doc 21 §1's invariant "returns identical
  whether adjustment is applied today or later" is UNACHIEVABLE bit-exact on paisa-quantized closes
  — independent half-paisa roundings perturb ratios (100/3→33.33, 101/3→33.67: ratio ≠ 101/100;
  falsified by a single appended split 3:1). Resolution (ADR-024, doc 21 amended): invariance is
  EXACT on close_unadj × adj_factor (property-tested with exact rationals); each published close is
  pinned to be exactly the HALF_UP quantization of the exact value (second property); features
  needing exact long-horizon returns consume the factor path (P1-05 note). Never weakened — the
  naive equality test was replaced by two STRONGER exact statements.
- Golden fixture-date typo caught by the golden run: the draft demerger ex-date (2025-01-20) sat
  AFTER Q5 (2025-01-15) though the hand-computation said "between Q4 and Q5" and blocked Q1..Q4.
  Fixture date corrected to 2024-12-20 to match the documented intent; expected VALUES untouched
  (justification recorded in golden_scenario.py — this is a fixture correction, not a
  golden-value update).
- Operator-approved fork: "blocked ISIN" = PRE-EX WINDOW withholding (doc 12's "unresolved window"
  reading), not whole-ISIN (doc 06 letter amended via ADR-024) — whole-ISIN would have stripped
  ~250 ISINs' provably-correct post-ex history (195 pending rights alone). Live build: 52,534 rows
  blocked across 196 ISINs; RELIANCE's own pending Jio Financial demerger (ex 2023-07-20) demos it.
- Resolutions live in config/ca-resolutions.yaml (curated = f(raw, code, config), doc 08 — a DB row
  would be wiped by rebuild; muhurat-config precedent). Ratio columns keep the ROW KIND's semantics
  (resolved bonus stays den/(num+den)); unmatched/ambiguous resolution = ConfigError.
- Series census (probe): 162 distinct series in the vault → equity INCLUDE-list (EQ>BE>BZ>SM>ST>SZ)
  with priority collapse; auxiliaries (BL/T0/BO/IL) always coexist with exactly one main series
  (1,381 multi-series (isin,day) rows, zero two-main conflicts); duplicate same-series rows =
  ContractViolation. 186 unresolvable classic-11 rows excluded (miss beats guess).
- Live rebuild (asof 2026-07-15): run_id curate-20260715-2fa3ae29; security 6,839 / listing 10,842 /
  calendar 758 / CA 8,205 / prices_adj 1,939,557; coverage_excluded 10,256 (pre-2021-07-15 sample
  days — floor enforced as carried from P0-10); conservation exact. RELIANCE across its 2024-10-28
  bonus: pre-ex adjusted = raw × 1/2 to the paisa. Same-day bonus(1:2)+split(2→1) on INE012Q01021:
  factor exactly 1/3 (61.30 → 20.43); its vault rows END the day before ex — the name stopped
  trading at the boundary (raw truth, verified, not a defect). SECOND FULL REBUILD: same run_id,
  "no-op (identical)" — determinism + idempotency proven on the real vault.
- Deferrals recorded: curate --incremental (rebuild is the correctness path; nightly era);
  band_hit stays NULL (bhavcopy carries no band columns); publish gate v0 = schema + PK + coverage
  + conservation (P0-16 extends); old-version GC is ops housekeeping (immutable versions kept).
- Review ran INLINE (all 9 agent launches died: org monthly spend limit + ECONNRESET —
  P0-07/08/09/10 precedent). Each .claude/agents mandate adopted seat-by-seat, evidence-first:
  arch (lint-imports KEPT ×2; engine untouched; no .df(); no wall-clock in build paths — CLI
  --asof default today is an argument boundary; subprocess git in _code_ref is curate-layer-legal,
  falls back to version) PASS. test (288 green re-run; unique basenames; no network; DoD→named
  tests; golden fixture-date correction justified in-module; invariance reframe is a strengthening)
  1 NOTE fixed: _verify_identical determinism-breach path was untested → integration test added.
  money (hand-recompute 2655.70×1/2=1327.85 ✓; scale() 28-digit-division tie-safety PROBED —
  ties only at terminating quotients, which are exact in-range → argument recorded at the code
  site) 1 NOTE fixed. contract (no schema changes; PricesAdj strict validation at build + door +
  read; DECIMAL survives the hive round-trip — integration-asserted; resolutions-mutated rows
  revalidate) PASS. docs (ADR-024 append-only; 21/06/10/16 propagated; sweep clean) 1 WARN fixed:
  doc 17 RB-4 still said "enter resolved CA row" — an operator would hunt for a DB row; rewritten
  to name config/ca-resolutions.yaml + per-kind ratio semantics. quant-researcher (resolutions
  PIT argument: the resolved factor was public in the circular at ex_date, so applying it to any
  asof ≥ ex_date is information-set-honest; before the operator enters it the build only
  over-blocks — conservative, never leaks; quantized-close rounding bias closed by the
  factor-path rule) PASS with argument recorded. risk (pre-ex closure property-locked; an action
  with available_at > asof not blocking is CONSISTENT with the P0-10 carried WARN — the pre-ex
  announce window awaits P0-21 timestamps; operator-input failure modes all ConfigError; exposure
  measured) PASS. execution (strict e > d boundary — ex-day unadjusted, live-verified; BL never
  becomes a close; volume raw is execution-correct since §3 liquidity math is value-based; NEW
  CARRY: P1-07's fill realism needs a band/circuit source before backtest claims — band_hit NULL
  until then) 1 CARRY. portfolio (all 4 DoD clauses demonstrated; RB-4 workflow now names the
  file; deferrals recorded; curated versions are NOT in the backup set — disposable by design,
  doc 08 — version GC is ops housekeeping) PASS.
- Findings tally: 1 WARN (doc 17 RB-4 — fixed), 2 NOTE (determinism-breach test — added;
  tie-safety comment — added), 1 CARRY to P1-07 (band/circuit source), 0 CRITICAL.
